"""Paper Library data models."""
from __future__ import annotations
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class ParagraphTag(BaseModel):
    section_type: str
    paragraph_index: int = 0
    tags: list[str] = Field(default_factory=list)
    claim_type: str | None = None


class PaperTagResult(BaseModel):
    field: str = ""
    sub_field: str = ""
    keywords: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    innovation_points: list[str] = Field(default_factory=list)
    paragraph_tags: list[ParagraphTag] = Field(default_factory=list)


class DeepAnalysis(BaseModel):
    motivation: str = ""
    mathematical_formulation: str = ""
    experimental_design: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    critical_review: dict[str, Any] = Field(default_factory=dict)
    one_more_thing: str = ""


class LibraryPaper(BaseModel):
    id: UUID | None = None
    paper_id: UUID | None = None
    source_run_id: UUID | None = None
    status: str = "pending"
    field: str | None = None
    sub_field: str | None = None
    keywords: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    innovation_points: list[str] = Field(default_factory=list)
    summary_json: dict[str, Any] = Field(default_factory=dict)
    deep_analysis_json: dict[str, Any] | None = None
    architecture_figure_path: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citation_count: int = 0
    latex_source_path: str | None = None
    compiled_pdf_path: str | None = None
    project_tags: list[str] = Field(default_factory=list)
    is_manually_uploaded: bool = False


class LibraryChunk(BaseModel):
    id: UUID | None = None
    library_paper_id: UUID
    section_type: str
    paragraph_index: int = 0
    text: str
    token_count: int = 0
    tags: list[str] = Field(default_factory=list)
    claim_type: str | None = None
    embedding: list[float] | None = None


class LibraryPaperCreate(BaseModel):
    title: str
    arxiv_id: str | None = None
    doi: str | None = None
    source_run_id: str | None = None
    project_tags: list[str] = Field(default_factory=list)


class LibrarySearchQuery(BaseModel):
    query: str
    field: str | None = None
    sub_field: str | None = None
    project_tag: str | None = None
    limit: int = 20
    offset: int = 0
