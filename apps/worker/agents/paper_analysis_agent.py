"""
PaperAnalysisAgent — Level 2 deep paper analysis.

Smart Agent, Dumb Tools pattern:
- Uses MULTIPLE focused LLM calls (not one mega-call)
- Each call targets a specific analysis dimension
- Results assembled into DeepAnalysis model
"""
from __future__ import annotations
from typing import Any

from pydantic import BaseModel, Field
from structlog import get_logger

from apps.worker.llm_gateway import LLMGateway, ModelTier
from libs.schemas.library import DeepAnalysis, ExperimentalDesign, ExperimentalResults, CriticalReview

logger = get_logger(__name__)


# ── Focused sub-models for individual calls ──

class MotivationResult(BaseModel):
    motivation: str = ""
    note: str = ""

class MathResult(BaseModel):
    mathematical_formulation: str = ""
    note: str = ""

class ExperimentResult(BaseModel):
    experimental_design: ExperimentalDesign = Field(default_factory=ExperimentalDesign)
    results: ExperimentalResults = Field(default_factory=ExperimentalResults)
    note: str = ""

class ReviewResult(BaseModel):
    critical_review: CriticalReview = Field(default_factory=CriticalReview)
    one_more_thing: str = ""
    note: str = ""


# ── Focused prompts ──

_MOTIVATION_PROMPT = """\
You are analyzing a research paper. Focus ONLY on the research motivation.

Extract:
- motivation: What problem was found? Why does it need solving? What is the significance? (2-3 paragraphs)

IMPORTANT: If the input is empty or insufficient, return motivation as empty string with a note explaining what was missing. Do NOT fabricate data.
"""

_MATH_PROMPT = """\
You are analyzing a research paper. Focus ONLY on mathematical formulations.

Extract:
- mathematical_formulation: Key equations, loss functions, algorithms. Use LaTeX notation ($$L = \\sum ...$$). Include derivation steps if present in the paper.

If the paper has no mathematical content, return an empty string. Do NOT invent equations.

IMPORTANT: If the input is empty or insufficient, return empty string with a note. Do NOT fabricate data.
"""

_EXPERIMENT_PROMPT = """\
You are analyzing a research paper. Focus ONLY on experimental setup and results.

Extract:
- experimental_design: {models: [str], datasets: [str], hyperparams: str, reproducibility_notes: str}
- results: {baselines: [str], best_metrics: str, key_insights: [str]}

Be precise — list actual model names, dataset names, and numeric results from the paper.

IMPORTANT: If the input is empty or insufficient, return empty fields with a note. Do NOT fabricate data.
"""

_REVIEW_PROMPT = """\
You are a sharp, experienced reviewer critically assessing this paper.

Produce:
- critical_review: {strengths: [str] (3-5 points), weaknesses: [str] (3-5 points), improvements: [str] (concrete suggestions)}
- one_more_thing: Anything else noteworthy — appendix findings, unexpected connections, insights worth sharing.

Be specific and constructive. Reference actual paper content in your assessment.

IMPORTANT: If the input is empty or insufficient, return empty fields with a note. Do NOT fabricate data.
"""


class PaperAnalysisAgent:
    """
    Level 2 deep analysis agent using MULTIPLE focused LLM calls.
    Each dimension (motivation, math, experiments, review) gets its own call
    for better quality than a single mega-call.
    """

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def run(
        self,
        paper_text: str,
        metadata: dict[str, Any],
    ) -> DeepAnalysis:
        header = (
            f"Paper title: {metadata.get('title', 'Unknown')}\n"
            f"Year: {metadata.get('year', 'Unknown')}\n"
            f"Venue: {metadata.get('venue', 'Unknown')}\n"
            f"Authors: {', '.join(metadata.get('authors', []))}\n\n"
        )
        content = paper_text[:25000]

        # Run 4 focused calls (sequential to avoid rate limits)
        motivation = await self._call(MotivationResult, _MOTIVATION_PROMPT, header, content, "motivation")
        math = await self._call(MathResult, _MATH_PROMPT, header, content, "math")
        experiments = await self._call(ExperimentResult, _EXPERIMENT_PROMPT, header, content, "experiments")
        review = await self._call(ReviewResult, _REVIEW_PROMPT, header, content, "review")

        result = DeepAnalysis(
            motivation=motivation.motivation if motivation else "",
            mathematical_formulation=math.mathematical_formulation if math else "",
            experimental_design=experiments.experimental_design if experiments else ExperimentalDesign(),
            results=experiments.results if experiments else ExperimentalResults(),
            critical_review=review.critical_review if review else CriticalReview(),
            one_more_thing=review.one_more_thing if review else "",
        )

        logger.info(
            "paper_analysis_agent.done",
            title=metadata.get("title", "?")[:40],
            motivation_len=len(result.motivation),
            strengths=len(result.critical_review.strengths),
            weaknesses=len(result.critical_review.weaknesses),
        )
        return result

    async def _call(self, schema: type, system_prompt: str, header: str, content: str, label: str) -> Any:
        """Single focused LLM call with error handling."""
        try:
            return await self.gateway.chat_structured(
                output_schema=schema,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{header}Paper content:\n{content}"},
                ],
                tier=ModelTier.HIGH,
            )
        except Exception as exc:
            logger.warning(f"paper_analysis.{label}_failed", error=str(exc))
            return None
