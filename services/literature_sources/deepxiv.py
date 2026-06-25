"""DeepXiv command-line literature source wrapper."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import shlex
from typing import Any

from libs.schemas.literature import LiteratureCandidate, LiteratureErrorKind, LiteratureSource
from services.literature_errors import SourceRequestError
from services.literature_sources.base import SourceSearchResult, compact_raw, parse_year


class DeepXivSource:
    source = LiteratureSource.DEEPXIV

    def __init__(
        self,
        options: dict[str, object] | None = None,
        **dependencies: object,
    ) -> None:
        self.options = dict(options or {})
        self.timeout_seconds = self._timeout_seconds(self.options.get("timeout_seconds"))

    async def search(self, query: str, limit: int = 50) -> SourceSearchResult:
        command = self.options.get("command")
        if not command:
            return SourceSearchResult(
                source=self.source,
                unavailable_reason="DeepXiv command is not configured",
            )

        try:
            payload = await self._run_command(command, query, limit)
        except SourceRequestError as exc:
            return SourceSearchResult(
                source=self.source,
                errors=[exc.to_report_error(query)],
            )

        records = payload.get("results", payload) if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            records = []
        return SourceSearchResult(
            source=self.source,
            candidates=[
                candidate
                for index, record in enumerate(records[:limit])
                if (candidate := self._candidate(record, index)) is not None
            ],
        )

    async def close(self) -> None:
        return None

    async def _run_command(self, command: object, query: str, limit: int) -> Any:
        args = command if isinstance(command, list) else shlex.split(str(command))
        process = await asyncio.create_subprocess_exec(
            *[str(arg) for arg in args],
            "--query",
            query,
            "--limit",
            str(limit),
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            await self._kill_and_wait(process)
            raise SourceRequestError(
                source=self.source,
                kind=LiteratureErrorKind.TRANSIENT_ERROR,
                message=f"DeepXiv command timed out after {self.timeout_seconds:g} seconds",
            ) from exc
        except asyncio.CancelledError:
            await asyncio.shield(self._kill_and_wait(process))
            raise
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise SourceRequestError(
                source=self.source,
                kind=self._error_kind(process.returncode),
                message=message or f"DeepXiv command exited with {process.returncode}",
            )
        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SourceRequestError(
                source=self.source,
                kind=self._error_kind(1),
                message=f"DeepXiv returned invalid JSON: {exc}",
            ) from exc

    def _candidate(self, record: object, index: int) -> LiteratureCandidate | None:
        if not isinstance(record, dict):
            return None
        title = str(record.get("title") or "").strip()
        if not title:
            return None
        identifier = record.get("id") or record.get("doi") or record.get("arxiv_id") or index
        return LiteratureCandidate(
            candidate_id=f"DEEPXIV:{identifier}",
            title=title,
            source=self.source,
            doi=str(record["doi"]).strip() if record.get("doi") else None,
            arxiv_id=str(record["arxiv_id"]).strip() if record.get("arxiv_id") else None,
            url=str(record["url"]).strip() if record.get("url") else None,
            abstract=str(record["abstract"]).strip() if record.get("abstract") else None,
            year=parse_year(record.get("year") or record.get("published")),
            venue=str(record["venue"]).strip() if record.get("venue") else None,
            authors=self._authors(record.get("authors")),
            raw=compact_raw(dict(record)),
        )

    def _authors(self, value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(author) for author in value if author]
        return []

    async def _kill_and_wait(self, process: object) -> None:
        kill = getattr(process, "kill", None)
        if kill is not None:
            with suppress(ProcessLookupError):
                kill()
        wait = getattr(process, "wait", None)
        if wait is not None:
            with suppress(ProcessLookupError):
                await wait()

    def _timeout_seconds(self, value: object) -> float:
        try:
            timeout = float(value) if value is not None else 30.0
        except (TypeError, ValueError):
            return 30.0
        return timeout if timeout > 0 else 30.0

    def _error_kind(self, returncode: int | None) -> LiteratureErrorKind:
        return (
            LiteratureErrorKind.TRANSIENT_ERROR
            if returncode is None or returncode >= 500
            else LiteratureErrorKind.UNAVAILABLE
        )
