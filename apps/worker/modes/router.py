"""
Research OS - Mode Router (Mode 0)

Classifies user intent and recommends the appropriate research mode.
Rule-based first pass, with LLM fallback for ambiguous cases.
"""
from __future__ import annotations

from libs.schemas.multimode import ModeConfig, ResearchMode

# Keyword sets for each mode (from Doc 06 section 5.4)
ATLAS_KEYWORDS: list[str] = [
    "new to",
    "beginner",
    "入门",
    "overview",
    "survey",
    "landscape",
    "classics",
    "经典",
    "how to start",
    "introduction",
    "路线图",
    "roadmap",
    "taxonomy",
    "分类",
    "history",
    "evolution",
    "understand",
    "learn",
    "onboarding",
    "atlas",
]

FRONTIER_KEYWORDS: list[str] = [
    "recent",
    "最近",
    "top conference",
    "顶会",
    "benchmark",
    "state of the art",
    "sota",
    "pain point",
    "痛点",
    "sub-field",
    "子方向",
    "specific",
    "focused",
    "gap",
    "limitation",
    "future work",
    "cutting edge",
    "comparison",
    "对比",
    "method",
    "approach",
]

DIVERGENT_KEYWORDS: list[str] = [
    "innovation",
    "创新",
    "creative",
    "brainstorm",
    "cross-domain",
    "跨领域",
    "transfer",
    "迁移",
    "analogical",
    "类比",
    "borrow",
    "借鉴",
    "new idea",
    "novel",
    "divergent",
    "发散",
]

REVIEW_KEYWORDS: list[str] = [
    "summarize",
    "总结",
    "report",
    "报告",
    "export",
    "导出",
    "proposal",
    "advisor",
    "导师",
    "refine",
    "rewrite",
    "compile",
    "整理",
]

_MODE_KEYWORD_MAP: dict[ResearchMode, list[str]] = {
    ResearchMode.ATLAS: ATLAS_KEYWORDS,
    ResearchMode.FRONTIER: FRONTIER_KEYWORDS,
    ResearchMode.DIVERGENT: DIVERGENT_KEYWORDS,
    ResearchMode.REVIEW: REVIEW_KEYWORDS,
}


def _score_mode(text_lower: str, keywords: list[str]) -> int:
    """Count how many keywords appear as substrings in the lowered text."""
    return sum(1 for kw in keywords if kw in text_lower)


def classify_mode(user_input: str) -> ResearchMode:
    """Classify user input into a research mode using keyword matching.

    Algorithm:
        1. Lowercase the input.
        2. Score each mode by counting keyword substring matches.
        3. Return the mode with the highest score.
        4. Default to ATLAS when no matches are found or there is a tie
           for the top score.
    """
    text_lower = user_input.lower()

    scores: dict[ResearchMode, int] = {
        mode: _score_mode(text_lower, keywords)
        for mode, keywords in _MODE_KEYWORD_MAP.items()
    }

    max_score = max(scores.values())

    # Default to ATLAS if nothing matched
    if max_score == 0:
        return ResearchMode.ATLAS

    # Collect modes that share the max score
    top_modes = [mode for mode, score in scores.items() if score == max_score]

    # If there is a unique winner, return it; otherwise default to ATLAS
    if len(top_modes) == 1:
        return top_modes[0]

    # Tie-break priority: ATLAS (safe default) > DIVERGENT > FRONTIER > REVIEW
    _TIE_BREAK_ORDER = [
        ResearchMode.ATLAS,
        ResearchMode.DIVERGENT,
        ResearchMode.FRONTIER,
        ResearchMode.REVIEW,
    ]
    for mode in _TIE_BREAK_ORDER:
        if mode in top_modes:
            return mode

    return top_modes[0]


def build_mode_config(
    user_input: str,
    keywords: list[str] | None = None,
    seed_paper_ids: list[str] | None = None,
    constraints: dict | None = None,
    mode_override: ResearchMode | None = None,
) -> ModeConfig:
    """Build a complete ModeConfig from user input.

    Steps:
        1. Classify the mode (or use override).
        2. Assemble a ``ModeConfig`` with the provided parameters.
    """
    mode = mode_override if mode_override is not None else classify_mode(user_input)

    return ModeConfig(
        mode=mode,
        topic=user_input,
        keywords=keywords or [],
        seed_paper_ids=seed_paper_ids or [],
        constraints=constraints or {},
    )
