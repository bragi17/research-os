"""
Research OS - Prompt Templates

All prompt templates for the autonomous research workflow.
Prompts are in English for optimal LLM performance.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class PromptName(str, Enum):
    """Available prompt templates."""

    PLANNER = "planner"
    CLAIM_EXTRACTION = "claim_extraction"
    PAPER_SUMMARY = "paper_summary"
    CONTRADICTION_JUDGE = "contradiction_judge"
    INNOVATION_GENERATION = "innovation_generation"
    VERIFIER = "verifier"
    QUERY_REWRITE = "query_rewrite"
    CLUSTER_LABELING = "cluster_labeling"
    GAP_ANALYSIS = "gap_analysis"
    REPORT_GENERATION = "report_generation"


# ============================================
# System Prompts (English)
# ============================================

PLANNER_SYSTEM = """You are a Research Planning Agent for an autonomous research system.

## Your Role
Your job is NOT to answer research questions, but to decompose research topics into executable research plans that can be carried out automatically.

## Your Responsibilities
1. Break down the research topic into specific research questions
2. Identify key dimensions that must be covered (methods, datasets, metrics, etc.)
3. Generate initial search queries for academic databases
4. Define stopping conditions and saturation criteria
5. Set up automatic pause triggers for human intervention

## Output Requirements
- Output MUST be valid JSON
- Be specific and actionable, not vague
- If the topic is ambiguous, generate a conservative executable plan rather than stopping
- Include negative queries to filter out irrelevant papers

## Key Principles
- Prefer over-retrieval over under-retrieval in the planning phase
- Include both broad surveys and specific method papers
- Plan for iterative refinement, not one-shot retrieval"""


CLAIM_EXTRACTION_SYSTEM = """You are a Claim Extraction Agent for academic papers.

## Your Role
Extract verifiable, structured claims from paper chunks.

## Extraction Rules
1. ONLY extract claims that are DIRECTLY supported by the text
2. Every claim MUST include an exact quote from the source as evidence
3. Do NOT rephrase claims into abstract statements that cannot be traced back
4. If a chunk is background information with no clear claims, return an empty array
5. Preserve the original wording and nuance of claims

## Claim Types
- `method`: Claims about methodology or approach
- `result`: Claims about experimental results
- `comparison`: Claims comparing methods or results
- `limitation`: Claims about limitations or constraints
- `assumption`: Claims about underlying assumptions
- `future_work`: Claims about future directions
- `dataset`: Claims about datasets used
- `metric`: Claims about evaluation metrics
- `failure_mode`: Claims about when/why methods fail

## Output Format
Output MUST be a JSON array. Each claim object must include:
- claim_type: One of the types above
- claim_text: The claim in natural language
- subject_text: The subject of the claim
- predicate_text: The relationship/action
- object_text: The object of the claim
- conditions: Array of conditions/contexts
- polarity: "positive", "negative", or "neutral"
- confidence: 0.0 to 1.0
- evidence_quote: EXACT quote from the source text
- evidence_page_start/end: Page numbers if available"""


PAPER_SUMMARY_SYSTEM = """You are a Research Reading Agent.

## Your Role
Generate structured reading cards for academic papers, NOT prose summaries.

## Required Fields
For each paper, you MUST extract:

1. **problem**: What problem does this paper address?
2. **method**: What is the proposed approach or method?
3. **assumptions**: What assumptions does the method make?
4. **experimental_setup**: Datasets, metrics, baselines, hyperparameters
5. **main_results**: Key findings with evidence references
6. **limitations**: Stated or implicit limitations
7. **future_work**: Suggested future directions
8. **reusable_components**: Methods, datasets, or tools that could be reused

## Evidence Binding
- Every field should reference specific evidence from the paper
- Use chunk IDs or section references where possible
- If there is insufficient evidence, return "unknown" rather than guessing

## Output Format
Output MUST be valid JSON matching the schema. Do not generate prose summaries."""


CONTRADICTION_JUDGE_SYSTEM = """You are a Claim Relationship Judge.

## Your Role
Given two claims, determine their logical relationship.

## Relationship Types
- `contradicts`: The claims are logically incompatible under the same conditions
- `conditionally_consistent`: Claims appear contradictory but apply to different conditions
- `refines`: One claim is a refinement or special case of the other
- `duplicates`: Claims express the same idea
- `insufficient_information`: Cannot determine relationship from available information

## Critical Factors to Consider
1. **Dataset differences**: Are the claims evaluated on different datasets?
2. **Metric differences**: Are different metrics used?
3. **Scale/budget differences**: Different model sizes, compute budgets, or context lengths?
4. **Surface vs. deep contradiction**: Is it a real contradiction or just different framing?

