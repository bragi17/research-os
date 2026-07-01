"""
Research OS - Authentication & Authorization

JWT-based authentication with user registration, login, and role-based access control.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, model_validator
from structlog import get_logger

from apps.api.database import get_pool

logger = get_logger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    import warnings
    JWT_SECRET = "research-os-dev-secret-DO-NOT-USE-IN-PRODUCTION"
    warnings.warn("JWT_SECRET not set! Using insecure default. Set JWT_SECRET env var for production.", stacklevel=2)
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

FIRST_ADMIN_USERNAME = "wtl"
FIRST_ADMIN_EMAIL = "wtl@research-os.local"
FIRST_ADMIN_PASSWORD = "Pedbtx123456!"

security = HTTPBearer(auto_error=False)


# --- Request/Response Models ---

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5)
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)

class LoginRequest(BaseModel):
    identifier: str | None = Field(default=None, min_length=1)
    email: str | None = Field(default=None, min_length=5)
    password: str

    @model_validator(mode="after")
    def require_identifier_or_email(self) -> "LoginRequest":
        if not self.identifier and not self.email:
            raise ValueError("identifier or email is required")
        return self

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, Any]

class UserResponse(BaseModel):
    id: UUID
    email: str
    username: str
    role: str
    workspace_id: UUID | None
    is_active: bool
    created_at: datetime


# --- Password Hashing ---

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# --- JWT Token ---

def create_access_token(user_id: UUID, email: str, role: str, workspace_id: UUID | None = None) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "workspace_id": str(workspace_id) if workspace_id else None,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token") from None


# --- Database Operations ---

def _validate_first_admin_user(row: Any) -> dict[str, Any]:
    user = dict(row)
    if (
        user.get("username") != FIRST_ADMIN_USERNAME
        or user.get("email") != FIRST_ADMIN_EMAIL
        or user.get("role") != "admin"
        or user.get("is_active") is not True
        or user.get("workspace_id") is None
    ):
        raise RuntimeError(
            "first admin bootstrap conflict: expected "
            f"username={FIRST_ADMIN_USERNAME!r}, email={FIRST_ADMIN_EMAIL!r}, "
            "role='admin', is_active=True, and workspace_id present; found "
            f"username={user.get('username')!r}, email={user.get('email')!r}, "
            f"role={user.get('role')!r}, is_active={user.get('is_active')!r}, "
            f"workspace_id={user.get('workspace_id')!r}"
        )
    return user


async def _fetch_first_admin_candidate(pool: Any) -> Any | None:
    return await pool.fetchrow(
        """
            SELECT * FROM app_user
            WHERE username = $1 OR email = $2
            ORDER BY
                CASE
                    WHEN username = $1 AND email = $2 THEN 0
                    WHEN username = $1 THEN 1
                    ELSE 2
                END,
                created_at ASC,
                id ASC
            LIMIT 1
            """,
        FIRST_ADMIN_USERNAME,
        FIRST_ADMIN_EMAIL,
    )


async def create_user(email: str, username: str, password: str) -> dict[str, Any]:
    pool = await get_pool()
    # Identifier login accepts email or username, so neither value may appear in either namespace.
    existing = await pool.fetchrow(
        """
            SELECT id FROM app_user
            WHERE email = $1 OR email = $2 OR username = $1 OR username = $2
            LIMIT 1
            """,
        email, username,
    )
    if existing:
        raise HTTPException(status_code=409, detail="Email or username already registered")

    user_id = uuid4()
    # Create a default workspace for the user
    workspace_id = uuid4()

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO workspace (id, name, owner_id) VALUES ($1, $2, NULL)""",
            workspace_id, f"{username}'s workspace",
        )
        row = await conn.fetchrow(
            """
                INSERT INTO app_user (id, email, username, password_hash, role, workspace_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, email, username, role, workspace_id, is_active, created_at
                """,
            user_id, email, username, hash_password(password), "research_user", workspace_id,
        )
        # Update workspace owner
        await conn.execute(
            "UPDATE workspace SET owner_id = $1 WHERE id = $2",
            user_id, workspace_id,
        )
    return dict(row)

async def get_user_by_email(email: str) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM app_user WHERE email = $1 AND is_active = true",
        email,
    )
    return dict(row) if row else None

async def get_user_by_identifier(identifier: str) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
            SELECT * FROM app_user
            WHERE (email = $1 OR username = $1) AND is_active = true
            ORDER BY
                CASE WHEN email = $1 THEN 0 ELSE 1 END,
                created_at ASC,
                id ASC
            LIMIT 1
            """,
        identifier,
    )
    return dict(row) if row else None

async def ensure_first_admin_user() -> dict[str, Any]:
    pool = await get_pool()
    existing = await _fetch_first_admin_candidate(pool)
    if existing:
        return _validate_first_admin_user(existing)

    user_id = uuid4()
    workspace_id = uuid4()

    try:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO workspace (id, name, owner_id) VALUES ($1, $2, NULL)",
                workspace_id, f"{FIRST_ADMIN_USERNAME}'s workspace",
            )
            row = await conn.fetchrow(
                """
                    INSERT INTO app_user (id, email, username, password_hash, role, workspace_id, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, true)
                    RETURNING id, email, username, role, workspace_id, is_active, created_at
                    """,
                user_id,
                FIRST_ADMIN_EMAIL,
                FIRST_ADMIN_USERNAME,
                hash_password(FIRST_ADMIN_PASSWORD),
                "admin",
                workspace_id,
            )
            await conn.execute(
                "UPDATE workspace SET owner_id = $1 WHERE id = $2",
                user_id, workspace_id,
            )
    except asyncpg.UniqueViolationError as exc:
        existing = await _fetch_first_admin_candidate(pool)
        if existing:
            return _validate_first_admin_user(existing)
        raise RuntimeError("first admin bootstrap raced with another insert but no account was found") from exc

    return _validate_first_admin_user(row)

async def get_user_by_id(user_id: UUID) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, username, role, workspace_id, is_active, created_at FROM app_user WHERE id = $1",
        user_id,
    )
    return dict(row) if row else None


# --- FastAPI Dependencies ---

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """FastAPI dependency to get the authenticated user.

    Returns user dict with keys: id, email, username, role, workspace_id.
    If no auth header provided, returns a default anonymous user for development.
    """
    if credentials is None:
        # Development mode: allow unauthenticated access with default user
        if os.getenv("AUTH_REQUIRED", "false").lower() != "true":
            return {
                "id": UUID("00000000-0000-0000-0000-000000000000"),
                "email": "anonymous@dev.local",
                "username": "anonymous",
                "role": "admin",
                "workspace_id": UUID("00000000-0000-0000-0000-000000000000"),
            }
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = decode_token(credentials.credentials)
    user_id = UUID(payload["sub"])

    user = await get_user_by_id(user_id)
    if user is None or not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="User not found or disabled")

    return user


def require_role(*roles: str):
    """Factory for role-checking dependency."""
    async def checker(user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required role: {', '.join(roles)}",
            )
        return user
    return checker
