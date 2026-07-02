from __future__ import annotations

import pytest

from libs.schemas.paper_verification import PaperCandidate, PaperVerificationStatus
from services.paper_verification import (
    PaperVerifier,
    candidate_from_id,
    candidate_key,
    normalize_arxiv_id,
    normalize_doi,
)


class StubVerifier(PaperVerifier):
    async def _verify_arxiv(self, candidate):
        if candidate.arxiv_id == "2505.24431":
            return self._verified(
                candidate,
                method="arxiv",
                title="Verified arXiv Paper",
                arxiv_id="2505.24431",
            )
        return None

    async def _verify_doi(self, candidate):
        if candidate.doi == "10.1000/test":
            return self._verified(
                candidate,
                method="crossref",
                title="Verified DOI Paper",
                doi="10.1000/test",
            )
        return None

    async def _verify_s2(self, candidate):
        if candidate.s2_id == "abc":
            return self._verified(
                candidate,
                method="semantic_scholar",
                title="Verified S2 Paper",
                s2_id="abc",
            )
        return None

    async def _verify_openalex(self, candidate):
        return None

    async def _verify_title(self, candidate):
        if candidate.title == "Known Title":
            return self._verified(candidate, method="title_match", title="Known Title")
        return None


class ExceptionVerifier(StubVerifier):
    async def _verify_doi(self, candidate):
        raise RuntimeError("temporary outage")


class CloseCountingAdapter:
    def __init__(self, *args, **kwargs):
        self.close_count = 0

    async def close(self):
        self.close_count += 1


def test_candidate_key_prefers_stable_identifier():
    assert (
        candidate_key(PaperCandidate(candidate_id="x", arxiv_id="2505.24431"))
        == "arxiv:2505.24431"
    )
    assert (
        candidate_key(PaperCandidate(candidate_id="x", doi="10.1000/test"))
        == "doi:10.1000/test"
    )
    assert candidate_key(PaperCandidate(candidate_id="x", s2_id="abc")) == "s2:abc"


def test_candidate_key_strips_arxiv_version_suffix():
    assert normalize_arxiv_id("2505.24431v2") == "2505.24431"
    assert candidate_key(PaperCandidate(candidate_id="x", arxiv_id="2505.24431v1")) == (
        candidate_key(PaperCandidate(candidate_id="x", arxiv_id="2505.24431v2"))
    )


def test_normalize_doi_strips_url_and_marker():
    assert normalize_doi("https://doi.org/10.1000/Test") == "10.1000/test"
    assert normalize_doi("doi: 10.1000/Test") == "10.1000/test"


def test_candidate_from_openalex_id():
    candidate = candidate_from_id("OA:W123", title="Title", source="recommendation")

    assert candidate == PaperCandidate(
        candidate_id="OA:W123",
        title="Title",
        openalex_id="W123",
        source="recommendation",
    )


def test_candidate_from_raw_s2_id():
    candidate = candidate_from_id("abc123")

    assert candidate.s2_id == "abc123"


def test_candidate_from_title_id_uses_title_matching():
    candidate = candidate_from_id("title:known title", title="Known Title")

    assert candidate.candidate_id == "title:known title"
    assert candidate.title == "Known Title"
    assert candidate.s2_id is None


def test_candidate_from_bare_arxiv_id():
    candidate = candidate_from_id("2505.24431v2")

    assert candidate.arxiv_id == "2505.24431"
    assert candidate.s2_id is None


def test_paper_verifier_accepts_s2_alias():
    stub = CloseCountingAdapter()
    verifier = PaperVerifier(s2=stub)

    assert verifier.s2 is stub
    assert verifier.semantic_scholar is stub


@pytest.mark.asyncio
async def test_close_does_not_close_injected_adapters():
    s2 = CloseCountingAdapter()
    crossref = CloseCountingAdapter()
    openalex = CloseCountingAdapter()
    verifier = PaperVerifier(s2=s2, crossref=crossref, openalex=openalex)

    await verifier.close()

    assert s2.close_count == 0
    assert crossref.close_count == 0
    assert openalex.close_count == 0


@pytest.mark.asyncio
async def test_close_closes_owned_adapters(monkeypatch):
    created = []

    class OwnedAdapter(CloseCountingAdapter):
        def __init__(self, *args, **kwargs):
            super().__init__()
            created.append(self)

    monkeypatch.setattr("services.paper_verification.SemanticScholarAdapter", OwnedAdapter)
    monkeypatch.setattr("services.paper_verification.CrossrefAdapter", OwnedAdapter)
    monkeypatch.setattr("services.paper_verification.OpenAlexAdapter", OwnedAdapter)

    verifier = PaperVerifier()

    await verifier.close()

    assert [adapter.close_count for adapter in created] == [1, 1, 1]


@pytest.mark.asyncio
async def test_verifies_by_arxiv():
    record = await StubVerifier().verify(
        PaperCandidate(candidate_id="p", arxiv_id="2505.24431")
    )
    assert record.verification_status == PaperVerificationStatus.VERIFIED
    assert record.verification_method == "arxiv"


@pytest.mark.asyncio
async def test_unverified_when_all_layers_miss():
    record = await StubVerifier().verify(PaperCandidate(candidate_id="p", title="Unknown"))
    assert record.verification_status == PaperVerificationStatus.UNVERIFIED
    assert record.verification_method == "none"


@pytest.mark.asyncio
async def test_malformed_candidate_is_error():
    record = await StubVerifier().verify(PaperCandidate(candidate_id=""))
    assert record.verification_status == PaperVerificationStatus.ERROR


@pytest.mark.asyncio
async def test_external_exception_is_verify_pending():
    record = await ExceptionVerifier().verify(
        PaperCandidate(candidate_id="p", doi="10.1000/test")
    )

    assert record.verification_status == PaperVerificationStatus.VERIFY_PENDING
    assert record.verification_method == "none"
