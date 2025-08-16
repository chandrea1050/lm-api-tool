# Technical Product Specification — SMB → PE Buyer Shortlist

## 1) Overview
- Problem: Quickly identify likely private equity buyers for SMBs by analyzing the company’s website and matching to a curated PE dataset.
- Solution: A Python app with CLI and Streamlit UI that:
  - Extracts a structured company profile from a URL using the OpenAI Responses API (or an offline heuristic).
  - Scores and ranks local PE funds deterministically with transparent, factor-by-factor rationale.
  - Presents a clean UI with insights, breakdowns, and a single consolidated summary.

### Technical approach
- Single-pass agent orchestration: `run_agent(url, dataset_path, model, top_k, offline, extra_context)` executes a compact pipeline — fetch → extract → score.
- Extraction (online): Use the OpenAI Responses API to transform cleaned page text into a structured `company_profile` with explicit fields (industries, locations, revenue_range_usd, employee_count_range, offerings, summary, confidence). Temperature kept low to reduce variance. The prompt is instruction-heavy to nudge schema adherence and brevity.
- Extraction (offline fallback): If no API key or when toggled, use a heuristic extractor to infer sectors, locations, and rough size ranges from the text (deterministic and fast for demos).
- Deterministic ranking: All matching and scoring happen locally over `data/pe_funds.json`. We compute per-factor subscores and a weighted total (industry 0.40, region 0.20, revenue 0.20, employees 0.10, deal type 0.10). This ensures reproducible ranks across runs.
- In-session memory: The Streamlit app accumulates user notes in session state and passes them as `extra_context` into extraction to disambiguate (e.g., desired deal type, revenue hints). Notes are deduplicated and can be cleared.
- Explanations: The UI derives human-friendly explanations from subscores and includes nuanced deal-type reasoning (MATCH, NEAR MATCH, MISMATCH) with synonym/adjacency hints.

### LLM API usage
- API: OpenAI Python SDK’s Responses API for structured text generation. The agent composes a strict instruction prompt to produce a compact JSON-like profile. Temperature is low and prompts are concise to manage token usage and response stability.
- Inputs: Cleaned page content (and optionally the user’s extra context) is summarized into the profile. No ranking logic is delegated to the LLM; it only extracts.
- Outputs: A structured profile object the downstream scorer consumes. Any uncertainty is reflected in the `confidence` field.

### Challenges and mitigations
- Variability vs determinism: LLM outputs can vary; we confine the LLM to extraction and keep ranking deterministic with fixed weights and numeric features; low temperature further stabilizes output.
- Website heterogeneity: Some SMB sites are sparse or JS-heavy. Mitigation: a static fetch + heuristic fallback; future: Playwright-based rendering, multi-page crawl.
- Taxonomy mismatch: Company vs fund terms differ (industry labels, deal types). Mitigation: synonym mapping for deal types (e.g., buyout ≈ LBO/control/majority) and natural-language explanations; future: standardized taxonomies (NAICS/SIC) and broader aliasing.
- User confusion around deal-type mismatches: A top fund can still rank high due to other weights. Mitigation: explicit MATCH/NEAR/MISMATCH messaging, contribution/weight display, and a single consolidated Summary section.
- UI duplication and context noise: Early versions doubled summaries and repeatedly appended notes. Mitigation: one Summary at page end; dedupe chat notes; Clear chat button.
- Dataset breadth: Small demo dataset can underrepresent real mandates. Mitigation: easy-to-edit JSON, expanded sample funds, richer offerings; future: normalized schema and importer.

## 2) Goals and Success Metrics
- Goals:
  - Accurate, readable company profiles from typical SMB sites.
  - Deterministic, explainable shortlist with quantitative factor contributions.
  - Lightweight UI that’s demo-ready and simple to run locally.
- Metrics:
  - Time to result: < 10s for average site in online mode; < 3s in offline mode.
  - Determinism: identical shortlist and scores given the same inputs.
  - Usability: no duplicate summaries; clear deal-type explanations.
  - Stability: no unhandled exceptions on common inputs.

## 3) Scope
- In-scope:
  - URL-based extraction into a structured profile.
  - Local scoring across industry, region, revenue, employees, and deal type.
  - Streamlit UI with Purpose, Company profile, Key insights, Shortlist, Detailed breakdown, and one Summary section.
  - In-session memory (chat notes) to guide extraction/scoring.
  - Offline mode with heuristic extraction.
- Out-of-scope (current release):
  - Multi-page crawling, JS-rendering.
  - External data enrichment (Clearbit/Crunchbase).
  - Large or production-grade funds database.
  - Authentication/hosting/permissions model.

