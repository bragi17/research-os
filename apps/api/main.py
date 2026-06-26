"""Research OS API entry point."""

from apps.api.app import create_app
from apps.api.redis_queue import (
    get_redis,
    set_redis,
)

app = create_app()


def __getattr__(name: str):
    """Compatibility for older tests/imports that read apps.api.main._redis."""
    if name == "_redis":
        return get_redis()
    raise AttributeError(name)


def disable_redis_for_tests() -> None:
    """Disable the shared API Redis connection in tests."""
    set_redis(None)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=8000, reload=True)
