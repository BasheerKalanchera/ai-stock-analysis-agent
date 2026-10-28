# Backlog — Architecture Review Findings

Tracking list generated from the Lead Backend Architect review on 2026-08-24.
Mark items `[x]` as they're closed. Add a short note under an item when it's resolved (what was done, commit/date).

---

## 🚨 Urgent

- [x] **[Critical] Live Tavily API key hardcoded and committed to git** — `check_Tavily_usage.py:5-6`
  Two real API keys are typed directly into the file (one active, one commented out), tracked in git history.
  **Fix:** Revoke both keys in the Tavily dashboard, generate a new one, load it via `os.getenv("TAVILY_API_KEY")` like the rest of the app does. Scrub git history (`git filter-repo`/BFG) if this repo is or will be shared/public.
  **Resolved 2026-08-24:** User is on Tavily's free tier, so key rotation was deemed low priority and skipped. Instead, `check_Tavily_usage.py` was untracked from git (`git rm --cached`) and added to `.gitignore` (commit `098ff09`, pushed to `origin/main`). File remains on disk locally but is no longer on GitHub going forward. Note: it still exists in the two older commits (`8106f80`, `3e5c813`) already on GitHub — history was not scrubbed, per user's call that this is an acceptable risk on the free tier.

---

## Security

- [ ] **[Medium] `skills_loader.py` save/delete functions don't sanitize filenames** — `skills_loader.py` (`save_skill`, `delete_skill`)
  `create_skill` sanitizes its filename against path traversal; `save_skill`/`delete_skill` don't. Currently safe only because the UI restricts input via a dropdown.
  **Fix:** Add the same sanitization/containment check directly inside `save_skill` and `delete_skill`, not just at the UI call site.

- [ ] **[Medium] AI-generated report text rendered with HTML safety switch off** — `app.py:1053`
  `st.markdown(thesis, unsafe_allow_html=True)` renders LLM output (built from scraped web content) with raw HTML allowed.
  **Fix:** Remove `unsafe_allow_html=True` unless a specific formatting need requires it; sanitize with an allowlist (e.g. `bleach`) if it's needed.

- [ ] **[Low] No authentication on the Streamlit app**
  If ever deployed publicly, anyone could trigger paid LLM/API calls or edit valuation skill files.
  **Fix:** Add an auth gate (Streamlit built-in auth or reverse-proxy) before any public deployment. Not urgent for local/private use.

---

## Architecture

- [ ] **[High] `app.py` mixes UI, secrets/DB setup, orchestration, and per-mode display logic in one 1094-line file**
  ~10 near-identical branching blocks (once for status placeholders, once for results display), one per workflow mode, keyed by fragile string literals.
  **Fix:** Extract a `WORKFLOW_REGISTRY` (mode → graph, node sequence, placeholder labels, render function) and replace the branching with a data-driven dispatch loop.

- [ ] **[High] `nodes.py` is a 746-line god file with ~20 near-duplicate node functions**
  One `screener_for_X_node` / `isolated_X_node` pair per agent/deep-dive mode, mostly copy-pasted.
  **Fix:** Replace with a factory: `make_screener_node(download_flags)` / `make_isolated_node(agent_fn)`.

- [ ] **[Medium] Redundant fixed sleep delays stacked on top of adaptive retry backoff**
  `delay_node` (2x in full workflow) + 10s `STEP_DELAY` between qualitative sub-steps + 10s inter-ticker cooldown in `app.py`'s batch loop, all unconditional — on top of `generate_with_retry`'s adaptive backoff.
  **Fix:** Remove or shorten the fixed sleeps in favor of the existing adaptive retry; make any remaining delay env-configurable.

- [ ] **[Medium] No browser/context pooling for Playwright scraping**
  Every `download_financial_data` call spins up a fresh browser process — costly in batch mode.
  **Fix:** Consider a long-lived browser instance reused across tickers during a batch run.

- [ ] **[Low] `log_file_content` state field is an unbounded append-only string**
  Stored in every Postgres checkpoint with no size cap.
  **Fix:** Add a size cap or truncate old sections on long/multi-transcript runs.

---

## Reliability / Error Handling

- [ ] **[High] Failed agent steps can silently flow into the final report as if valid** — `nodes.py` (`execute_with_fallback`)
  Rate-limit detection via substring match (`"429" in error_str`); on total failure, returns a plain error string stored as if it were real output.
  **Fix:** Use a typed/sentinel failure result that downstream synthesis/report code explicitly checks for and visibly flags.

- [ ] **[High] Cached LLM failures get permanently replayed** — `qualitative_analysis_agent.py` (`@lru_cache` on `_analyze_with_gemini`)
  A transient failure string (e.g. "Rate limit exceeded...") gets cached and replayed for identical future prompts.
  **Fix:** Never cache error-shaped results; only cache on confirmed success, or drop the decorator.

- [ ] **[Medium] Downloaded PDFs/PPTs/credit reports aren't content-validated**
  Only the Excel download path checks magic bytes before accepting a file; PDF/PPT/credit-rating downloads don't.
  **Fix:** Apply the same magic-byte check (`%PDF` for PDFs, `PK` for PPTX) uniformly across all download paths.

- [ ] **[Medium] PPT text-extraction failures are swallowed** — `strategy_agent.py:196-197`
  Logged but execution continues with empty text, producing a report that looks grounded but isn't.
  **Fix:** Fail the node explicitly (or flag the output) when extraction yields no usable text.

