from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass
class FetchedPage:
    url: str
    status_code: int
    title: Optional[str]
    text: str
    meta: Dict[str, Any]


class FetchError(Exception):
    pass


def fetch_url(url: str, timeout: int = 15) -> FetchedPage:
    """Fetch and lightly clean a web page content.

    Note: This is a best-effort basic fetch; JS-heavy sites may render poorly.
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise FetchError(str(e))

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        # still try to capture something
        text = _clean_text(resp.text or "")
        return FetchedPage(url=url, status_code=resp.status_code, title=None, text=text, meta={
            "content_type": content_type,
            "headers": dict(resp.headers),
        })

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script/style/nav/footer tags
    for tag in soup(["script", "style", "noscript", "nav", "footer", "svg"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else None

    # Heuristic: prefer main > article > body
    main = soup.find("main") or soup.find("article") or soup.body
    text = _clean_text(main.get_text(separator=" ")) if main else _clean_text(soup.get_text(" "))

    meta = {
        "fetched_at": int(time.time()),
        "content_type": content_type,
        "title": title,
    }
    return FetchedPage(url=url, status_code=resp.status_code, title=title, text=text, meta=meta)


# Local PE dataset query

def query_pe_db(criteria: Dict[str, Any], dataset_path: str) -> List[Dict[str, Any]]:
    """Filter the local PE fund dataset with scoring and a quantitative breakdown.

    criteria example:
    {
        "industries": ["Industrial", "Software"],
        "regions": ["US"],
        "revenue_usd": {"min": 15000000, "max": 40000000},
        "employees": {"min": 50, "max": 200},
        "deal_type": "Buyout"
    }
    Returns each result with keys: fund, score, match (fund row), subscores (detailed breakdown)
    """
    with open(dataset_path, "r", encoding="utf-8") as f:
        funds = json.load(f)

    inds = set([i.lower() for i in criteria.get("industries", [])])
    regs = set([r.lower() for r in criteria.get("regions", [])])
    rev = criteria.get("revenue_usd") or {}
    emp = criteria.get("employees") or {}
    deal = (criteria.get("deal_type") or "").lower()

    def _range_coverage(cmin: Optional[float], cmax: Optional[float], fmin: Optional[float], fmax: Optional[float]) -> Optional[float]:
        """Return overlap coverage ratio of company range within fund range (0-1), or None if not computable."""
        if cmin is None or cmax is None or fmin is None or fmax is None:
            return None
        if cmax < cmin or fmax < fmin:
            return 0.0
        inter_min = max(cmin, fmin)
        inter_max = min(cmax, fmax)
        inter = max(0.0, inter_max - inter_min)
        clen = max(1e-9, float(cmax - cmin))
        return max(0.0, min(1.0, inter / clen))

    def score_with_breakdown(f: Dict[str, Any]) -> Dict[str, Any]:
        weights = {
            "industry": 0.4,
            "region": 0.2,
            "revenue": 0.2,
            "employees": 0.1,
            "deal": 0.1,
        }
        subs = {}
        total = 0.0

        # industry overlap
        if inds:
            fund_inds = [x.lower() for x in f.get("industries", [])]
            overlap = len(inds.intersection(fund_inds))
            raw = min(1.0, overlap / max(1, len(inds)))
            contrib = weights["industry"] * raw
            subs["industry"] = {
                "applied": True,
                "raw": raw,
                "overlap_count": overlap,
                "company_count": len(inds),
                "weight": weights["industry"],
                "contribution": round(contrib, 4),
                "company_industries": sorted(list(inds)),
                "fund_industries": f.get("industries", []),
            }
            total += contrib
        else:
            subs["industry"] = {"applied": False, "weight": weights["industry"]}

        # region overlap
        if regs:
            fund_regs = [x.lower() for x in f.get("regions", [])]
            overlap = len(regs.intersection(fund_regs))
            raw = 1.0 if overlap > 0 else 0.0
            contrib = weights["region"] * raw
            subs["region"] = {
                "applied": True,
                "raw": raw,
                "overlap_count": overlap,
                "weight": weights["region"],
                "contribution": round(contrib, 4),
                "company_regions": sorted(list(regs)),
                "fund_regions": f.get("regions", []),
            }
            total += contrib
        else:
            subs["region"] = {"applied": False, "weight": weights["region"]}

        # revenue fit
        f_rev = f.get("revenue_focus_usd", {})
        if rev:
            lo_ok = rev.get("min") is None or f_rev.get("min") is None or rev.get("min") >= f_rev.get("min")
            hi_ok = rev.get("max") is None or f_rev.get("max") is None or rev.get("max") <= f_rev.get("max")
            binary_fit = 1.0 if (lo_ok and hi_ok) else 0.0
            coverage = _range_coverage(rev.get("min"), rev.get("max"), f_rev.get("min"), f_rev.get("max"))
            raw = binary_fit
            contrib = weights["revenue"] * raw
            subs["revenue"] = {
                "applied": True,
                "raw": raw,
                "binary_fit": binary_fit,
                "coverage_ratio": coverage,
                "company_range": rev,
                "fund_range": f_rev,
                "weight": weights["revenue"],
                "contribution": round(contrib, 4),
            }
            total += contrib
        else:
            subs["revenue"] = {"applied": False, "weight": weights["revenue"]}

        # employees fit
        f_emp = f.get("employee_focus", {})
        if emp:
            lo_ok = emp.get("min") is None or f_emp.get("min") is None or emp.get("min") >= f_emp.get("min")
            hi_ok = emp.get("max") is None or f_emp.get("max") is None or emp.get("max") <= f_emp.get("max")
            binary_fit = 1.0 if (lo_ok and hi_ok) else 0.0
            coverage = _range_coverage(emp.get("min"), emp.get("max"), f_emp.get("min"), f_emp.get("max"))
            raw = binary_fit
            contrib = weights["employees"] * raw
            subs["employees"] = {
                "applied": True,
                "raw": raw,
                "binary_fit": binary_fit,
                "coverage_ratio": coverage,
                "company_range": emp,
                "fund_range": f_emp,
                "weight": weights["employees"],
                "contribution": round(contrib, 4),
            }
            total += contrib
        else:
            subs["employees"] = {"applied": False, "weight": weights["employees"]}

        # deal type match
        if deal:
            raw = 1.0 if deal in [d.lower() for d in f.get("deal_types", [])] else 0.0
            contrib = weights["deal"] * raw
            subs["deal"] = {
                "applied": True,
                "raw": raw,
                "company_deal_type": deal,
                "fund_deal_types": f.get("deal_types", []),
                "weight": weights["deal"],
                "contribution": round(contrib, 4),
            }
            total += contrib
        else:
            subs["deal"] = {"applied": False, "weight": weights["deal"]}

        return {"score": round(total, 4), "subscores": subs}

    scored = []
    for f in funds:
        s = score_with_breakdown(f)
        scored.append({
            "fund": f["name"],
            "score": s["score"],
            "match": f,
            "subscores": s["subscores"],
        })

    return sorted(scored, key=lambda x: x["score"], reverse=True)
