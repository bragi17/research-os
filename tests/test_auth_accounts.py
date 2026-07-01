from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import asyncpg
import pytest
from fastapi import FastAPI

import apps.api.auth as auth


USER_ID = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
FIRST_ADMIN_USERNAME = "wtl"
FIRST_ADMIN_EMAIL = "wtl@research-os.local"
FIRST_ADMIN_PASSWORD = "Pedbtx123456!"


def first_admin_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": USER_ID,
        "email": FIRST_ADMIN_EMAIL,
        "username": FIRST_ADMIN_USERNAME,
        "password_hash": "$2b$12$hash",
        "role": "admin",
        "workspace_id": WORKSPACE_ID,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    row.update(overrides)
    return row


def require_auth_attr(name: str):
    assert hasattr(auth, name), f"apps.api.auth is missing {name}"
    return getattr(auth, name)


def require_login_request_with_identifier(routes_auth):
    fields = getattr(routes_auth.LoginRequest, "model_fields", None)
    if fields is None:
        fields = routes_auth.LoginRequest.__fields__
    assert "identifier" in fields
    return routes_auth.LoginRequest


class FakePool:
    def __init__(self) -> None:
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.inserted_user: dict[str, object] | None = None
        self.inserted_workspace: dict[str, object] | None = None
        self.workspace_owner_update: tuple[object, object] | None = None

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        if "WHERE username = $1" in query:
            return None
        if "WHERE (email = $1 OR username = $1)" in query:
            identifier = args[0]
            if identifier in {FIRST_ADMIN_USERNAME, FIRST_ADMIN_EMAIL}:
                return {
                    "id": USER_ID,
                    "email": FIRST_ADMIN_EMAIL,
                    "username": FIRST_ADMIN_USERNAME,
                    "password_hash": "$2b$12$hash",
                    "role": "admin",
                    "workspace_id": WORKSPACE_ID,
                    "is_active": True,
                }
            return None
        if "INSERT INTO app_user" in query:
            self.inserted_user = {
                "id": args[0],
                "email": args[1],
                "username": args[2],
                "password_hash": args[3],
                "role": args[4],
                "workspace_id": args[5],
                "is_active": True,
                "created_at": datetime.now(timezone.utc),
            }
            return self.inserted_user
        return None

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def transaction(self):
        return self

    async def execute(self, query: str, *args: object):
        self.execute_calls.append((query, args))
        if "INSERT INTO workspace" in query:
            self.inserted_workspace = {"id": args[0], "name": args[1], "owner_id": None}
        if "UPDATE workspace SET owner_id = $1 WHERE id = $2" in query:
            self.workspace_owner_update = (args[0], args[1])
        return None


def test_first_admin_constants_are_defined() -> None:
    assert require_auth_attr("FIRST_ADMIN_USERNAME") == FIRST_ADMIN_USERNAME
    assert require_auth_attr("FIRST_ADMIN_EMAIL") == FIRST_ADMIN_EMAIL
    assert require_auth_attr("FIRST_ADMIN_PASSWORD") == FIRST_ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_get_user_by_identifier_checks_email_or_username(monkeypatch: pytest.MonkeyPatch) -> None:
    get_user_by_identifier = require_auth_attr("get_user_by_identifier")
    pool = FakePool()
    monkeypatch.setattr("apps.api.auth.get_pool", AsyncMock(return_value=pool))

    user = await get_user_by_identifier("wtl")

    assert user is not None
    assert user["username"] == FIRST_ADMIN_USERNAME
    assert "WHERE (email = $1 OR username = $1)" in pool.fetchrow_calls[0][0]


@pytest.mark.asyncio
async def test_first_admin_seed_is_idempotent_when_user_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_first_admin_user = require_auth_attr("ensure_first_admin_user")

    class ExistingPool(FakePool):
        async def fetchrow(self, query: str, *args: object):
            self.fetchrow_calls.append((query, args))
            if "WHERE username = $1" in query:
                return first_admin_row(id="existing")
            return await super().fetchrow(query, *args)

    pool = ExistingPool()
    monkeypatch.setattr("apps.api.auth.get_pool", AsyncMock(return_value=pool))

    user = await ensure_first_admin_user()

    assert user["id"] == "existing"
    assert pool.execute_calls == []