- [ ] **[Low] Scattered bare `except: pass` in retry-delay parsers and checkpoint-resume paths**
  Across risk/valuation/strategy/synthesis/qualitative agents and `app.py`.
  **Fix:** At minimum log at debug level so failures aren't invisible during troubleshooting.

---

## Code Quality / Duplication

- [ ] **[Medium] `generate_with_retry` copy-pasted across 4 agent files**
  `risk_agent.py`, `valuation_agent.py`, `strategy_agent.py`, `synthesis_agent.py`.
  **Fix:** Extract to a shared `llm_utils.py`.

- [ ] **[Low] Logger boilerplate duplicated verbatim in 7 files**
  Handler + formatter + `propagate=False` guard repeated per module.
  **Fix:** Extract a `get_logger(name, emoji)` helper.

- [ ] **[Medium] Inconsistent/stale default model names across agents**
  `"gemini-1.5-flash"` hardcoded in several places vs `"gemini-2.5-flash"`/`"flash-lite"` elsewhere.
  **Fix:** Centralize model defaults in one config instead of per-file literals.

- [ ] **[Medium] Chart/text interleaving depends on parsing the LLM's own markdown output** — `quantitative_agent.py`
  Marker-string splitting tightly couples prompt wording to parsing logic; phrasing drift silently breaks chart placement.
  **Fix:** Ask the LLM for structured JSON output instead of parsing markdown.

- [ ] **[Low] Duplicated prompt section block in `strategy_agent.py`** (`_map_reduce_strategy`)
  A section appears twice verbatim in the same prompt template — looks like a copy-paste artifact.
  **Fix:** Remove the duplicate, verify no behavior depends on it.

---

## Testing

- [ ] **[High] No automated test suite, no CI pipeline**
  `test_risk_app.py` / `test_strategy_app.py` are manual Streamlit harnesses requiring live credentials and network access — not `pytest`-runnable, no assertions, no mocking.
  **Fix:** Add a minimal `pytest` suite with mocked LLM/network responses for pure-logic pieces (JSON parsing, dtype round-trips in `checkpointer_serde.py`, skill matching in `skills_loader.py`). Add a `.github/workflows` CI job to run it.

- [ ] **[Medium] `qualitative_analysis_agent.py` (680 lines, most complex module) has zero automated coverage**
  Covers SEBI check, transcript analysis, QoQ JSON diffing, scuttlebutt search, OCR fallback.
  **Fix:** Prioritize test coverage here once the mocked-test harness above exists.

---

## Dependency / Repo Hygiene

- [ ] **[Medium] `requirements.txt` has no version pins**
  Risky given LangChain/LangGraph's frequent breaking changes.
  **Fix:** Pin at least major/minor versions (e.g. `langgraph~=0.x`).

- [ ] **[Low] Both `google-generativeai` (legacy SDK) and `google-genai` (new SDK) listed**
  **Fix:** Confirm which is actually in use, drop the other.

- [ ] **[Low] `asyncio` listed twice in `requirements.txt`**
  It's part of the Python standard library — shouldn't be a dependency at all.
  **Fix:** Remove both entries.

- [ ] **[Low] Unused-looking dependencies from an unrelated experiment**
  `pyaudio`, `websockets`, `termcolor` don't appear used by the current text-based Streamlit app.
  **Fix:** Confirm and prune if unused.

- [ ] **[Low] Stray runtime artifacts tracked in git**
  `final_report.json`, `session_practice.wav`, `march_to_may_changes.patch`, `Undervalued list of stocks.txt`.
  **Fix:** `git rm` these and add patterns to `.gitignore` so they don't return.

---

## 💡 Feature Ideas

Brainstormed on 2026-08-24 based on a full read of `app.py`/`nodes.py`/`graphs.py` and the agent pipeline. Not scoped or committed to — pick one to flesh out into a real plan when ready.

### Natural extensions (reuse existing agents/data, lower effort)

- [ ] **Forensic/governance red-flag agent**
  Promoter pledging, related-party transactions, auditor changes, qualified audit opinions — screener.in already surfaces most of this.
  **Fits:** alongside the existing Risk and SEBI Violations agents.

- [ ] **Shareholding pattern tracking**
  FII/DII/promoter holding trend and bulk/block deals, from data already being scraped off screener.in.
  **Fits:** as an input to the Scuttlebutt or Risk agent.

- [ ] **Multi-quarter trend memory**
  QoQ Concall Analysis currently compares only 2 consecutive quarters. Extend to N quarters to check whether management's guidance from a year ago actually played out — a classic scuttlebutt credibility check.
  **Fits:** generalization of the existing `strategy_shift_graph` / `compare_quarters_node`.

- [ ] **Sector scan / screener mode**
  Valuation Deep-Dive currently analyzes one ticker's peer comparison at a time. Flip it: run quant+valuation across a whole sector list to rank/screen for undervalued names — turns the tool from "analyze what I picked" into "help me find candidates."

### New capabilities (bigger lift, higher value)

- [ ] **Persistent report history**
  Results currently live only in `st.session_state` (wiped unless "append" is checked), and checkpoints are deleted after a successful run — no history is retained. Postgres is already wired in via the checkpointer; persist each finished report so a stock's thesis can be tracked over months, not just one QoQ snapshot.

- [ ] **Chat over a finished report**
  Once a report is generated, let the user ask follow-up questions grounded in that ticker's full state/log (RAG-style) instead of only reading static markdown — turns a one-shot report into an interactive research session.

- [ ] **API usage dashboard**
  A sidebar panel showing today's Gemini/Tavily quota usage (same idea as the standalone `check_Tavily_usage.py` script, built into the UI) — useful before kicking off a large batch run.