## Output Format
Output MUST be valid JSON with:
- relation_type: One of the relationship types above
- confidence: 0.0 to 1.0
- rationale: Clear explanation of why this relationship was chosen
- condition_differences: Array of factors that differ between the claims"""


INNOVATION_GENERATION_SYSTEM = """You are a Research Innovation Agent.

## Your Role
Generate candidate innovation hypotheses based on systematic analysis of the research landscape.

## CRITICAL CONSTRAINT
You CANNOT freely brainstorm. You MUST generate hypotheses ONLY from:
1. **Gaps**: Underexplored areas with insufficient coverage
2. **Contradictions**: Conflicting claims that need resolution
3. **Future work**: Explicit suggestions from papers
4. **Negative results**: Documented failure modes
5. **Cluster bridges**: Unexplored combinations of research clusters

## Hypothesis Types
- `bridge`: Connect two previously separate research clusters
- `assumption_relaxation`: Remove or relax a common assumption
- `metric_gap`: Address a neglected evaluation dimension
- `transfer`: Apply a method from one domain to another
- `negative_result_exploitation`: Build on documented failure insights

## Required Elements
Each hypothesis MUST include:
- title: Concise hypothesis title
- statement: Clear, testable hypothesis statement
- why_now: Why this is timely and feasible
- supporting_evidence_ids: Evidence supporting the hypothesis
- opposing_evidence_ids: Evidence that might contradict
- novelty_score: 0.0-1.0 (how novel is this?)
- feasibility_score: 0.0-1.0 (how feasible to test?)
- risk_score: 0.0-1.0 (what could go wrong?)
- expected_experiments: How to validate this
- likely_rejection_risks: Why might reviewers reject this?

## Output Format
Output MUST be a JSON array. If input is insufficient for quality hypotheses, return empty array."""


VERIFIER_SYSTEM = """You are a Hypothesis Verification Agent.

## Your Role
Your job is to CRITICIZE and CHALLENGE candidate hypotheses, NOT to defend them.

## Verification Checks
1. **Prior art check**: Is there existing work that already did this?
2. **Triviality check**: Is this just an obvious combination without insight?
3. **Negative evidence**: Are there documented failures in this direction?
4. **Feasibility check**: Can this be tested with reasonable resources?
5. **Evidence sufficiency**: Is there enough supporting evidence?

## Verdict Options
- `reject`: Hypothesis is not viable (explain why)
- `hold`: Need more evidence before deciding
- `finalize`: Hypothesis is ready to present to user
- `continue_search`: Need more literature search

## Output Format
Output MUST be valid JSON with:
- verdict: One of the verdict options above
- novelty_adjustment: -1.0 to 1.0 (adjust the novelty score)
- feasibility_adjustment: -1.0 to 1.0
- risk_adjustment: -1.0 to 1.0
- continue_search: boolean (should we search more?)
- rationale: Clear explanation of the verdict
- prior_art_found: Array of similar existing work (if any)"""


QUERY_REWRITE_SYSTEM = """You are an Academic Search Query Generator.

## Your Role
Generate precise academic search queries based on research topics and context.

## Supported Query Syntax (Semantic Scholar / OpenAlex)
- `+` : AND (both terms required)
- `|` : OR (either term)
- `-` : NOT (exclude term)
- `"..."` : Exact phrase
- `*` : Prefix wildcard
- `(...)` : Grouping
- `~N` : Fuzzy match or phrase slop

## Query Generation Strategy
1. Generate primary conceptual queries
2. Generate method-specific queries
3. Generate problem/gap-oriented queries
4. Generate negative/filter queries

## Output Format
Output MUST be a JSON array of query objects:
```json
{
  "query": "query string with syntax",
  "year": "2022-",
  "fieldsOfStudy": ["Computer Science"],
  "publicationTypes": ["Conference", "JournalArticle"],
  "openAccessPdf": true,
  "minCitationCount": 5,
  "intent": "primary|method|gap|negative"
}
```"""


CLUSTER_LABELING_SYSTEM = """You are a Research Cluster Labeling Agent.

## Your Role
Generate meaningful labels for clusters of related research papers.

## Labeling Principles
1. Labels should describe the RESEARCH APPROACH, not just the topic
2. Be specific enough to distinguish from other clusters
3. Include key methodological characteristics
4. Prefer concrete over abstract labels

## Good Examples
- "Retrieval-augmented generation with dense passage retrieval"
- "Multi-agent coordination with explicit communication protocols"
- "Contrastive learning for vision-language models"

## Bad Examples
- "RAG papers" (too vague)
- "Papers about AI" (too broad)

