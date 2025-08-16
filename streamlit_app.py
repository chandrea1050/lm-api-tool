from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv
import pandas as pd
import altair as alt

from llm_pe_matcher.agent import run_agent

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "pe_funds.json"

load_dotenv()

st.set_page_config(page_title="SMB → PE Buyer Shortlist", layout="wide")

st.title("SMB → PE Buyer Shortlist Prototype")

st.markdown("### Purpose")
st.write(
    "This prototype leverages advanced AI capabilities, specifically utilizing the OpenAI API to access cutting-edge LLMs such as GPT-5 and the OpenAI Responses API as a foundational agentic tool. Its primary function is to analyze small and medium-sized business (SMB) websites, extracting concise company profiles and generating a ranked shortlist of private equity buyers based on a locally sourced dataset. The process is distinguished by a transparent, factor-by-factor rationale and detailed quantitative breakdowns, ensuring clarity and accountability in the selection methodology. By combining the simplicity and efficiency of Chat Completions with enhanced agentic reasoning, this solution delivers powerful, actionable insights tailored to the needs of both SMBs and investment professionals."
)

with st.sidebar:
    st.header("Settings")
    default_model = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07")
    model = st.text_input("OpenAI model", value=default_model, help="Model name you have access to")
    offline = st.toggle("Offline mode (heuristic only)", value=(os.getenv("OPENAI_API_KEY") is None))
    k = st.slider("Top-K funds", min_value=3, max_value=15, value=5, step=1)

st.markdown("### User Interface")
st.write("Enter a company website URL to analyze. Add context in chat if you like.")

if "chat" not in st.session_state:
    st.session_state.chat = []  # list of dicts: {role, content}

# Chat input
with st.container(border=True):
    url = st.text_input("Company website URL", placeholder="https://example.com")
    user_msg = st.text_area("Optional: context or notes", placeholder="e.g., D.E. Shaw evaluating exit options; revenue ~ $25M; HQ in NYC")
    col1, col2 = st.columns([1,1])
    with col1:
        run_btn = st.button("Analyze")
    with col2:
        clear_btn = st.button("Clear chat")

if clear_btn:
    st.session_state.chat = []
    st.session_state.pop("last_submitted_context", None)

# Only append the context when Analyze is clicked, and avoid duplicates across reruns
if run_btn and user_msg:
    if st.session_state.get("last_submitted_context") != user_msg:
        st.session_state.chat.append({"role": "user", "content": user_msg})
        st.session_state["last_submitted_context"] = user_msg

# Display chat
for m in st.session_state.chat:
    align = "left" if m["role"] == "assistant" else "right"
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# Run analysis
def _chat_context() -> str:
    # Concatenate all user messages as extra context
    users = [m["content"] for m in st.session_state.chat if m.get("role") == "user"]
    return "\n".join(users).strip()


def _deal_match_nuance(cdt: Optional[str], fdt_list: List[str], raw: Any, weight: Any, contrib: Any) -> Dict[str, str]:
    """Provide rich natural-language reasoning for deal-type alignment.

    Returns dict with keys:
      - long: multi-sentence explanation for the details table
      - bullet: short bullet for summary
    """
    cdt_norm = (cdt or "").strip().lower()
    fund_norm = [str(x).strip().lower() for x in (fdt_list or [])]
    # Synonyms / adjacency map
    synonyms = {
        "buyout": {"buyout", "lbo", "control", "majority"},
        "majority": {"majority", "control", "buyout"},
        "minority": {"minority", "non-control", "growth minority", "minority growth"},
        "growth": {"growth", "growth equity", "minority"},
        "carve-out": {"carve-out", "carveout", "divestiture"},
        "roll-up": {"roll-up", "rollup", "buy-and-build", "add-on", "platform"},
        "recap": {"recap", "recapitalization"},
    }
    exact = cdt_norm in fund_norm if cdt_norm else False
    syn_set = synonyms.get(cdt_norm, {cdt_norm} if cdt_norm else set())
    synonym_overlap = bool(syn_set.intersection(set(fund_norm))) if cdt_norm else False

    fdt_disp = ", ".join(fdt_list or []) or "—"
    is_match = True if (raw or 0) > 0 else False

    if not cdt_norm:
        long = (
            f"No explicit deal type provided for the company; fund supports {fdt_disp}. "
            f"This factor did not influence scoring (weight {weight})."
        )
        bullet = "Deal type: not specified (factor ignored)"
        return {"long": long, "bullet": bullet}

    if is_match:
        # Exact match counts; also surface relevant alternatives the fund supports
        long = (
            f"Company requests '{cdt}'; fund mandate includes {fdt_disp}. "
            f"Alignment: MATCH — requested deal type is explicitly supported (contribution +{(contrib or 0):.3f}, weight {weight})."
        )
        bullet = f"Deal type: MATCH — requested '{cdt}' supported (fund: {fdt_disp})"
        return {"long": long, "bullet": bullet}

    # No exact match — assess adjacency via synonyms
    if synonym_overlap:
        # Adjacent/nearby coverage exists (e.g., company wants Buyout, fund lists Majority/Control)
        long = (
            f"Company requests '{cdt}'; fund mandate is {fdt_disp}. "
            f"No exact listing for the requested type, but adjacent options are supported (e.g., {cdt} ≈ {', '.join(sorted(syn_set))}). "
            f"Alignment: NEAR MATCH — contribution remains 0 due to strict criteria (weight {weight}), but the fund may accommodate depending on flexibility."
        )
        bullet = f"Deal type: NEAR MATCH — requested '{cdt}' not listed; adjacent options present (fund: {fdt_disp})"
        return {"long": long, "bullet": bullet}

    # Fully mismatched
    long = (
        f"Company requests '{cdt}'; fund mandate is {fdt_disp}. "
        f"Alignment: MISMATCH — requested deal type is not represented; contribution 0 of weight {weight}."
    )
    bullet = f"Deal type: MISMATCH — requested '{cdt}' not in fund mandate (fund: {fdt_disp})"
    return {"long": long, "bullet": bullet}


