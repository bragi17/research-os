# Literature Sources and ARIS Gate Design

Date: 2026-06-25

## Context

Research OS currently performs prior-art retrieval through Semantic Scholar and
OpenAlex inside `apps/worker/modes/base.py`. Failures from those APIs are logged
and the run can continue with an empty candidate set. That makes a failed search
look similar to a successful novelty check with no matches.

The local ARIS reference project uses a stronger pattern:

- multiple source classes, including local knowledge bases and web sources
- explicit source contribution accounting
- verification before trusting paper metadata
- transient API failures represented as pending or blocked, not as negative
  evidence

Research OS should adopt that pattern while keeping the existing workflow and UI.

## Goals

- Add configurable literature sources: local library, Zotero, Obsidian,
  WebSearch, Semantic Scholar, OpenAlex, and DeepXiv.
- Add a Settings UI section for literature sources with the same visual language
  as the rest of the app.
- Support multiple API keys per source where useful, starting with Semantic
  Scholar and WebSearch providers.
- Fix Semantic Scholar behavior for keys limited to one request per second by
  enforcing per-key `1 rps` and `burst=1`.
- Improve OpenAlex 429 handling through polite-pool configuration and retry
  classification.
- Add an ARIS-style retrieval gate so an empty aggregate caused by retrieval
  failure blocks or marks the stage pending instead of being treated as evidence
  of novelty.
- Reuse the existing paper verification table and statuses:
  `verified`, `unverified`, `verify_pending`, and `error`.

## Non-Goals

- Do not make Research OS depend on `/root/auto-claude-code-research-in-sleep`
  at runtime.
- Do not commit API keys or plaintext secrets.
- Do not replace the existing run modes or paper verification schema.
- Do not implement a browser-only WebSearch that only works through the current
  assistant session; autonomous worker runs need a real backend provider.

## Architecture

Add a literature search layer separate from the run-mode orchestration:

- `services/literature_settings.py`
  - stores source enablement, source options, and encrypted credentials
  - reads legacy `.env` settings as fallback
  - returns safe masked settings for the API
- `services/literature_search.py`
  - coordinates all enabled source adapters
  - normalizes source-specific results into `LiteratureCandidate`
  - records per-source contribution counts and errors
  - applies the aggregate retrieval gate
- `services/source_key_pool.py`
  - manages multiple keys for one provider
  - enforces independent per-key rate limits
  - rotates keys and cools down keys after 429 or credential errors
- source adapters under `libs/adapters/` or `services/literature_sources/`
  - local library
  - Zotero
  - Obsidian
  - WebSearch
  - Semantic Scholar
  - OpenAlex
  - DeepXiv

`apps/worker/modes/base.py::search_academic_sources` remains the compatibility
entry point. It delegates to the new coordinator and returns the existing tuple
shape to callers, with richer diagnostics in the error payloads.

## Settings UI and API

Add a `Literature Sources` category to `/api/v1/settings/models`. The category
contains structured source profiles rather than plain key-value rows.

Each source profile exposes:

- source id and label
- enabled flag
- configured state
- masked key previews
- editable non-secret options
- last test status, error, and timestamp

The Settings page renders this category with a dedicated component:

- enable or disable each source
- add or remove API keys
- set source-specific paths and provider options
- test an individual source
- save changes without showing plaintext secrets after reload

The component uses the existing card, typography, colors, status badges, and
lucide icons. It does not use emoji.

## Settings Storage

Add database-backed literature source settings:

- `literature_source_settings`
  - `workspace_id`
  - `source`
  - `enabled`
  - `options_json`
  - `last_test_status`
  - `last_test_error`
  - `last_test_at`
  - timestamps
- `literature_source_credentials`
  - `workspace_id`
  - `source`
  - `label`
  - `secret_encrypted`
  - `secret_preview`
  - `is_active`
  - `last_status`
  - `last_error`
  - `last_used_at`
  - `cooldown_until`
  - timestamps

Secrets use the same encryption primitive as existing LLM settings. Legacy env
values are preserved as fallback:

- `S2_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY`
- `OPENALEX_EMAIL`
- `OPENALEX_API_KEY`
- source path variables such as Zotero and Obsidian paths when present

If database settings exist for a source, they take precedence over `.env`.

## Multi-Key Behavior

Semantic Scholar and WebSearch providers support multiple keys.

For Semantic Scholar:

- each key gets its own limiter
- default limiter is `1 request/second`
- burst capacity is `1`
- requests rotate across active keys
- a 429 puts only that key into cooldown
- a 403 marks that key as credential or permission failed
- retries use response `Retry-After` when available, otherwise exponential
  backoff

This allows three Semantic Scholar keys to produce roughly three successful
requests per second without any single key violating the documented limit.

OpenAlex primarily uses polite-pool configuration:

- require or strongly prefer `OPENALEX_EMAIL`
- use lower default request rates than the current adapter
- classify persistent 429 as transient retrieval failure
- never treat an OpenAlex 429 as a successful empty search

## Source Behavior

Local library:

