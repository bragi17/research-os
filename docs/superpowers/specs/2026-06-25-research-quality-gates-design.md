# Research Quality Gates Design

**Date:** 2026-06-25
**Scope:** Improve Research OS idea generation, paper verification, persistent research memory, and production submission audits by adapting the strongest design patterns from `auto-claude-code-research-in-sleep` without copying its Markdown-skill architecture.
**Approved direction:** Implement as four isolated feature worktrees under `.worktrees/`, then merge back to `main` in dependency order.

## Context

Research OS already has a strong service-oriented research pipeline:

- Frontier mode searches Semantic Scholar and OpenAlex, expands citation chains, reranks candidates, deep-reads papers, extracts claims, builds comparison matrices, and mines pain points.
- Divergent mode normalizes pain points, searches cross-domain analogies, screens transfer candidates, generates idea cards, checks prior art, reviews feasibility, and ranks the final portfolio.
- The production layer already contains projects, experiment plans, jobs, artifacts, claim ledger entries, manuscript packages, and submission gates.

The weaker areas are not workflow shape. They are trust boundaries:

- Paper candidates can flow forward without explicit existence and metadata verification status.
- Idea novelty and quality are judged too much by the same pipeline that generated the ideas.
- Failed ideas and evidence links are not first-class durable memory.
- Production submission gates are mostly static checks and claim status summaries, not fresh audit-class reviews.

The ARIS reference project contributes useful design rules:

- Verify candidate papers before analysis.
- Separate candidate generation from verdicts.
- Persist failed ideas and evidence relationships for anti-repetition.
- Use fresh, independent reviewers for quality or correctness gates.
- Keep auditable artifacts and machine-readable verdicts.

## Considered Approaches

### Approach 1: Direct ARIS Skill Port

Copy ARIS-style Markdown workflows and helpers into Research OS.

Pros:
- Fast to mirror known behavior.
- Easy to compare with ARIS docs.

Cons:
- Does not fit the existing FastAPI, DB, LangGraph, and production scheduler architecture.
- Creates a parallel artifact system outside Research OS tables.
- Harder to expose in the web UI and API consistently.

### Approach 2: Service-Native Quality Gates

Implement ARIS concepts as Research OS services, schemas, DB rows, LangGraph nodes, and production coding tasks.

Pros:
- Fits the current system.
- Reuses existing academic adapters, library, claim ledger, coding task, and submission package flows.
- Makes verification and audit statuses visible through API/UI.
- Keeps artifacts machine-readable and queryable.

Cons:
- Requires schema and test work.
- Merge order matters because later tasks depend on earlier data structures.

### Approach 3: Minimal Prompt-Only Tightening

Only adjust prompts for idea composition, prior-art check, and paper summaries.

Pros:
- Smallest patch.
- Low schema churn.

Cons:
- Does not fix trust boundaries.
- Same-model self-judgment remains.
- No persistent anti-repetition memory.
- Hard to audit after the run.

## Recommendation

Use Approach 2. Implement four service-native features in separate worktrees, with short-lived branches merged in dependency order:

1. `feat/paper-verification-gate`
2. `feat/idea-novelty-jury`
3. `feat/research-memory-ledger`
4. `feat/submission-audit-gates`

The first worktree creates verification status data that the second and third can consume. The fourth primarily touches production submission flow and should merge after claim and memory structures settle.

This document is the umbrella design for the four related quality-gate changes. Implementation planning should still be split into four separate plans, one per branch, because each branch has its own tests, merge point, and rollback boundary.

## Design Section 1: Paper Verification Gate

### Goal

Every candidate paper should carry an explicit verification status before it is used for summaries, gaps, idea novelty, citations, or submission context.

### Component Design

Add a paper verification service near the existing academic adapters, not as a standalone ARIS helper clone. The service accepts candidate paper records with any known identifiers:

- Semantic Scholar paper ID
- OpenAlex work ID
- arXiv ID
- DOI
- title
- year
- source

It returns a normalized record:

- `candidate_id`
- `canonical_title`
- `canonical_doi`
- `canonical_arxiv_id`
- `canonical_s2_id`
- `canonical_openalex_id`
- `verification_status`: `verified`, `unverified`, `verify_pending`, `error`
- `verification_method`: `arxiv`, `crossref`, `semantic_scholar`, `openalex`, `title_match`, `none`
- `verification_reason`
- `verified_at`

### Data Flow

`search_academic_sources()` continues to retrieve broad candidates from S2 and OpenAlex. After retrieval, the new verifier enriches IDs and statuses before the candidates are stored in `context_bundle` or selected for deep reading.

For Frontier:

`candidate_retrieval -> verify candidates -> scope_pruning -> deep_reading`

For Divergent prior art:

`prior_art_check -> search prior art -> verify prior-art candidates -> novelty assessment`

### Error Handling

External API failures produce `verify_pending`, not silent drops. Malformed candidates produce `error`. Unverified papers remain visible with a warning status so search quality can be inspected.

### Testing

Tests should cover:

- arXiv ID verification success.
- DOI verification success.
- title-only fallback.
- transient adapter failure mapped to `verify_pending`.
- malformed candidate mapped to `error`.
- Frontier candidate retrieval preserving verification fields.

## Design Section 2: Idea Novelty Jury

### Goal

Improve idea quality by separating idea generation from quality and novelty verdicts.

### Component Design

Divergent mode keeps its current seven-stage shape, but `idea_composition`, `prior_art_check`, `feasibility_review`, and `idea_portfolio` get stricter roles.

Generation stages may:

- Generate many candidate ideas.
- Attach source pain points and method-transfer provenance.
- Attach prior-work notes.
- Estimate objective feasibility facts such as data availability, compute budget, and required experiment type.

Generation stages must not:

