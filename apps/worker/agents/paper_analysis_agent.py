"""
PaperAnalysisAgent — Level 2 deep paper analysis.

Smart Agent, Dumb Tools pattern:
- PLAN: LLM produces comprehensive analysis (structured output)
- EXECUTE: Store results in DB
- Triggered on-demand when user clicks "Run Deep Analysis"
"""
from __future__ import annotations
from typing import Any

from structlog import get_logger

from apps.worker.llm_gateway import LLMGateway, ModelTier
from libs.schemas.library import DeepAnalysis

logger = get_logger(__name__)

ANALYSIS_SYSTEM_PROMPT = """\
You are a senior research paper reviewer conducting a comprehensive analysis.
Support LaTeX math notation in your output where relevant.

Analyze the paper thoroughly and produce:

1. **motivation**: Research motivation — what problem was found, why it needs solving,
   what is the significance of this work. (2-3 paragraphs)

2. **mathematical_formulation**: Key mathematical formulations, loss functions,
   algorithms. Use LaTeX notation (e.g., $$L = \\sum_{i} ...$$). Include derivation
   steps if important.

3. **experimental_design**: Systematic summary of experimental details:
   - models: list of model architectures used
   - datasets: list of datasets with sizes/splits
   - hyperparams: key hyperparameters (lr, batch_size, epochs, etc.)
   - reproducibility_notes: what would someone need to reproduce this

4. **results**: Core experimental results:
   - baselines: methods compared against
   - best_metrics: key metric values achieved
   - key_insights: what the results reveal

5. **critical_review**: As a sharp reviewer:
   - strengths: what this paper does well (3-5 points)
   - weaknesses: limitations and issues (3-5 points)
   - improvements: concrete suggestions for improvement

6. **one_more_thing**: Anything else noteworthy — interesting appendix findings,
   unexpected connections, or insights worth sharing.
"""


class PaperAnalysisAgent:
    """
    Level 2 deep analysis agent.
    Called on-demand when user requests full paper analysis.
    """

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def run(
        self,
        paper_text: str,
        metadata: dict[str, Any],
    ) -> DeepAnalysis:
        """
        Produce comprehensive deep analysis of a paper.

        Args:
            paper_text: Full paper content (LaTeX or parsed text, up to 30k chars)
            metadata: {title, year, venue, authors, ...}

        Returns:
            DeepAnalysis with all sections filled
        """
        user_content = (
            f"Paper title: {metadata.get('title', 'Unknown')}\n"
            f"Year: {metadata.get('year', 'Unknown')}\n"
            f"Venue: {metadata.get('venue', 'Unknown')}\n"
            f"Authors: {', '.join(metadata.get('authors', []))}\n\n"
            f"Full paper content:\n{paper_text[:30000]}\n"
        )

        try:
            result = await self.gateway.chat_structured(
                output_schema=DeepAnalysis,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                tier=ModelTier.HIGH,
            )
            logger.info(
                "paper_analysis_agent.done",
                title=metadata.get("title", "?")[:40],
                motivation_len=len(result.motivation),
                has_math=bool(result.mathematical_formulation),
            )
            return result

        except Exception as exc:
            logger.error("paper_analysis_agent.failed", error=str(exc))
            return DeepAnalysis(
                motivation=f"Analysis failed: {exc}",
            )