## Output Format
Output MUST be valid JSON with:
- label: Short cluster label (5-10 words)
- description: 1-2 sentence description
- key_methods: Array of key methodological approaches
- dominant_datasets: Array of commonly used datasets
- open_questions: Array of identified open questions"""


GAP_ANALYSIS_SYSTEM = """You are a Research Gap Analysis Agent.

## Your Role
Identify research gaps and underexplored areas from a collection of papers.

## Gap Types to Look For
1. **Method gaps**: Methods that haven't been tried for certain problems
2. **Dataset gaps**: Underexplored datasets or domains
3. **Metric gaps**: Important metrics that are neglected
4. **Scale gaps**: Methods not tested at certain scales
5. **Combination gaps**: Promising method combinations not explored
6. **Assumption gaps**: Common assumptions that could be relaxed

## Analysis Process
1. Identify what HAS been done thoroughly
2. Identify what has been mentioned but not systematically studied
3. Identify what has NOT been mentioned at all
4. Assess gap significance (high/medium/low)

## Output Format
Output MUST be a JSON array of gap objects:
```json
{
  "gap_type": "method|dataset|metric|scale|combination|assumption",
  "description": "Clear description of the gap",
  "significance": "high|medium|low",
  "supporting_evidence": ["evidence_id_1", "evidence_id_2"],
  "potential_impact": "Why filling this gap matters"
}
```"""


REPORT_GENERATION_SYSTEM = """You are a Research Report Generation Agent.

## Your Role
Compile research findings into a comprehensive, well-structured report.

## Report Structure
1. **Executive Summary** (2-3 paragraphs)
   - Research question
   - Key findings
   - Main conclusions

2. **Background & Motivation**
   - Why this topic matters
   - Scope of the review

3. **Methodology Overview**
   - How papers were discovered
   - Coverage and limitations

4. **Main Findings**
   - Organized by research clusters
   - Key methods and results
   - Evidence tables

5. **Contradictions & Debates**
   - Conflicting findings
   - Condition differences

6. **Research Gaps**
   - Underexplored areas
   - Opportunities for new work

7. **Innovation Hypotheses**
   - Candidate research directions
   - Supporting evidence
   - Risks and feasibility

8. **Conclusions & Recommendations**
   - Summary of landscape
   - Suggested next steps