- Reject ideas based only on same-model taste.
- Declare novelty confirmed without verified prior-art evidence.
- Hide eliminated ideas without recording a reason.

Add a jury step or jury subroutine around prior-art and portfolio ranking. The jury can be implemented as a production coding-agent task or an LLM gateway path with explicit metadata marking it as an independent review. It receives the full deduplicated candidate set plus verified prior-art records and returns:

- `idea_id`
- `novelty_verdict`: `novel`, `overlapping`, `unclear`
- `quality_verdict`: `pursue`, `hold`, `reject`
- `closest_prior_work`
- `strongest_objection`
- `required_validation`
- `jury_model`
- `jury_trace_id` or task ID

### Data Flow

`idea_composition -> mechanical dedup -> prior_art_search_with_verification -> novelty_jury -> feasibility_review -> idea_portfolio`

Mechanical dedup can run in the worker because it is not a quality verdict. It should use normalized titles, hypothesis stems, and borrowed method names.

### Error Handling

If the jury fails, ideas should remain in `hold` with `novelty_verdict = unclear`, and the run should surface a warning rather than falsely finalizing novelty.

### Testing

Tests should cover:

- duplicate idea collapse by deterministic key.
- jury failure produces `hold` and warnings.
- prior-art verification statuses propagate into idea cards.
- `idea_portfolio` ranks only after jury fields exist or marks missing jury state.

## Design Section 3: Research Memory Ledger

### Goal

Add persistent research memory equivalent to ARIS research-wiki, but implemented through Research OS database-backed entities and existing library/claim infrastructure.

### Component Design

Do not create Markdown wiki pages. Instead add durable ledgers:

- Paper verification memory: canonical identifiers and verification outcomes.
- Idea memory: proposed, held, rejected, archived, pursued ideas.
- Idea evidence edges: idea to pain point, paper, claim, experiment plan, and production job.
- Failed idea memory: rejected or invalidated ideas with explicit reasons and similarity keys.

This should reuse existing tables where practical. If schema additions are needed, prefer narrow tables rather than expanding JSON blobs everywhere.

### Data Flow

Frontier writes verified papers, gaps, and pain points. Divergent reads this memory before generating ideas and writes both surviving and rejected ideas after jury. Production claims and experiment results can later update idea outcomes.

### Error Handling

Memory writes are side effects. If they fail, the primary research run should still complete, but the event stream and run warnings should report that memory persistence failed.

### Testing

Tests should cover:

- writing proposed and rejected ideas.
- loading failed-idea banlist by topic or similarity key.
- linking idea to verified prior work.
- side-effect failure records warning without failing the whole run.

## Design Section 4: Submission Audit Gates

### Goal

Upgrade production submission gating from static checks to audit-class gates that can inspect paper text, raw result snapshots, citations, artifacts, and strongest rejection arguments.

### Component Design

Extend the existing production submission package flow. Current `gate_submission_package()` already writes reports for claim audit, checklist, compile, anonymity, citation, and artifact provenance. Keep this structure and add audit result fields or nested report sections for:

- paper claim audit: every quantitative or scope claim in `paper.md` traced to `claims_snapshot.json`, `artifact_snapshot.json`, raw metrics, or result files.
- citation audit: every citation marker or bibliography entry verified against canonical paper metadata.
- adversarial rejection memo: strongest rejection argument and adjudication status.

These audits can be queued as coding tasks using the existing provider layer. They must read files from `paper_dir` and snapshots directly, not executor summaries.

### Data Flow

`prepare_manuscript_drafting -> coding task writes paper.md -> gate_submission_package -> queue missing audit tasks -> audit task writes JSON report -> regate submission`

The static gate may keep submission in `gated` while audit reports are missing. Once reports exist and pass, status can become `ready`.

### Error Handling

Missing audit report is a gating failure, not a pass. Audit task runtime failures should be recorded as `ERROR` reports and keep status `gated`.

### Testing

Tests should cover:

- missing audit report keeps submission gated.
- passing audit reports can unblock submission when other checks pass.
- failed citation audit keeps submission gated.
- audit task creation is idempotent.
- generated gate report contains all audit sections.

## Worktree And Merge Strategy

Use `.worktrees/` at the repository root. It already exists and is ignored.

Create branches:

- `.worktrees/paper-verification-gate` on `feat/paper-verification-gate`
- `.worktrees/idea-novelty-jury` on `feat/idea-novelty-jury`
- `.worktrees/research-memory-ledger` on `feat/research-memory-ledger`
- `.worktrees/submission-audit-gates` on `feat/submission-audit-gates`

Implementation can happen in isolated worktrees, but merge order should remain strict:

1. Merge `feat/paper-verification-gate` into `main`.
2. Rebase or recreate `feat/idea-novelty-jury` on updated `main`, then merge.
3. Rebase or recreate `feat/research-memory-ledger` on updated `main`, then merge.
4. Rebase or recreate `feat/submission-audit-gates` on updated `main`, then merge.

This reduces conflicts around schemas, API types, and production orchestrator code.

## Non-Goals

- Do not copy ARIS Markdown skill files into Research OS.
- Do not replace LangGraph workflows with Markdown workflows.
- Do not make all four branches merge simultaneously.
- Do not use prompt-only changes as the primary quality fix.
- Do not block research runs on memory persistence side effects.

## Acceptance Criteria

- Paper candidates expose verification status before deep reading and prior-art novelty checks.
- Divergent idea cards include explicit jury fields and closest prior-art context.
- Failed or rejected ideas are persisted and can be loaded to reduce repeated ideation.
- Submission gates distinguish static checks from audit-class reports.
- Tests cover each new service boundary and each changed workflow decision.
- All four branches merge to `main` in order with passing targeted tests.
