# SMB → PE Fund Matcher (Prototype)

An AI-powered tool that:
- Takes a company's website URL as input
- Extracts a structured company profile (industries, locations, revenue, employees, offerings, summary)
- Produces a ranked shortlist of private equity funds with transparent, factor-by-factor rationale

Supports both CLI and a Streamlit browser UI. Uses the OpenAI Responses API for extraction and a deterministic, local scoring model for ranking.

## Highlights

- Streamlit UI with clear sections: Purpose, Company profile, Key insights, Shortlist, Detailed breakdown, and a single consolidated Summary at the end
- Deterministic scoring with quantitative breakdowns and a stacked contribution chart
- Nuanced deal-type reasoning: MATCH / NEAR MATCH / MISMATCH with synonyms and adjacent cases
- Local, editable dataset at `data/pe_funds.json` (expanded with more demo funds)
- Offline mode (no API key required) using a heuristic extractor
 - In-session memory: chat context persists during the session to guide extraction and scoring; de-duplicated and clearable

## Prereqs

- Python 3.9+
- An OpenAI API key set in your environment

Optional: copy `.env.example` to `.env` in the project root and fill in values.

## Install

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Quick start (CLI)

```cmd
# Basic run
python -m llm_pe_matcher.cli https://example.com

# Choose top-K (default 5)
python -m llm_pe_matcher.cli https://example.com --k 5

# Save raw JSON output to a file
python -m llm_pe_matcher.cli https://example.com --json-output output.json

# Use a specific OpenAI model (defaults from OPENAI_MODEL; UI default is gpt-5-2025-08-07)
python -m llm_pe_matcher.cli https://example.com --model gpt-5-2025-08-07

# Offline smoke test (no API key required)
python -m llm_pe_matcher.cli https://example.com --offline

# Provide additional context to guide extraction and scoring
python -m llm_pe_matcher.cli https://example.com --context "We are D.E. Shaw analyzing exit options; rev ~$30M; HQ NYC; buyout preferred"
```

### Streamlit UI

Launch the browser UI:

```cmd
.venv\Scripts\python -m streamlit run streamlit_app.py
```

In the app, enter a URL, optional context, and click Analyze. Toggle Offline mode if you don’t have an API key.

Environment variables:
- `OPENAI_API_KEY` (required)
- `OPENAI_MODEL` (optional; CLI `--model` overrides; UI defaults to `gpt-5-2025-08-07` if unset)
- Use `--offline` or the UI toggle to run without an API key

## How it works

Two entry points share the same core logic:

- CLI: `python -m llm_pe_matcher.cli <url> [--k K] [--model NAME] [--offline] [--context ...]`
- UI: `streamlit_app.py` orchestrates input, calls the agent, and renders results

Core flow (both paths):
1) Extract company profile
  - Online mode: Uses OpenAI Responses API to summarize the fetched HTML into a structured profile.
  - Offline mode: Heuristic extractor infers industries, locations, and rough size from page text.
2) Score funds locally and deterministically
  - `query_pe_db` runs over `data/pe_funds.json` and computes factor subscores and a weighted total.
3) Return ranked shortlist with rationale
  - Includes per-factor subscores, contributions, and natural-language details.

Scoring model (weights):
- Industry: 0.40
- Region: 0.20
- Revenue: 0.20
- Employees: 0.10
- Deal type: 0.10

Deal-type nuance:
- Exact MATCH when the requested deal type is listed by the fund.
- NEAR MATCH when not exact but adjacent via synonyms (e.g., buyout ≈ LBO/control/majority; growth ≈ growth equity/minority; roll-up ≈ buy-and-build/add-on/platform; etc.). NEAR MATCH contributes 0 for determinism but is called out in the explanation.
- MISMATCH when neither exact nor adjacent.

## Notes on models and the agentic API

- Uses the OpenAI Responses API as the core agentic primitive (a modern alternative to chat-only calls).
- Temperature kept low for determinism.
- You can override the model with CLI `--model` or `OPENAI_MODEL`; the UI’s default is `gpt-5-2025-08-07`.

## Limitations & challenges

- Website parsing is basic; tricky pages (heavy JS, gated content) may yield sparse text.
- Industry/size inference is heuristic and depends on the content available.
- The PE dataset is a small sample and not comprehensive; for production you’d:
  - Back-fill with a real database/CRM of buyers and mandates
  - Normalize industries (e.g., NAICS/SIC mapping)
  - Add richer financial ranges and deal preferences
 - NEAR MATCH currently does not add score (by design for predictability); you may choose to award fractional credit.

## If I had more time

- Add multi-page crawling (About, Products, Careers) with rate limits and robots.txt compliance
- Enrich with company data APIs (e.g., Clearbit, Crunchbase) where allowed
- Expand dataset and implement a proper scoring model with learned weights
- Add evaluation harness + unit tests for the extractor and ranker
- Add caching (file or Redis) for fetched pages and model outputs
- Expand synonyms/taxonomy for deal types and industries
- Add a sidebar control to set desired deal type and weights

