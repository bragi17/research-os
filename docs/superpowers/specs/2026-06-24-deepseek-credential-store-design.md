# DeepSeek Credential Store Design

## Goal

Replace legacy LLM provider configuration with a market-standard model credential store: DeepSeek is the only supported LLM provider, credentials are editable from the Settings UI, stored outside source code, and applied at runtime without restarting services.

## Scope

In scope:

- LLM provider credentials and model selection.
- Settings API and Settings UI behavior for LLM configuration.
- Runtime refresh behavior for API and worker processes.
- Cleanup of GPT, Claude, OpenAI-named default model settings where they describe LLM provider choice.

Out of scope:

- DashScope/Tongyi embedding and rerank services.
- Academic API keys such as Semantic Scholar, OpenAlex, Crossref, and Unpaywall.
- Storage, parser, auth, and research mode behavior unrelated to LLM calls.

## Architecture Decision

Use a workspace-level credential store as the runtime source of truth.

The `.env` file becomes bootstrap configuration only. On startup, if no LLM credential record exists, the app can import:

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`, default `https://api.deepseek.com`
- `DEEPSEEK_MODEL`, default `deepseek-v4-pro`

After bootstrap, Settings UI changes write to the credential store, not to source code. The worker and API resolve the active LLM profile at call time or through a short-lived cache that is invalidated when settings change.

This mirrors common agent products: UI-managed encrypted credentials, masked display, test connection before save, and runtime provider clients built from the active credential profile.

## Data Model

Create a single active DeepSeek credential record.

Table: `llm_provider_credentials`

- `id uuid primary key`
- `workspace_id uuid not null default '00000000-0000-0000-0000-000000000000'`
- `provider text not null check (provider = 'deepseek')`
- `label text not null default 'DeepSeek'`
- `base_url text not null default 'https://api.deepseek.com'`
- `model text not null default 'deepseek-v4-pro'`
- `api_key_encrypted text`
- `api_key_preview text`
- `is_active boolean not null default true`
- `last_test_status text`
- `last_test_error text`
- `last_test_at timestamptz`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Indexes:

- Unique active DeepSeek profile per workspace.

No plaintext API key is returned from the API. UI responses include only `api_key_preview` and `is_key_set`.

## Secret Handling

Add application-level credential encryption.

- New environment variable: `CREDENTIAL_ENCRYPTION_KEY`.
- Use Fernet-compatible symmetric encryption for `api_key_encrypted`.
- Development fallback may derive a local key from `JWT_SECRET`, but production should require explicit `CREDENTIAL_ENCRYPTION_KEY`.
- Never write user-provided API keys into tracked files, docs, migrations, tests, logs, or client responses.

Deletion clears `api_key_encrypted`, clears `api_key_preview`, and marks the profile as not configured. It must not silently fall back to an older key.

## API Contract

Keep the existing settings route family but make LLM credentials explicit.

Recommended endpoints:

- `GET /api/v1/settings/models`
  - Returns current categories.
  - LLM category has one editable DeepSeek profile.
  - Non-LLM categories keep current behavior.

- `PUT /api/v1/settings/llm`
  - Body fields: `api_key`, `base_url`, `model`, `label`.
  - Empty or omitted `api_key` preserves the current key unless `clear_api_key` is true.
  - Validates provider is DeepSeek-only.
  - Saves encrypted credential and invalidates runtime cache.

- `DELETE /api/v1/settings/llm/api-key`
  - Clears only the stored API key.
  - Leaves base URL and model so the UI remains editable.

- `POST /api/v1/settings/llm/test`
  - Tests supplied fields or the active saved profile.
  - Sends a minimal DeepSeek chat completion.
  - Saves `last_test_status` when testing the active profile.

Existing `/api/v1/settings/models/test-llm` can remain temporarily as a compatibility alias, but the UI should move to `/api/v1/settings/llm/test`.

## Runtime Refresh

Implement a small `LLMSettingsRepository` and `LLMConfigCache`.

- API writes call `invalidate_llm_config()`.
- API publishes a Redis event such as `llm_config_changed`.
- Worker subscribes or periodically checks a version timestamp.
- Gateway cache has a short TTL fallback so it refreshes even if Redis is unavailable.
- `LLMGateway` builds clients from the current active profile.

Current internal `ModelTier` references can remain as compatibility labels for workflow quality/cost intent, but all tiers resolve to the same configured DeepSeek model. Removing tiers from every workflow can be a later refactor.

## Frontend Behavior

Settings UI should show a single DeepSeek LLM panel:

- Provider: DeepSeek, fixed.
- Base URL: editable, default `https://api.deepseek.com`.
- Model: editable, default `deepseek-v4-pro`.
- API key: password input, blank by default, placeholder shows whether a key is set.
- Actions: Save, Test Connection, Clear API Key.
- Status: last test status and error summary.

The UI should not present OpenAI, GPT, Claude, or multiple provider choices.

## Cleanup Rules

Remove or rename legacy LLM configuration:

- `OPENAI_API_KEY` -> `DEEPSEEK_API_KEY`
- `OPENAI_BASE_URL` -> `DEEPSEEK_BASE_URL`
- `OPENAI_MODEL_DEFAULT` and `OPENAI_MODEL_CHEAP` -> `DEEPSEEK_MODEL`
- GPT and Claude example text in docs or UI -> DeepSeek-only text

Do not remove:

- `openai` Python package, because DeepSeek uses an OpenAI-compatible API.
- `langchain-openai`, unless structured output is replaced in a separate refactor.
- DashScope embedding and rerank configuration.

## Testing

Add tests before implementation for:

- Credential encryption never returns plaintext API keys.
- Bootstrap imports DeepSeek env values only when the database has no active profile.
- Settings update invalidates the gateway cache.
- LLM gateway uses `https://api.deepseek.com` and `deepseek-v4-pro` defaults.
- Legacy OpenAI LLM keys are no longer exposed by the settings API.
- Existing embedding and rerank tests continue to pass unchanged.

## Migration Strategy

1. Add the credential table and repository.
2. Add DeepSeek defaults and env bootstrap.
3. Update settings routes while preserving non-LLM categories.
4. Update gateway configuration resolution.
5. Update Settings UI.
6. Update docs and tests.
7. Optionally provide a one-time migration from existing `OPENAI_*` env values to DeepSeek fields only if the user explicitly wants it.

## Acceptance Criteria

- DeepSeek is the only configurable LLM provider in the UI and API.
- The default LLM profile uses `https://api.deepseek.com` and `deepseek-v4-pro`.
- API keys are not hardcoded and are not committed.
- Settings changes take effect for new LLM calls without restarting API or worker processes.
- Existing DashScope embedding/rerank behavior remains unchanged.
- Test coverage proves credential masking, update, delete, connection test, and gateway reload behavior.
