"""Shared errors for literature source adapters."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from libs.schemas.literature import (
    LiteratureErrorKind,
    LiteratureSource,
    LiteratureSourceError,
)


@dataclass
class SourceRequestError(Exception):
    """Classified error raised by a literature source adapter."""

    source: LiteratureSource
    kind: LiteratureErrorKind
    message: str
    status_code: int | None = None
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message

    def to_report_error(self, query: str | None = None) -> LiteratureSourceError:
        return LiteratureSourceError(
            source=self.source,
            kind=self.kind,
            message=self.message,
            query=query,
            status_code=self.status_code,
            retry_after_seconds=self.retry_after_seconds,
        )


def retry_after_seconds(value: Any) -> float | None:
    """Parse nonnegative numeric Retry-After seconds."""

    if value is None:
        return None

    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None

    if not math.isfinite(seconds) or seconds < 0:
        return None

    return seconds