## 4) Users and Personas
- M&A analysts and PE associates
- SMB executives/advisors
- Demo audiences evaluating LLM-driven workflows

## 5) Functional Requirements
- Input:
  - Required: company website URL.
  - Optional: free-form notes (chat) serving as in-session memory.
  - Options: top-K funds (3–15), model name, offline mode toggle.
- Extraction:
  - Online: OpenAI Responses API summarizes fetched HTML into company_profile with confidence.
  - Offline: heuristic inference for industries, locations, rough ranges.
- Scoring and ranking:
  - Factors and weights:
    - Industry 0.40
    - Region 0.20
    - Revenue 0.20
    - Employees 0.10
    - Deal type 0.10
  
  ### How the factors and weights were determined
  - Design goals:
    - Determinism and auditability: simple math, reproducible outputs, transparent contributions per factor.
    - Face-validity for LMM/SMB-focused PE: mirror how associates typically screen deals (industry first, then size/geography, then deal type).
    - Robust to sparse inputs: missing fields should not dominate the outcome.
  - Why these factors:
    - Industry: Most funds publish sector theses and stay disciplined; industry misfit is often a hard no.
    - Region: Many funds have geographic focus or proximity preferences; national funds still impose soft constraints.
    - Revenue and Employees: Size determines check size and operational complexity; revenue is primary, employees is a secondary proxy.
    - Deal type: Important but sometimes flexible (control vs minority, platform vs add-on), so included with lower weight and explained in prose.
  - Relative weights rationale:
    - Industry 0.40 — primary screening gate; strongest predictor of fit; deserves plurality of the score.
    - Region 0.20 — meaningful constraint but less absolute than industry, especially for national funds.
    - Revenue 0.20 — key size filter tied to check size and mandate bands.
    - Employees 0.10 — useful size/complexity signal but noisier and less standardized across sectors.
    - Deal type 0.10 — signals mandate alignment; kept lower to avoid over-penalizing funds that flex deal types.
  - Calibration method (initial):
    - Seeded by domain heuristics from lower-middle-market PE screens.
    - Smoke-tested on a handful of real/synthetic companies against the demo dataset; tweaked to yield intuitive rankings where strong industry fit reliably outranks perfect deal-type alignment with poor industry fit.
  - Constraints and trade-offs:
    - Small demo dataset; avoid overfitting weights to a few examples.
    - Maintain stability across minor extraction variance; low temperature and deterministic local scoring help.
    - Keep explanations readable; contributions shown in a stacked chart to visualize relative impact.
  - Handling missing/ambiguous data:
    - Missing fields contribute 0 for that factor but do not add extra penalties.
    - Deal-type NEAR MATCHes are called out in text but currently do not add partial points (to keep demo logic simple and predictable).
  - Configurability and evolution:
    - Weights are normalized to sum to 1.0 and currently fixed in code; planned move to config.yaml and optional UI sliders.
    - Future work includes partial credit (e.g., 0.25–0.5) for NEAR MATCH deal types and learned weights from labeled data.
  - Output includes subscores, contribution per factor, and rationale.
- Deal-type reasoning:
  - MATCH when fund explicitly lists requested type.
  - NEAR MATCH when synonyms/adjacent types overlap (no score contribution, called out in text).
  - MISMATCH otherwise.
  - Synonym examples: buyout ≈ LBO/control/majority; growth ≈ growth equity/minority; roll-up ≈ buy-and-build/add-on/platform; carve-out ≈ divestiture; recap ≈ recapitalization.
- In-session memory:
  - Chat notes persist in the session, de-duplicated, passed as extra_context; Clear chat resets.
- UI behavior:
  - One consolidated Summary section at the end; no per-fund summary in Detailed breakdown.
  - Detailed breakdown shows a natural-language table per factor (not JSON).
  - Stacked bar chart showing relative factor contributions.
- CLI behavior:
  - Flags: --k, --model, --offline, --json-output, --context.

## 6) Non-Functional Requirements
- Determinism: local scoring is deterministic; LLM temperature kept low.
- Performance: target < 10s online, < 3s offline on typical content.
- Reliability: graceful error handling for fetch/LLM failures with visible error message in UI.
- Security & privacy:
  - API key from env; never written to logs or UI.
  - Only page content and user-provided context are sent to the LLM in online mode.
- Accessibility: simple structure; relies on Streamlit defaults.
- Maintainability: clear module boundaries; small local dataset; documented README.

