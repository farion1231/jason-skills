---
name: jason-update-model
description: Audit CC Switch's pricing table against models.dev (every run), and/or research a newly released model's pricing + context and add it
argument-hint: [optional model name, e.g. "Claude Opus 5" — omit to just run the audit]
---

# Update Model

Two jobs, one entry point:

1. **Every run starts with an audit** (Step 0): pull the latest models.dev catalog and diff it
   against the seeded pricing table — recent coding models we don't have yet, and rows whose
   price no longer matches the vendor's.
2. If the skill argument names a **specific model**, that model is the priority: research it
   (Step 1) and add it (Steps 2–3) without further asking. Other audit findings are reported
   alongside, not silently fixed.

With **no argument**, the audit report IS the deliverable: present it with a recommended
worklist (which mismatches to fix, which missing models to add) and let the user pick before
writing anything.

---

## Step 0 — Audit against models.dev (always run first)

Run the bundled script (stdlib-only Python; downloads `https://models.dev/api.json`, ~3 MB):

```bash
python3 .claude/skills/jason-update-model/audit.py          # from the repo root
#   --days N       missing-model window, default 180 (0 = all)
#   --api-json F   reuse a cached api.json instead of downloading
```

It parses `schema.rs::seed_model_pricing` (both rustfmt tuple layouts) and prints three sections:

| Section | Meaning | What to do |
|---------|---------|------------|
| **A. Price mismatches** | seed row differs >2% / $0.005 from the vendor's own models.dev entry | Price-CHANGE candidates. models.dev is **not** authoritative — confirm each against the vendor's official pricing page (Step 1 sources) before writing seed + repair (Step 2). |
| **B. Missing recent models** | first-party coding models (anthropic / openai / google / xai / deepseek / zai / moonshotai / alibaba / minimax) released in the window, no seed row | ADD candidates via Steps 1–2. Only seed what CC Switch users actually route — skip niche SKUs and rolling `-latest` aliases unless asked. |
| **C. Seed rows absent from models.dev** | informational | **Not errors**: tier-suffixed rows (`gpt-5.2-codex-low`), dated ids, gateway-only ids, vendors models.dev doesn't track. Never delete a seed row because of C. |

