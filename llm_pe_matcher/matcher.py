from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .tools import query_pe_db


DEFAULT_TOP_K = 5


def shortlist_pe_funds(
    company_profile: Dict[str, Any],
    dataset_path: str,
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict[str, Any]]:
    """Score and return top-k funds with brief rationales."""
    industries = company_profile.get("industries", [])
    regions = company_profile.get("locations", [])

    # Infer regions to broader labels (naive heuristic)
    reg_labels = []
    for loc in regions:
        t = (loc or "").lower()
        if any(x in t for x in ["united states", "usa", "us", "california", "texas", "ny", "new york"]):
            reg_labels.append("US")
        elif any(x in t for x in ["canada", "ontario", "quebec"]):
            reg_labels.append("Canada")
        elif any(x in t for x in ["uk", "united kingdom", "england", "london", "europe"]):
            reg_labels.append("Europe")
    reg_labels = list(dict.fromkeys(reg_labels))  # dedupe, preserve order

    criteria = {
        "industries": industries,
        "regions": reg_labels or ["US"],  # default bias to US for SMB demo
    }

    # Revenue & employee ranges if available
    rev = company_profile.get("revenue_range_usd") or {}
    emp = company_profile.get("employee_count_range") or {}
    if rev:
        criteria["revenue_usd"] = rev
    if emp:
        criteria["employees"] = emp

    # Assume buyout by default for SMB exits
    criteria["deal_type"] = "Buyout"

    ranked = query_pe_db(criteria, dataset_path)

    # Add rationale text
    out = []
    for r in ranked[: top_k * 2]:  # over-fetch for better cutoff with threshold
        f = r["match"]
        reasons = []
        if industries and set(x.lower() for x in industries).intersection(x.lower() for x in f.get("industries", [])):
            reasons.append("industry fit")
        if reg_labels and set(x.lower() for x in reg_labels).intersection(x.lower() for x in f.get("regions", [])):
            reasons.append("region fit")
        if rev:
            reasons.append("revenue range compatible")
        if emp:
            reasons.append("employee range compatible")
        reasons = reasons or ["generalist flexibility"]

        subs = r.get("subscores", {})
        rationale = {
            "summary": ", ".join(reasons),
            "subscores": subs,
        }
        out.append({
            "fund": r["fund"],
            "score": r["score"],
            "rationale": rationale,
        })

    # Keep top_k with score threshold
    out = [x for x in out if x["score"] >= 0.2][:top_k]
    return out