## 7) System Architecture

Components
- UI: `streamlit_app.py`
- Agent: `llm_pe_matcher.agent.run_agent`
- Tools: `llm_pe_matcher.tools.fetch_url`, `llm_pe_matcher.tools.query_pe_db`
- Scoring: deterministic subscores and weights; deal-type nuance helper in UI for explanations
- Data: `data/pe_funds.json` (demo funds)

Data Flow
```
User URL + optional notes (session memory)
   |
   v
Streamlit UI (controls: model, offline, K)
   | calls run_agent(url, dataset_path, model, top_k, offline, extra_context)
   v
Agent
   |-- fetch_url(url) -> HTML/text
   |-- Online: LLM (Responses API) -> company_profile
   |-- Offline: heuristic -> company_profile
   |-- query_pe_db(criteria from profile+context) -> shortlist (scores + subscores)
   v
Result JSON (profile + shortlist)
   |
   v
UI renders: metrics, insights, ranked table, chart, per-fund factor details, final consolidated Summary
```

## 8) Data Models

Company profile
- company_name: str
- url: str
- industries: [str]
- locations: [str]
- employee_count_range: {min?: int, max?: int}
- revenue_range_usd: {min?: number, max?: number}
- offerings: [str]
- summary: str
- confidence: float (0–1)

PE fund (dataset)
- name: str
- industries: [str]
- regions: [str]
- revenue_focus_usd: {min?: number, max?: number}
- employee_focus: {min?: int, max?: int}
- deal_types: [str]
- notes/check size/other fields as available

Shortlist item
- fund: str
- score: float
- rationale.subscores: per-factor blocks with applied/raw/coverage/contribution/weight and supporting fields

## 9) Scoring Algorithm
- Total score = sum(contribution_i) across factors.
- Industry: overlap ratio × 0.40
- Region: any overlap → 1 else 0; × 0.20
- Revenue: coverage_ratio × 0.20
- Employees: coverage_ratio × 0.10
- Deal type: exact match 1 else 0; × 0.10; NEAR MATCH flagged but 0 contribution

## 10) UX Specification (Streamlit)
- Sidebar: model input, offline toggle, Top-K slider
- Inputs: URL + optional notes; Analyze and Clear chat
- Sections: Purpose, User Interface, Company profile, Key insights, Shortlist, Detailed breakdown, Summary (only here)
- Charts: stacked bar for factor contributions
- Behavior: append notes only on Analyze; de-dup across reruns; Clear chat resets

### Why Streamlit
- Speed of iteration: enables a production-like demo UI with minimal boilerplate, ideal for fast prototyping and user feedback.
- Python-native: integrates directly with our Python stack (agent, tools, scoring) without a separate frontend codebase.
- Reactive model: simple rerun semantics keep state predictable; easy to wire inputs to outputs.
- Built-in widgets and layout: metrics, expanders, dataframes, and download buttons cover our initial UX needs.

### How we used Streamlit
- Page scaffold: `st.set_page_config` for title/layout; top-level sections using `st.title`, `st.subheader`, and markdown.
- Controls: sidebar inputs (`st.text_input`, `st.toggle`, `st.slider`) bound to agent parameters.
- In-session memory: `st.session_state.chat` stores notes; we de-duplicate via `last_submitted_context` and reset with "Clear chat".
- UX flow: guarded append of user notes only on Analyze; a spinner during agent execution; `st.error` for exceptions.
- Data presentation: `st.metric` for headline stats, `st.dataframe` for tables, Altair for the stacked contribution chart, and expanders for per-fund details.
- Downloads and transparency: `st.download_button` for the full JSON result; optional raw JSON toggles for debugging.

## 11) Configuration
- Env: OPENAI_API_KEY, OPENAI_MODEL
- CLI: --k, --model, --offline, --json-output, --context

## 12) Error Handling
- Fetch/LLM errors surfaced via `st.error` and handled gracefully
- Missing data renders as “—” with robust formatting helpers

## 13) Testing Plan
- Unit: factor calculators, coverage math, deal-type nuance cases
- Integration: offline E2E on static pages; CLI JSON schema validation
- UI smoke: launch, sections render, exactly one Summary
- Determinism: repeated runs yield identical lists/scores

## 14) Deployment/Runbook
- venv setup; `pip install -r requirements.txt`
- CLI and Streamlit run commands
- API keys via env/.env; never log secrets

## 15) Risks and Mitigations
- Sparse content → low confidence; allow user notes, show confidence, offline fallback
- Taxonomy mismatch; add synonyms and future normalization
- Small dataset; document schema, easy extension
- Latency variance; compact prompts, offline toggle