Before any write, show the user the worklist (A rows you'd fix after vendor confirmation, B rows
you'd add) and get a go-ahead — except the argument-named model itself, which the invocation
already approves.

**Known-intentional divergences** live in `audit-ignore.json` next to the script
(`{"<seed id>": "reason"}`) — e.g. list price deliberately kept over a promo price. When the user
rules a reported mismatch intentional, record it there (reason + when to remove) so it stops
re-alerting every run.

Script maintenance: it mirrors app logic — `normalizeModelIdForPricing` / `isTextPricingModel`
(`src/lib/modelsDevPricing.ts`) and the `.`↔`-` claude mapping; keep in sync if those change.
Reference prices come only from first-party providers, home vendor first — never from
aggregators/resellers (opencode, iflowcn, openrouter…), whose retail prices are not list prices.

---

## Step 1 — Research the model's data (web)

Use web search / fetch to gather the following, **cross-checking at least two sources**:

| Datum | Notes |
|-------|-------|
| Canonical model id(s) | the id the provider's API uses, e.g. `claude-opus-5`, `glm-5.2`, `gpt-5.6` |
| Display name | the vendor's official model name |
| Input price $/M | per **million** input tokens, in **USD** |
| Output price $/M | per million output tokens |
| Cache-read $/M | prompt-cache hit/read price — `"0"` if the vendor doesn't publish one |
| Cache-write $/M | prompt-cache write/creation price — `"0"` if not published |
| Context window | max input tokens (needed only for preset lists — Step 3) |

**Sources, best first:**

1. **models.dev** — `https://models.dev/api.json`. This is the exact catalog the app's own price
   importer uses, so it's the most trustworthy structured source. Shape:
   ```
   { "<providerId>": { "name": ..., "models": {
       "<modelId>": { "name": ..., "release_date": "YYYY-MM-DD",
                      "cost": { "input": .., "output": .., "cache_read": .., "cache_write": .. },
                      "limit": { "context": .., "output": .. } } } } }
   ```
   ⚠️ **`cost.*` is already per-million USD — use the numbers as-is (do NOT multiply).**
   `limit.context` is the context window. Find your model under the right provider (the same model
   may appear under several providers; prefer the first-party one).
2. **Official vendor pricing/docs** (Anthropic / OpenAI / Google / Z.ai / Moonshot / DeepSeek / …) —
   authoritative for the **list price**. Use these to confirm or override models.dev.
3. **OpenRouter** — `https://openrouter.ai/models/<slug>` (page) or `https://openrouter.ai/api/v1/models`
   (JSON). ⚠️ OpenRouter's `pricing` is **per-token** strings → **×1,000,000** for $/M. Good
   cross-check, but OR prices are one provider's, not always the official list.

**Pricing conventions (must match the existing table):**
- Use the vendor's **official list price**, not a reseller/aggregator discount.
- Chinese vendors: official list price in **USD** (convert CNY at ~7.14 if only CNY is published).
- `"0"` for any cache column the vendor doesn't publish.
- If sources disagree beyond a rounding difference, **show both, say which you'd use, and ask**
  before writing — a wrong price permanently mis-bills every request logged for that model.

---

## Step 2 — Add the price to the built-in table

`src-tauri/src/database/schema.rs` → `fn seed_model_pricing` → the `pricing_data` array. Add one
6-tuple near its model family:

```rust
("<model-id>", "<Display Name>", "<input>", "<output>", "<cache_read>", "<cache_creation>"),
//                                                        ^^ cache_read BEFORE cache_creation (=cache-write)
```

- All six are **string** literals ($/M as plain decimal strings, e.g. `"5"`, `"25"`, `"0.50"`).
- **`model_id`** = the clean, lowercase, **base** id: strip the vendor namespace before the last
  `/`, drop a `:suffix`, map `@`→`-`. This mirrors the DB lookup (`clean_model_id_for_pricing` in
  `usage_stats.rs`; TS twin `normalizeModelIdForPricing`). One base id covers logged variants
  (`vendor/…`, `…@high`, dated suffixes) — only add a **suffixed** row when the price genuinely
  differs by tier/effort (e.g. the existing `gpt-5.2-codex-low`).
- For Claude ids use the **dashed** form (`claude-opus-5`); the lookup maps `.`↔`-` for `claude-`.
- **No `SCHEMA_VERSION` bump.** `ensure_model_pricing_seeded` (one call in `database/mod.rs::init()`)
  re-runs `seed` + `repair` on **every** app start, so a new row reaches all users next launch. Do
  not add a `migration.rs` step for pricing.

**If it's a price CHANGE to an already-seeded model** (not a brand-new model): update the value in
`seed_model_pricing` **and** add a 10-tuple to `fn repair_current_model_pricing`:

```rust
("<id>", "<Name>", "<newIn>", "<newOut>", "<newCacheRead>", "<newCacheWrite>",
                   "<oldIn>", "<oldOut>", "<oldCacheRead>", "<oldCacheWrite>"),
```
Seed sets the price for fresh installs; repair's `UPDATE ... WHERE <the four cost columns still
equal the OLD values>` corrects existing users' rows **without** clobbering a user's manual edit
(`display_name` is rewritten too, but only the four cost columns are the guard).

---

## Step 3 — (only if the model goes into a provider preset) add context + cost there

The pricing table has **no** context-window column — context lives in the per-provider preset model
lists. Do this **only** if you're also adding this model to a provider's
`src/config/*ProviderPresets.ts` `models` list:

- **OpenClaw**: `models[]` → `{ id, name, contextWindow, cost: { input, output } }`
- **Hermes**: `models[]` → `{ id, name, context_length }`
- **OpenCode**: variant metadata (contextLimit / outputLimit) in `OPENCODE_PRESET_MODEL_VARIANTS`
- **Codex native**: `modelCatalog([...])` → `contextWindow` (+ official `baseInstructions`)

To add a whole new **provider**, use `/jason-add-preset`. To make an existing provider **default** to this
model, see **Advanced** below.

---

## Step 4 — Report & verify

- Print a compact table: `model_id | input | output | cache_read | cache_write | context | source(s)`.
- Audit-only run: the three-section Step 0 report + your recommended worklist is the deliverable.
- List every file touched.
- Rust edited → `cd src-tauri && cargo fmt && cargo test`. Presets edited → `pnpm typecheck && pnpm format`.

---

## Advanced — bump preset DEFAULTS / flagship machinery (only when explicitly asked)

Adding a price (Steps 1–2) is self-contained and is the normal job. **Switching presets to default
to a new flagship**, or adding a new Claude/Codex/Gemini **tier**, is a bigger, hand-synced job — do
it only when the user explicitly wants presets to adopt the new model as their default. Touchpoints
(grep the symbol; line numbers drift):

| Concern | Where to edit |
|---------|---------------|
| Claude default per role | `claudeProviderPresets.ts`: `ANTHROPIC_MODEL` + `ANTHROPIC_DEFAULT_{HAIKU,SONNET,OPUS}_MODEL` — **4 id conventions** (prefixed-dotted `anthropic/claude-…`, bare-dotted `claude-sonnet-4.6`, bare-dashed `claude-…`, Bedrock `global.anthropic.…`; only haiku Bedrock carries `-v1:0`). Only bump presets actually serving Anthropic. |
| Codex default | `codexProviderPresets.ts`: `generateThirdPartyConfig(…, modelName = "gpt-5.5")` default **and** every explicit 3rd arg **and** inline-TOML `model=`/`review_model=`; also `codexTemplates.ts`. |
| Gemini default | `geminiProviderPresets.ts`: `env.GEMINI_MODEL` **and** the top-level `model:` (duplicated; Google Official OAuth preset has neither). |
| Cross-app default | `universalProviderPresets.ts`: `NEWAPI_DEFAULT_MODELS` — one edit covers NewAPI + custom-gateway across all 3 apps. |
| Claude Desktop routes | `claudeDesktopProviderPresets.ts` `CLAUDE_DESKTOP_ROLE_ROUTE_IDS` **and** Rust `claude_desktop_config.rs` `DEFAULT_PROXY_ROUTES` (+ `CURRENT_OPUS_ROUTE_ID`/`LEGACY_OPUS_ROUTE_ID` for opus) — hand-synced. |
| New Claude tier/role (rare, like Fable) | `is_claude_safe_model_id` whitelist + `claude_role_keyword` + `proxy/model_mapper.rs` + `commands/provider.rs` + frontend `ROLE_ORDER`/`routeRoleFromId`/`isClaudeSafeRoute` + `ClaudeFormFields.tsx` + 4 locales; gated on Claude Desktop's external app.asar validator. |
| New usage/subscription tier | `services/subscription.rs` (`TIER_*`/`KNOWN_TIERS`/`classify_gemini_model`) + `tray.rs` `TIER_LABEL_GROUPS` + `SubscriptionQuotaFooter.tsx` `TIER_I18N_KEYS` — **three independent lists, sync all three** + 4 locales. |
| i18n | **FOUR** locales `src/i18n/locales/{zh,en,ja,zh-TW}.json`, searched by key path. (CLAUDE.md / jason-add-preset.md say "three" — that's stale.) |

Do **not** blanket find/replace a model id — the same fields serve unrelated upstreams; only bump a
preset whose provider actually serves the released model, and when unsure, ask.

---

## Rules

1. **Research first; never invent a price.** Cross-check ≥2 sources; when they disagree beyond
   rounding, show both and ask before writing.
2. **Unit gotcha:** models.dev `cost.*` is already $/M; OpenRouter API is **per-token** (×1e6);
   official vendor docs win for the list price.
3. **Pricing tuple order:** `(id, name, input, output, cache_read, cache_creation)` — cache_read
   before cache_creation(write). All string literals. **No `SCHEMA_VERSION` bump.**
4. **New model → seed only. Price change → seed value + `repair` (new + old-value guard).**
5. **`model_id`** = clean lowercase base id; add a suffixed row only when price differs by tier.
6. **Context window → preset lists (Step 3), not the pricing table** (it has no context column).
7. **Keep Step 2 self-contained.** Only touch preset defaults / flagship machinery (Advanced) when
   the user explicitly asks presets to adopt the new model as their default.
8. **Report the numbers + sources** so the user can eyeball; if you add any i18n key, all **four** locales.
9. **Audit findings are candidates, not auto-writes.** A-row price fixes need official-vendor
   confirmation + user go-ahead; B-rows are added selectively; C is informational — the audit
   never deletes seed rows. User-ruled intentional divergences go into `audit-ignore.json`
   instead of re-alerting every run.