def _subscores_to_rows(subs: Dict[str, Any]):
    """Return rows where Details is natural language, not JSON."""
    rows = []
    def fmt_money_range(r: Dict[str, Any]) -> str:
        if not r:
            return "—"
        def _fmt(x):
            if x is None:
                return "?"
            try:
                v = float(x)
            except Exception:
                return str(x)
            if v >= 1_000_000_000:
                return f"${v/1_000_000_000:.1f}B"
            if v >= 1_000_000:
                return f"${v/1_000_000:.1f}M"
            if v >= 1_000:
                return f"${v/1_000:.0f}k"
            return f"${int(v)}"
        return f"{_fmt(r.get('min'))} – { _fmt(r.get('max')) }"

    def fmt_int_range(r: Dict[str, Any]) -> str:
        if not r:
            return "—"
        return f"{r.get('min', '?')} – {r.get('max', '?')}"

    def coverage_phrase(cov: Any) -> str:
        try:
            c = float(cov)
        except Exception:
            return "coverage unavailable"
        if c >= 0.95:
            return "fully covered"
        if c >= 0.75:
            return f"mostly covered (~{c*100:.0f}%)"
        if c > 0:
            return f"partially covered (~{c*100:.0f}%)"
        return "no overlap"

    for key in ["industry", "region", "revenue", "employees", "deal"]:
        s = subs.get(key, {}) or {}
        applied = s.get("applied")
        raw = s.get("raw")
        contrib = s.get("contribution")
        weight = s.get("weight")
        details_text = ""
        if key == "industry":
            comp_inds = ", ".join(s.get("company_industries", []) or []) or "—"
            fund_inds = ", ".join(s.get("fund_industries", []) or []) or "—"
            oc = s.get("overlap_count")
            cc = s.get("company_count")
            details_text = f"Industry overlap {oc}/{cc}. Company: {comp_inds}. Fund: {fund_inds}."
        elif key == "region":
            comp_regs = ", ".join(s.get("company_regions", []) or []) or "—"
            fund_regs = ", ".join(s.get("fund_regions", []) or []) or "—"
            oc = s.get("overlap_count")
            details_text = f"Regional alignment {'yes' if (raw or 0)>0 else 'no'} (overlap={oc}). Company regions: {comp_regs}. Fund regions: {fund_regs}."
        elif key == "revenue":
            binfit = s.get('binary_fit')
            cov = s.get('coverage_ratio')
            if binfit == 1.0:
                details_text = (
                    f"Company revenue {fmt_money_range(s.get('company_range') or {})} is within the fund's target range "
                    f"({coverage_phrase(cov)})."
                )
            else:
                details_text = (
                    f"Company revenue {fmt_money_range(s.get('company_range') or {})} is outside the fund's target range "
                    f"({coverage_phrase(cov)})."
                )
        elif key == "employees":
            binfit = s.get('binary_fit')
            cov = s.get('coverage_ratio')
            if binfit == 1.0:
                details_text = (
                    f"Company headcount {fmt_int_range(s.get('company_range') or {})} is within the fund's preferred band "
                    f"({coverage_phrase(cov)})."
                )
            else:
                details_text = (
                    f"Company headcount {fmt_int_range(s.get('company_range') or {})} is outside the fund's preferred band "
                    f"({coverage_phrase(cov)})."
                )
        elif key == "deal":
            cdt = s.get("company_deal_type")
            fdt_list = s.get("fund_deal_types", []) or []
            if not applied:
                nuance = _deal_match_nuance(None, fdt_list, raw, weight, contrib)
            else:
                nuance = _deal_match_nuance(cdt, fdt_list, raw, weight, contrib)
            details_text = nuance["long"]

        rows.append({
            "Factor": key.title(),
            "Applied": applied,
            "Raw": raw,
            "Contribution": contrib,
            "Weight": weight,
            "Details": details_text,
        })
    return rows

