from __future__ import annotations


def test_read_worker_concurrency_prefers_env_file(monkeypatch, tmp_path) -> None:
    from apps.worker.runner import read_worker_concurrency

    env_path = tmp_path / ".env"
    env_path.write_text("WORKER_CONCURRENCY=4\n")
    monkeypatch.setenv("ENV_FILE_PATH", str(env_path))
    monkeypatch.setenv("WORKER_CONCURRENCY", "9")

    assert read_worker_concurrency(default=2) == 4


def test_read_worker_concurrency_clamps_to_supported_range(monkeypatch, tmp_path) -> None:
    from apps.worker.runner import read_worker_concurrency

    env_path = tmp_path / ".env"
    env_path.write_text("WORKER_CONCURRENCY=99\n")
    monkeypatch.setenv("ENV_FILE_PATH", str(env_path))

    assert read_worker_concurrency(default=2) == 16