@pytest.mark.asyncio
async def test_first_admin_seed_rejects_existing_username_that_is_not_bootstrap_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_first_admin_user = require_auth_attr("ensure_first_admin_user")

    class ConflictingPool(FakePool):
        async def fetchrow(self, query: str, *args: object):
            self.fetchrow_calls.append((query, args))
            if "WHERE username = $1" in query:
                return first_admin_row(email="someone@example.test", role="research_user")
            return await super().fetchrow(query, *args)

    pool = ConflictingPool()
    monkeypatch.setattr("apps.api.auth.get_pool", AsyncMock(return_value=pool))

    with pytest.raises(RuntimeError, match="first admin"):
        await ensure_first_admin_user()

    assert pool.execute_calls == []


@pytest.mark.asyncio
async def test_first_admin_seed_rejects_existing_email_that_is_not_bootstrap_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_first_admin_user = require_auth_attr("ensure_first_admin_user")

    class ConflictingPool(FakePool):
        async def fetchrow(self, query: str, *args: object):
            self.fetchrow_calls.append((query, args))
            if "username = $1 OR email = $2" in query:
                return first_admin_row(username="someone")
            if "WHERE username = $1" in query:
                return None
            return await super().fetchrow(query, *args)

    pool = ConflictingPool()
    monkeypatch.setattr("apps.api.auth.get_pool", AsyncMock(return_value=pool))

    with pytest.raises(RuntimeError, match="first admin"):
        await ensure_first_admin_user()

    assert pool.execute_calls == []


@pytest.mark.asyncio
async def test_first_admin_seed_recovers_when_concurrent_insert_wins_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_first_admin_user = require_auth_attr("ensure_first_admin_user")

    class RacingPool(FakePool):
        def __init__(self) -> None:
            super().__init__()
            self.first_admin_fetches = 0

        async def fetchrow(self, query: str, *args: object):
            self.fetchrow_calls.append((query, args))
            if "username = $1 OR email = $2" in query or "WHERE username = $1" in query:
                self.first_admin_fetches += 1
                if self.first_admin_fetches == 1:
                    return None
                return first_admin_row()
            if "INSERT INTO app_user" in query:
                raise asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
            return None

    pool = RacingPool()
    monkeypatch.setattr("apps.api.auth.get_pool", AsyncMock(return_value=pool))

    user = await ensure_first_admin_user()

    assert user["username"] == FIRST_ADMIN_USERNAME
    assert user["role"] == "admin"
    assert pool.first_admin_fetches == 2


@pytest.mark.asyncio
async def test_create_user_rejects_cross_namespace_email_username_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_user = require_auth_attr("create_user")

    class CollisionPool(FakePool):
        async def fetchrow(self, query: str, *args: object):
            self.fetchrow_calls.append((query, args))
            if "FROM app_user" in query and "INSERT INTO app_user" not in query:
                proposed_email, proposed_username = args
                existing_email = "owner@example.test"
                existing_username = "shared-name"
                checks_both_namespaces = (
                    str(query).count("$1") >= 2 and str(query).count("$2") >= 2
                )
                if checks_both_namespaces and (
                    proposed_email in {existing_email, existing_username}
                    or proposed_username in {existing_email, existing_username}
                ):
                    return {"id": USER_ID}
                return None
            return await super().fetchrow(query, *args)

    pool = CollisionPool()
    monkeypatch.setattr("apps.api.auth.get_pool", AsyncMock(return_value=pool))

    with pytest.raises(auth.HTTPException) as exc_info:
        await create_user("shared-name", "new-user", "Pedbtx123456!")

    assert exc_info.value.status_code == 409
    assert pool.inserted_user is None


@pytest.mark.asyncio
async def test_first_admin_seed_creates_admin_workspace_and_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_first_admin_user = require_auth_attr("ensure_first_admin_user")
    pool = FakePool()
    monkeypatch.setattr("apps.api.auth.get_pool", AsyncMock(return_value=pool))

    user = await ensure_first_admin_user()

    assert user["email"] == FIRST_ADMIN_EMAIL
    assert user["username"] == FIRST_ADMIN_USERNAME
    assert user["role"] == "admin"
    assert pool.inserted_user is not None
    assert pool.inserted_user["password_hash"] != FIRST_ADMIN_PASSWORD
    assert str(pool.inserted_user["password_hash"]).startswith("$2")
    assert pool.inserted_workspace is not None
    assert pool.inserted_workspace["owner_id"] is None
    assert pool.workspace_owner_update == (pool.inserted_user["id"], pool.inserted_user["workspace_id"])