def _nl_bulleted_summary_for_fund(fund_name: str, score: float, subs: Dict[str, Any]) -> Dict[str, Any]:
    """Return bullets and a conclusion explaining match/mismatch reasons for this fund."""
    ind = subs.get("industry", {}) or {}
    reg = subs.get("region", {}) or {}
    rev = subs.get("revenue", {}) or {}
    emp = subs.get("employees", {}) or {}
    deal = subs.get("deal", {}) or {}

    bullets: List[str] = []
    # Industry
    if ind.get("applied"):
        bullets.append(f"Industry: overlap {ind.get('overlap_count')}/{ind.get('company_count')}")
    # Region
    if reg.get("applied"):
        bullets.append("Region: geographic fit" if (reg.get("raw") or 0) > 0 else "Region: no geographic overlap")
    # Revenue
    if rev.get("applied"):
        cov_r = rev.get('coverage_ratio') or 0
        bullets.append("Revenue: within focus (" + ("fully covered" if cov_r>=0.95 else f"~{cov_r*100:.0f}% covered") + ")")
    # Employees
    if emp.get("applied"):
        cov_e = emp.get('coverage_ratio') or 0
        bullets.append("Employees: within focus (" + ("fully covered" if cov_e>=0.95 else f"~{cov_e*100:.0f}% covered") + ")")
    # Deal type with explicit reason
    if deal.get("applied"):
        nuance = _deal_match_nuance(
            deal.get("company_deal_type"),
            deal.get("fund_deal_types", []) or [],
            deal.get("raw"),
            deal.get("weight"),
            deal.get("contribution"),
        )
        bullets.append(nuance["bullet"])

    # Conclusion
    if deal.get("applied") and (deal.get("raw") or 0) <= 0:
        conclusion = (
            f"Conclusion: Strong fit on non-deal factors, but deal-type misalignment; consider only if the fund is flexible. "
            f"Overall score {score:.2f}."
        )
    else:
        conclusion = f"Conclusion: Overall alignment is strong (including deal type). Overall score {score:.2f}."

    return {"bullets": bullets or ["Generalist compatibility"], "conclusion": conclusion}