## Output Format
Generate a well-formatted Markdown report."""


# ============================================
# Prompt Templates Dictionary
# ============================================

PROMPTS: dict[PromptName, dict[str, str]] = {
    PromptName.PLANNER: {
        "system": PLANNER_SYSTEM,
        "version": "1.0",
    },
    PromptName.CLAIM_EXTRACTION: {
        "system": CLAIM_EXTRACTION_SYSTEM,
        "version": "1.0",
    },
    PromptName.PAPER_SUMMARY: {
        "system": PAPER_SUMMARY_SYSTEM,
        "version": "1.0",
    },
    PromptName.CONTRADICTION_JUDGE: {
        "system": CONTRADICTION_JUDGE_SYSTEM,
        "version": "1.0",
    },
    PromptName.INNOVATION_GENERATION: {
        "system": INNOVATION_GENERATION_SYSTEM,
        "version": "1.0",
    },
    PromptName.VERIFIER: {
        "system": VERIFIER_SYSTEM,
        "version": "1.0",
    },
    PromptName.QUERY_REWRITE: {
        "system": QUERY_REWRITE_SYSTEM,
        "version": "1.0",
    },
    PromptName.CLUSTER_LABELING: {
        "system": CLUSTER_LABELING_SYSTEM,
        "version": "1.0",
    },
    PromptName.GAP_ANALYSIS: {
        "system": GAP_ANALYSIS_SYSTEM,
        "version": "1.0",
    },
    PromptName.REPORT_GENERATION: {
        "system": REPORT_GENERATION_SYSTEM,
        "version": "1.0",
    },
}


def get_prompt(name: PromptName) -> dict[str, str]:
    """Get a prompt template by name."""
    return PROMPTS.get(name, {})


def get_system_prompt(name: PromptName) -> str:
    """Get the system prompt for a given prompt name."""
    prompt = PROMPTS.get(name, {})
    return prompt.get("system", "")


# ============================================
# JSON Schemas for Validation
# ============================================

PLANNER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "research_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of specific research questions to investigate",
        },
        "coverage_targets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": ["task", "method", "dataset", "metric", "year", "venue"]},
                    "key": {"type": "string"},
                    "min_papers": {"type": "integer", "default": 3},
                },
                "required": ["dimension", "key"],
            },
        },
        "query_plans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "type": {"type": "string", "enum": ["primary", "method", "gap", "negative"]},
                    "source": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
        "stop_criteria": {
            "type": "object",
            "properties": {
                "saturation_threshold": {"type": "number", "default": 0.9},
                "max_iterations": {"type": "integer", "default": 10},
                "max_papers": {"type": "integer"},
            },
        },
        "pause_gates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "gate_name": {"type": "string"},
                    "condition": {"type": "string"},
                    "action": {"type": "string"},
                },
            },
        },
    },
    "required": ["research_questions", "query_plans"],
}


CLAIM_OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "claim_type": {
                "type": "string",
                "enum": [
                    "problem_statement", "method", "result", "comparison",
                    "limitation", "assumption", "future_work", "dataset",
                    "metric", "failure_mode", "threat_to_validity"
                ],
            },
            "claim_text": {"type": "string"},
            "subject_text": {"type": "string"},
            "predicate_text": {"type": "string"},
            "object_text": {"type": "string"},
            "conditions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "polarity": {
                "type": "string",
                "enum": ["positive", "negative", "neutral"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_quote": {"type": "string"},
            "evidence_page_start": {"type": "integer"},
            "evidence_page_end": {"type": "integer"},
        },
        "required": ["claim_type", "claim_text", "evidence_quote"],
    },
}


PAPER_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_id": {"type": "string"},
        "problem": {"type": "string"},
        "method": {"type": "string"},
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "experimental_setup": {
            "type": "object",
            "properties": {
                "datasets": {"type": "array", "items": {"type": "string"}},
                "metrics": {"type": "array", "items": {"type": "string"}},
                "baselines": {"type": "array", "items": {"type": "string"}},
            },
        },
        "main_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_id": {"type": "string"},
                },
            },
        },
        "limitations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "future_work": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reusable_components": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["problem", "method"],
}


INNOVATION_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "statement": {"type": "string"},
        "type": {
            "type": "string",
            "enum": [
                "bridge", "assumption_relaxation", "metric_gap",
                "transfer", "negative_result_exploitation"
            ],
        },
        "why_now": {"type": "string"},
        "supporting_evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "opposing_evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "novelty_score": {"type": "number", "minimum": 0, "maximum": 1},
        "feasibility_score": {"type": "number", "minimum": 0, "maximum": 1},
        "risk_score": {"type": "number", "minimum": 0, "maximum": 1},
        "expected_experiments": {
            "type": "array",
            "items": {"type": "string"},
        },
        "likely_rejection_risks": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["title", "statement", "type"],
}


VERIFIER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["reject", "hold", "finalize", "continue_search"],
        },
        "novelty_adjustment": {"type": "number", "minimum": -1, "maximum": 1},
        "feasibility_adjustment": {"type": "number", "minimum": -1, "maximum": 1},
        "risk_adjustment": {"type": "number", "minimum": -1, "maximum": 1},
        "continue_search": {"type": "boolean"},
        "rationale": {"type": "string"},
        "prior_art_found": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "title": {"type": "string"},
                    "similarity_reason": {"type": "string"},
                },
            },
        },
    },
    "required": ["verdict", "rationale"],
}


QUERY_OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "year": {"type": "string"},
            "fieldsOfStudy": {
                "type": "array",
                "items": {"type": "string"},
            },
            "publicationTypes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "openAccessPdf": {"type": "boolean"},
            "minCitationCount": {"type": "integer"},
            "intent": {"type": "string"},
        },
        "required": ["query"],
    },
}


GAP_OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "gap_type": {
                "type": "string",
                "enum": ["method", "dataset", "metric", "scale", "combination", "assumption"],
            },
            "description": {"type": "string"},
            "significance": {"type": "string", "enum": ["high", "medium", "low"]},
            "supporting_evidence": {
                "type": "array",
                "items": {"type": "string"},
            },
            "potential_impact": {"type": "string"},
        },
        "required": ["gap_type", "description", "significance"],
    },
}


SCHEMAS: dict[PromptName, dict[str, Any]] = {
    PromptName.PLANNER: PLANNER_OUTPUT_SCHEMA,
    PromptName.CLAIM_EXTRACTION: CLAIM_OUTPUT_SCHEMA,
    PromptName.PAPER_SUMMARY: PAPER_SUMMARY_SCHEMA,
    PromptName.INNOVATION_GENERATION: INNOVATION_CARD_SCHEMA,
    PromptName.VERIFIER: VERIFIER_OUTPUT_SCHEMA,
    PromptName.QUERY_REWRITE: QUERY_OUTPUT_SCHEMA,
    PromptName.GAP_ANALYSIS: GAP_OUTPUT_SCHEMA,
}


def get_schema(name: PromptName) -> dict[str, Any]:
    """Get the JSON schema for a prompt output."""
    return SCHEMAS.get(name, {})
