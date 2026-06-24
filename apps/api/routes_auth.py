"""Authentication API routes."""

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from structlog import get_logger

from apps.api.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    create_access_token,
    create_user,
    get_current_user,
    get_user_by_email,
    verify_password,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _token_response(user: dict[str, Any], token: str) -> dict[str, Any]:
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(os.getenv("JWT_EXPIRATION_HOURS", "24")) * 3600,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "username": user["username"],
            "role": user["role"],
            "workspace_id": str(user["workspace_id"]) if user.get("workspace_id") else None,
        },
    }


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(request: RegisterRequest) -> dict[str, Any]:
    """Register a new user account."""
    user = await create_user(
        email=request.email,
        username=request.username,
        password=request.password,
    )

    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        workspace_id=user.get("workspace_id"),
    )

    logger.info("user_registered", user_id=str(user["id"]), email=user["email"])
    return _token_response(user, token)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest) -> dict[str, Any]:
    """Authenticate a user and return a JWT token."""
    user = await get_user_by_email(request.email)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        workspace_id=user.get("workspace_id"),
    )

    logger.info("user_logged_in", user_id=str(user["id"]), email=user["email"])
    return _token_response(user, token)


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Get the current authenticated user's profile."""
    return user