if run_btn and url:
    with st.spinner("Fetching and analyzing website …"):
        try:
            result = run_agent(
                url,
                str(DATA_PATH),
                model=model,
                top_k=k,
                offline=offline,
                extra_context=_chat_context(),
            )
        except Exception as e:
            st.error(f"Error: {e}")
            result = None

    if result:
        company = result.get("company_profile", {})
        shortlist = result.get("shortlist", [])

        # ---- Company Profile: Clear summary cards ----
        st.subheader("Company profile")

        def _fmt_currency_range(r: Dict[str, Any]) -> str:
            if not r:
                return "—"
            mn = r.get("min")
            mx = r.get("max")
            if mn is None and mx is None:
                return "—"
            def _fmt(x):
                if x is None:
                    return "?"
                try:
                    v = float(x)
                except Exception:
                    return str(x)
                if v >= 1_000_000_000:
                    return f"${v/1_000_000_000:.1f}B"
                if v >= 1_000_000:
                    return f"${v/1_000_000:.1f}M"
                if v >= 1_000:
                    return f"${v/1_000:.0f}k"
                return f"${int(v)}"
            return f"{_fmt(mn)} – {_fmt(mx)}"

        def _fmt_int_range(r: Dict[str, Any]) -> str:
            if not r:
                return "—"
            mn = r.get("min")
            mx = r.get("max")
            if mn is None and mx is None:
                return "—"
            return f"{mn or '?'} – {mx or '?'}"

        cols = st.columns(4)
        with cols[0]:
            st.metric("Company", company.get("company_name") or "Unknown")
        with cols[1]:
            st.metric("Confidence", f"{(company.get('confidence') or 0)*100:.0f}%")
        with cols[2]:
            st.metric("Revenue (est)", _fmt_currency_range(company.get("revenue_range_usd") or {}))
        with cols[3]:
            st.metric("Employees (est)", _fmt_int_range(company.get("employee_count_range") or {}))

        cols2 = st.columns(2)
        with cols2[0]:
            inds = company.get("industries") or []
            locs = company.get("locations") or []
            st.markdown("**Industries:** " + (", ".join(inds) if inds else "—"))
            st.markdown("**Locations:** " + (", ".join(locs) if locs else "—"))
        with cols2[1]:
            offs = company.get("offerings") or []
            summary_txt = (company.get("summary") or "").strip()
            st.markdown("**Summary:** " + (summary_txt if summary_txt else "—"))
            if offs:
                st.markdown("**Offerings (detailed):**")
                for i, o in enumerate(offs[:10], start=1):
                    st.write(f"{i}. {o}")
            else:
                st.markdown("**Offerings:** —")

        # Key insights
        st.markdown("### Key insights")
        insights: List[str] = []
        if inds:
            insights.append(f"Sector focus: {', '.join(inds)}")
        if locs:
            insights.append(f"Geography: {', '.join(locs)}")
        rev = company.get("revenue_range_usd") or {}
        emp = company.get("employee_count_range") or {}
        if rev:
            insights.append(f"Revenue band: {_fmt_currency_range(rev)}")
        if emp:
            insights.append(f"Employee band: {_fmt_int_range(emp)}")
        if not insights:
            insights.append("Limited explicit signals on the website; estimates applied.")
        for i in insights:
            st.write(f"• {i}")

        # ---- Shortlist: Ranked table + visuals ----
        st.subheader("Shortlist (ranked)")

        # Build a summary table
        rows = []
        contrib_rows = []
        for rank, r in enumerate(shortlist, 1):
            fund = r.get("fund")
            score = r.get("score", 0)
            subs = (r.get("rationale", {}) or {}).get("subscores", {})
            def _get(path_key, key):
                d = subs.get(path_key, {})
                return d.get(key)
            row = {
                "Rank": rank,
                "Fund": fund,
                "Score": round(float(score or 0), 3),
                "Industry fit": _get("industry", "raw"),
                "Region fit": _get("region", "raw"),
                "Revenue coverage": _get("revenue", "coverage_ratio"),
                "Employees coverage": _get("employees", "coverage_ratio"),
                "Deal type match": _get("deal", "raw"),
            }
            rows.append(row)
            # contributions for stacked bar chart
            for factor in ["industry", "region", "revenue", "employees", "deal"]:
                contrib = (subs.get(factor, {}) or {}).get("contribution") or 0.0
                contrib_rows.append({"Fund": fund, "Factor": factor.title(), "Contribution": float(contrib)})

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True)

            # Visual: stacked contributions per fund
            contrib_df = pd.DataFrame(contrib_rows)
            if not contrib_df.empty:
                st.markdown("**Score composition by factor**")
                chart = (
                    alt.Chart(contrib_df)
                    .mark_bar()
                    .encode(
                        x=alt.X("sum(Contribution)", stack="normalize", title="Relative contribution"),
                        y=alt.Y("Fund", sort="-x"),
                        color=alt.Color("Factor", legend=alt.Legend(orient="bottom")),
                        tooltip=["Fund", "Factor", alt.Tooltip("Contribution", format=".3f")],
                    )
                    .properties(height=200+20*len(df))
                )
                st.altair_chart(chart, use_container_width=True)

        # Detailed per-fund breakdown (optional)
        st.markdown("### Detailed Breakdown")
        for i, r in enumerate(shortlist, 1):
            with st.expander(f"{i}. {r.get('fund')} — score {r.get('score'):.2f}", expanded=(i==1)):
                rationale = r.get("rationale", {})
                subs = rationale.get("subscores", {})
                # Natural-language details table
                rows = _subscores_to_rows(subs)
                st.dataframe(rows, hide_index=True)

        # Summary section (separate from Detailed breakdown)
        if shortlist:
            st.markdown("### Summary")
            top_lines = []
            for r in shortlist:  # include all shortlisted funds
                subs = (r.get("rationale", {}) or {}).get("subscores", {})
                summ = _nl_bulleted_summary_for_fund(r.get('fund',''), float(r.get('score') or 0), subs)
                header = f"**{r.get('fund')}** — score {float(r.get('score') or 0):.2f}"
                bullets = "\n".join([f"  - {b}" for b in summ["bullets"]])
                block = f"{header}\n{bullets}\n{summ['conclusion']}"
                top_lines.append(block)
            assistant_text = "\n\n".join(top_lines)
            # Render summary on page
            st.markdown(assistant_text)

        # Download buttons and raw JSON toggles
        colA, colB = st.columns(2)
        with colA:
            st.download_button(
                "Download result JSON",
                data=json.dumps(result, ensure_ascii=False, indent=2),
                file_name="pe_shortlist_result.json",
                mime="application/json",
            )
        with colB:
            if st.toggle("Show raw JSON details"):
                st.markdown("#### Raw company_profile")
                st.json(company)
                st.markdown("#### Raw shortlist")
                st.json(shortlist)