- query existing Research OS library tables and pools
- prefer DOI, arXiv id, S2 id, OpenAlex id, title, year, venue, and abstract
- counts as a local contribution for the aggregate gate

Zotero:

- read from configured local export or library path
- support JSON or BibTeX-compatible metadata where practical
- normalize DOI, arXiv id, title, authors, year, venue, abstract, and URL
- if no path is configured, mark the source unavailable rather than failed

Obsidian:

- read configured vault paths
- scan Markdown notes for DOI, arXiv identifiers, URLs, titles, and YAML
  frontmatter
- map matched notes into local literature candidates
- if no path is configured, mark the source unavailable rather than failed

WebSearch:

- use a backend provider configured in Settings
- support multiple keys for providers that need keys
- mark the source unavailable when no provider or key is configured
- normalize search results into candidate URLs and paper metadata when possible

Semantic Scholar:

- use key pool credentials first, then legacy env fallback
- preserve existing fields and filters
- reduce burst capacity to match the documented one-request-per-second key limit
- classify 403 and 429 separately

OpenAlex:

- use configured email and optional API key
- retry 429 with backoff
- preserve OpenAlex id, DOI, title, year, authors, venue, abstract, and OA URL

DeepXiv:

- treat as optional and unavailable unless the local tool or configured service
  is present
- use staged retrieval semantics where available: search, brief, head, section
- normalize enough metadata to pass through verification

## ARIS Retrieval Gate

Every search returns a `LiteratureSearchReport`:

- requested sources
- enabled sources
- contributing sources
- contribution counts
- source errors
- unavailable source reasons
- candidate count
- gate status

Gate statuses:

- `pass`: at least one source contributed candidates
- `warn`: at least one source contributed, but some sources failed
- `pending`: all enabled external failures are transient and local sources are
  unavailable or empty
- `blocked`: no source contributed and at least one required retrieval path
  failed or no usable source was configured

Worker behavior:

- `pass` and `warn` continue to verification and downstream scoring
- `pending` marks prior-art as `retrieval_pending`
- `blocked` marks prior-art as `retrieval_failed`
- empty aggregate results are never treated as evidence that an idea is novel

The gate report is persisted in run step metadata or event payloads so the UI can
show why a retrieval stage did or did not proceed.

## Paper Verification

Use the existing `paper_verification` table and service as the persistence layer.
Extend verification only where needed to match ARIS semantics:

- arXiv identifiers are verified directly when present
- DOI candidates are verified through CrossRef when configured
- title-only candidates can be fuzzy matched through Semantic Scholar
- transient lookup errors produce `verify_pending`
- candidates marked `unverified` remain visible and are not silently removed

Downstream novelty and citation logic must distinguish:

- verified prior art
- unverified possible prior art
- retrieval failure
- verification pending

## Error Handling

Errors are classified before they reach run logic:

- `credential_error`: invalid key, permission denied, persistent 403
- `rate_limited`: 429 after retries or active cooldown
- `transient_error`: timeout, 5xx, temporary network failure
- `configuration_error`: enabled source missing required path, email, or key
- `unavailable`: optional source not configured or local tool absent

Only `unavailable` optional sources are ignored for blocking decisions. Enabled
sources that fail contribute to `warn`, `pending`, or `blocked`.

## Compatibility and Migration

Add a migration for the two literature settings tables. The migration is
additive and does not alter existing run, library, or verification tables.

At read time, the settings repository bootstraps default source settings:

- local library enabled
- Semantic Scholar enabled when a key exists in DB or env
- OpenAlex enabled when an email or API key exists in DB or env
- Zotero, Obsidian, WebSearch, and DeepXiv disabled until configured

Existing `.env` keys continue to work for backend runs.

## Testing Plan

Backend unit tests:

- settings repository masks secrets and never returns plaintext keys
- multiple Semantic Scholar keys rotate and each limiter enforces `1 rps`
- Semantic Scholar 429 cools down only the affected key
- Semantic Scholar 403 is classified as credential failure
- OpenAlex 429 is classified as transient rate limiting
- aggregate gate blocks when all enabled sources produce no candidates
- aggregate gate warns when one source contributes and another fails
- verification retains unverified candidates

API tests:

- `/api/v1/settings/models` returns the new literature category
- source settings can be saved and reloaded with masked credentials
- source test endpoints redact secrets from errors

Worker integration tests:

- divergent prior-art check marks `retrieval_failed` when the gate blocks
- divergent prior-art check continues when local or external sources contribute
- empty candidate sets from failed retrieval are not scored as successful novelty

Frontend tests:

- Settings renders literature source controls without emoji
- multiple keys can be added and removed in local state
- masked keys are shown after reload
- disabled sources show inactive status clearly

Manual verification:

- run Settings page locally
- configure at least one Semantic Scholar key
- run a CPU-only research flow and confirm source contributions are present
- confirm 429/403 messages are classified and visible without exposing secrets

## Rollout

Implement in an isolated git worktree under `/root/research-os/.worktrees`.
Use failing tests first for the settings API, key pool, source gate, and worker
integration. After verification, merge back to the main working tree and push the
remote branch requested by the user.