@pytest.mark.asyncio
async def test_login_accepts_username_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    import apps.api.routes_auth as routes_auth

    LoginRequest = require_login_request_with_identifier(routes_auth)
    assert hasattr(routes_auth, "get_user_by_identifier")
    password_hash = auth.hash_password(FIRST_ADMIN_PASSWORD)
    monkeypatch.setattr(
        routes_auth,
        "get_user_by_identifier",
        AsyncMock(return_value={
            "id": USER_ID,
            "email": FIRST_ADMIN_EMAIL,
            "username": FIRST_ADMIN_USERNAME,
            "password_hash": password_hash,
            "role": "admin",
            "workspace_id": WORKSPACE_ID,
            "is_active": True,
        }),
    )

    response = await routes_auth.login(
        LoginRequest(identifier="wtl", password=FIRST_ADMIN_PASSWORD),
    )

    assert response["access_token"]
    assert response["user"]["username"] == "wtl"
    assert response["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_login_accepts_email_for_backward_compatibility(monkeypatch: pytest.MonkeyPatch) -> None:
    import apps.api.routes_auth as routes_auth

    LoginRequest = require_login_request_with_identifier(routes_auth)
    fields = getattr(routes_auth.LoginRequest, "model_fields", None)
    if fields is None:
        fields = routes_auth.LoginRequest.__fields__
    assert "email" in fields
    assert hasattr(routes_auth, "get_user_by_identifier")
    password_hash = auth.hash_password(FIRST_ADMIN_PASSWORD)
    get_user = AsyncMock(return_value={
        "id": USER_ID,
        "email": FIRST_ADMIN_EMAIL,
        "username": FIRST_ADMIN_USERNAME,
        "password_hash": password_hash,
        "role": "admin",
        "workspace_id": WORKSPACE_ID,
        "is_active": True,
    })
    monkeypatch.setattr(routes_auth, "get_user_by_identifier", get_user)

    response = await routes_auth.login(
        LoginRequest(email=FIRST_ADMIN_EMAIL, password=FIRST_ADMIN_PASSWORD),
    )

    assert response["access_token"]
    get_user.assert_awaited_once_with(FIRST_ADMIN_EMAIL)


@pytest.mark.asyncio
async def test_register_still_creates_research_user_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    import apps.api.routes_auth as routes_auth

    monkeypatch.setattr(
        routes_auth,
        "create_user",
        AsyncMock(return_value={
            "id": USER_ID,
            "email": "researcher@example.test",
            "username": "researcher",
            "role": "research_user",
            "workspace_id": WORKSPACE_ID,
            "is_active": True,
        }),
    )

    response = await routes_auth.register(
        routes_auth.RegisterRequest(
            email="researcher@example.test",
            username="researcher",
            password="Pedbtx123456!",
        ),
    )

    assert response["access_token"]
    assert response["user"]["role"] == "research_user"


@pytest.mark.asyncio
async def test_lifespan_ensures_first_admin_after_database_before_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.app as api_app

    calls: list[str] = []

    async def init_pool() -> None:
        calls.append("database")

    async def ensure_first_admin_user() -> None:
        calls.append("first_admin")

    async def init_redis() -> None:
        calls.append("redis")

    async def close_redis() -> None:
        calls.append("close_redis")

    async def close_pool() -> None:
        calls.append("close_pool")

    monkeypatch.setattr(api_app.database, "init_pool", init_pool)
    monkeypatch.setattr(api_app, "ensure_first_admin_user", ensure_first_admin_user)
    monkeypatch.setattr(api_app, "init_redis", init_redis)
    monkeypatch.setattr(api_app, "close_redis", close_redis)
    monkeypatch.setattr(api_app.database, "close_pool", close_pool)

    async with api_app.lifespan(FastAPI()):
        assert calls == ["database", "first_admin", "redis"]

    assert calls == ["database", "first_admin", "redis", "close_redis", "close_pool"]
