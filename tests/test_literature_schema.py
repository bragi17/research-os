"""Tests for literature source schemas."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from libs.schemas.literature import (
    LiteratureCredentialPreview,
    LiteratureSource,
    LiteratureSourceSettings,
    LiteratureSourceUpdate,
)


def test_credential_preview_rejects_invalid_uuid_id() -> None:
    with pytest.raises(ValidationError):
        LiteratureCredentialPreview(id="not-a-uuid")


def test_source_update_masks_new_credentials_by_default() -> None:
    update = LiteratureSourceUpdate(new_credentials=["secret-key"])

    dumped = update.model_dump()

    assert isinstance(update.new_credentials[0], SecretStr)
    assert update.new_credentials[0].get_secret_value() == "secret-key"
    assert dumped["new_credentials"] != ["secret-key"]
    assert str(dumped["new_credentials"][0]) == "**********"


def test_source_update_rejects_invalid_clear_credential_id() -> None:
    with pytest.raises(ValidationError):
        LiteratureSourceUpdate(clear_credential_ids=["not-a-uuid"])


def test_source_update_omitted_options_remains_none() -> None:
    update = LiteratureSourceUpdate()

    assert update.options is None


def test_credential_preview_rejects_unknown_last_status() -> None:
    with pytest.raises(ValidationError):
        LiteratureCredentialPreview(last_status="pending")


def test_source_settings_rejects_unknown_last_test_status() -> None:
    with pytest.raises(ValidationError):
        LiteratureSourceSettings(
            source=LiteratureSource.WEB_SEARCH,
            label="Web search",
            last_test_status="pending",
        )