## Repository layout

- `llm_pe_matcher/` — Python package (agent, CLI, tools)
  - `agent.py` — orchestrates extraction (Responses API) and scoring
  - `tools.py` — `fetch_url`, `query_pe_db` (deterministic scoring and subscores)
  - `matcher.py` — criteria construction, weight application
- `data/pe_funds.json` — Small demo dataset of PE funds
- `streamlit_app.py` — Browser UI for analysis and visualization
- `requirements.txt` — Python dependencies

## Example output (truncated)

```json
{
  "company_profile": {
    "company_name": "Acme Widgets",
    "url": "https://acmewidgets.com",
    "industries": ["Industrial Manufacturing", "B2B"],
    "locations": ["Dallas, TX, USA"],
    "employee_count_range": {"min": 80, "max": 120},
    "revenue_range_usd": {"min": 20000000, "max": 40000000},
    "offerings": ["Custom metal fabrication", "OEM components"],
    "summary": "Midwest-based manufacturer supplying OEM components to industrial clients.",
    "confidence": 0.71
  },
  "shortlist": [
    {
      "fund": "BlueLake Industrials",
      "score": 0.86,
      "rationale": {
        "subscores": {
          "industry": { "raw": 1.0, "contribution": 0.40, "weight": 0.40 },
          "region": { "raw": 1.0, "contribution": 0.20, "weight": 0.20 },
          "revenue": { "coverage_ratio": 0.8, "contribution": 0.16, "weight": 0.20 },
          "employees": { "coverage_ratio": 0.7, "contribution": 0.07, "weight": 0.10 },
          "deal": { "raw": 1.0, "contribution": 0.10, "weight": 0.10 }
        }
      }
    },
    {
      "fund": "Main Street Equity Partners",
      "score": 0.78,
      "rationale": {
        "subscores": { "industry": {"raw": 1.0}, "region": {"raw": 1.0}, "revenue": {"coverage_ratio": 0.6}, "employees": {"coverage_ratio": 0.5}, "deal": {"raw": 0.0} }
      }
    }
  ]
}
```

## UI walkthrough

The Streamlit UI renders the pipeline into scannable sections:

1) Purpose — brief description of the tool
2) Company profile — name, confidence, revenue band, employee band, industries, locations, summary, offerings
3) Key insights — quick bullets synthesized from the profile
4) Shortlist (ranked) — table of funds with factor fits and a stacked bar chart showing score composition
5) Detailed breakdown — per-fund table of factor details in natural language (industry, region, revenue, employees, deal)
6) Summary — one consolidated set of bullets + conclusion for each shortlisted fund (shown only here)

Chat notes in the UI are appended only when you press Analyze and are de-duplicated across reruns.
In-session memory: Your chat notes persist within the current Streamlit session and are passed as additional context to the agent; use Clear chat to reset.

## Architecture

Components:

- UI: `streamlit_app.py`
- Agent: `llm_pe_matcher.agent.run_agent`
- Tools: `llm_pe_matcher.tools.fetch_url`, `llm_pe_matcher.tools.query_pe_db`
- Scoring: deterministic weights and subscores; nuanced deal-type explanations
- Data: `data/pe_funds.json`
 - Session memory: Streamlit `session_state.chat` retains user notes during the session and feeds `extra_context`

Data flow:

```
User URL/context
  |
  v
Streamlit UI  ───────────────┐
  |                         |
  | calls run_agent(url, data, model, offline, context)
  v                         |
Agent (Responses API)        |
  |                         |
  |-- fetch_url(url) ------>|
  |   (HTML → text)         |
  |                         |
  |-- LLM summarize → company_profile
  |                         |
  |-- query_pe_db(criteria) → shortlist (scores + subscores)
  v                         |
Result JSON (profile + shortlist)
  |
  v
UI renders: metrics, insights, ranked table, chart, per-fund details, final summary
```

Factor weights and contribution math are applied locally, so results are reproducible across runs given the same inputs.

## Troubleshooting

- Ensure `OPENAI_API_KEY` is set.
- If import fails, confirm you are running from the repo root and the venv is active.
- Some sites block automated fetches; try another URL.
 - If the UI seems to repeat your context, use the Clear chat button; the app already deduplicates notes on Analyze.

## Recent updates

- Switched extraction pipeline to the OpenAI Responses API
- Added Streamlit UI with Purpose and a single Summary section (moved from per-fund expanders)
- Implemented nuanced deal-type reasoning (MATCH / NEAR MATCH / MISMATCH) with synonyms
- Added stacked contribution chart and natural-language factor details
- Prevented duplicate context in chat; removed posting the final summary to chat
- Expanded demo dataset with more funds and richer offerings
 - Added a comprehensive technical spec: see docs/TECH_SPEC.md