## 16) Roadmap
- Desired deal-type control; optional weight sliders
- Synonyms/taxonomy expansion (NAICS/SIC mapping)
- Multi-page crawl; polite rate limits
- Caching for fetch + model outputs
- Larger dataset; role-based filters
- Tests and CI

## 17) Acceptance Criteria
- Given URL + notes, UI renders profile, ranked shortlist, contribution chart, per-fund details, and exactly one final Summary
- Deal-type explanations read as MATCH / NEAR MATCH / MISMATCH with weight/contribution context
- Offline mode works without API access
- CLI outputs valid JSON and respects flags; deterministic results

## 18) Deep Technical Refinements (Future Work)
This section outlines specific, implementation-level improvements to elevate quality, accuracy, and performance.

### 18.1 Extraction fidelity and coverage
- Multi-page crawl: follow same-host links to About, Products, Solutions, Customers, and Careers with a 2–3 page cap, robots.txt check, and per-host delay (e.g., 500–1000ms). Maintain a visited set; fetch concurrently with a small pool.
- JS-rendered pages: optional Playwright headless rendering gate for pages with low text density; fallback to static fetch.
- Content scoring: prioritize main content nodes using density heuristics (tags, text length, position, boilerplate removal) and deduplicate near-identical blocks.

### 18.2 Normalization and taxonomy
- Industry mapping: curate a controlled vocabulary; add alias dictionary and fuzzy matching (e.g., RapidFuzz) to standardize company vs fund sectors.
- Region mapping: normalize to country/region sets; handle city/state parsing; geocode lite via static lists where possible.
- Deal-type synonyms: expand the adjacency graph; store as YAML and load at runtime for maintainability.

### 18.3 Scoring model evolution
- Partial credit for NEAR MATCH: award 0.25–0.5 of deal-type weight when adjacency is strong; parameterize via config.
- Learned weights: collect labeled pairs (company, suitable funds) and train a simple logistic regression or pairwise learning-to-rank model; fall back to deterministic weights when no model available.
- Calibration: apply isotonic or Platt scaling to map raw scores to confidence-like values for better interpretability.

### 18.4 UI/UX controls and clarity
- Sidebar controls for desired deal type (e.g., Buyout/Majority/Minority/Growth/Roll-up/Carve-out/Recap) and optional weight sliders.
- Tooltips and inline explanations next to factor columns in the shortlist table.
- Expand/collapse all controls and persistent URL query params to share a pre-filled session.

### 18.5 Caching and performance
- Page cache: file- or Redis-backed cache of fetch and cleaned text keyed by URL hash; TTL configurable.
- LLM cache: cache Responses API outputs by (model, prompt hash) for re-run efficiency.
- Vector cache (optional): embed offerings and industries once to enable faster overlap/semantic checks.

### 18.6 Evaluation and quality
- Golden set: store 20–50 known sites with expected industries/regions/sizes and expected buyers.
- Regression tests: run nightly to compare scores/ranks and fail on drift > threshold.
- A/B prompts: evaluate alternative extraction prompts with automatic metrics (field presence, length limits, precision/recall vs golden labels).

### 18.7 Data pipeline and schema
- Dataset schema: split industries, regions, deal types, and financial bands into normalized tables; validate with a JSON Schema.
- Import tools: CSV/Google Sheet importer with field validation and basic cleansing.
- Provenance: track last-updated and source notes per fund.

### 18.8 Observability and diagnostics
- Structured logs: add log levels and tracing IDs around fetch, extraction, scoring.
- Timing metrics: capture durations per step; surface total latency in UI footer.
- Error catalog: map common failure modes to user-facing guidance.

### 18.9 Packaging and distribution
- CLI entrypoint via setuptools; optional Dockerfile for reproducible runs.
- Config files: `config.yaml` for weights, synonyms, and crawl limits; override via env.
- Makefile or tasks.json targets for lint, test, run-ui.

### 18.10 Security and privacy
- Secrets: prefer environment variables and `.env`; never persist API keys.
- PII: redact potential PII in logs; consider allow-list of domains for demos.
- Network: add a global timeout and user-agent; respect robots.txt.

### 18.11 Future integrations
- Data enrichment: optional connectors (when permitted) to company data providers to improve confidence and fill gaps.
- Export formats: CSV, Excel, or CRM-compatible export of shortlists with rationale.

---
This document tracks the current product and a pragmatic path to production readiness while preserving determinism and explainability.
