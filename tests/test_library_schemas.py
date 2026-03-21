import pytest
from uuid import uuid4
from libs.schemas.library import (
    LibraryPaper, LibraryChunk, PaperTagResult, ParagraphTag,
    LibraryPaperCreate, LibrarySearchQuery, DeepAnalysis,
)

class TestLibraryPaper:
    def test_create(self):
        p = LibraryPaper(title="Test Paper", status="pending")
        assert p.keywords == []
        assert p.is_manually_uploaded is False

    def test_with_tags(self):
        p = LibraryPaper(title="Test", field="CV", sub_field="3D AD",
                         keywords=["point cloud"], methods=["PatchCore"])
        assert "point cloud" in p.keywords

class TestLibraryChunk:
    def test_create(self):
        c = LibraryChunk(library_paper_id=uuid4(), section_type="method",
                         text="We propose...", tags=["memory bank"])
        assert c.paragraph_index == 0

class TestPaperTagResult:
    def test_create(self):
        r = PaperTagResult(
            field="CV", sub_field="3D AD",
            keywords=["point cloud"], methods=["PatchCore"],
            datasets=["MVTec 3D-AD"], benchmarks=["AUROC"],
            innovation_points=["First to apply..."],
            paragraph_tags=[
                ParagraphTag(section_type="method", paragraph_index=0,
                             tags=["memory bank"], claim_type="contribution")
            ],
        )
        assert len(r.paragraph_tags) == 1

class TestDeepAnalysis:
    def test_create(self):
        d = DeepAnalysis(
            motivation="Found a problem...",
            mathematical_formulation="$$L = ...$$",
            experimental_design={"models": ["PointMAE"], "datasets": ["MVTec"]},
            results={"baselines": ["PatchCore"], "best_metrics": {"AUROC": 95.2}},
            critical_review={"strengths": ["novel"], "weaknesses": ["limited data"]},
            one_more_thing="Interesting appendix",
        )
        assert d.motivation.startswith("Found")

class TestLibrarySearchQuery:
    def test_defaults(self):
        q = LibrarySearchQuery(query="3D anomaly")
        assert q.limit == 20
        assert q.field is None
