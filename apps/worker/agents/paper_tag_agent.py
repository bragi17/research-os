"""
PaperTagAgent — Level 1 paper analysis.

Smart Agent, Dumb Tools pattern:
- PLAN: LLM extracts field/keywords/methods/tags (structured output)
- Result stored for later use (library add = zero extra cost)
"""
from __future__ import annotations
from typing import Any

from structlog import get_logger

from apps.worker.llm_gateway import LLMGateway, ModelTier
from libs.schemas.library import PaperTagResult

logger = get_logger(__name__)

TAG_SYSTEM_PROMPT = """\
You are a research paper tagger. Given a paper's content and metadata,
extract hierarchical labels at paper-level and paragraph-level.

Paper-level: identify the broad field, sub-field, key methods/algorithms,
datasets, benchmarks, and innovation points.

Paragraph-level: for each major section (abstract, introduction, method,
experiment, related_work, conclusion), identify technique tags and claim types.

Claim types: contribution, limitation, future_work, finding, definition, comparison.
"""


class PaperTagAgent:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def run(
        self,
        paper_text: str,
        metadata: dict[str, Any],
    ) -> PaperTagResult:
        user_content = (
            f"Paper title: {metadata.get('title', 'Unknown')}\n"
            f"Year: {metadata.get('year', 'Unknown')}\n"
            f"Venue: {metadata.get('venue', 'Unknown')}\n\n"
            f"Paper content:\n{paper_text[:8000]}\n"
        )

        try:
            result = await self.gateway.chat_structured(
                output_schema=PaperTagResult,
                messages=[
                    {"role": "system", "content": TAG_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                tier=ModelTier.MEDIUM,
            )
            logger.info(
                "paper_tag_agent.done",
                title=metadata.get("title", "?")[:40],
                field=result.field,
                keywords=len(result.keywords),
                paragraph_tags=len(result.paragraph_tags),
            )
            return result

        except Exception as exc:
            logger.error("paper_tag_agent.failed", error=str(exc))
            return PaperTagResult()
