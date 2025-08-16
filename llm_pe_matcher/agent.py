from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from .tools import fetch_url
from .matcher import shortlist_pe_funds, DEFAULT_TOP_K

load_dotenv()

SYSTEM_PROMPT = (
    "You are a pragmatic M&A analyst agent. Given a company website, extract a structured company_profile."
    "\n\n"
    "Instructions:\n"
    "- Infer fields: company_name, url, industries, locations, employee_count_range, revenue_range_usd, offerings, summary, confidence (0-1).\n"
    "- Consider any user-provided context as clarifications or overrides (size, regions, deal preferences).\n"
    "- Return strictly a JSON object for company_profile."
)


def _client(model: str | None = None) -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=api_key)


def run_agent(
    url: str,
    dataset_path: str,
    model: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    offline: bool = False,
    extra_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the agent. If offline or no API key, use a heuristic extractor."""
    if offline or not os.getenv("OPENAI_API_KEY"):
        company_profile = _offline_extract_profile(url)
        shortlist = shortlist_pe_funds(company_profile, dataset_path, top_k=top_k)
        return {"company_profile": company_profile, "shortlist": shortlist}

    model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    client = _client(model)

    # Tool definitions for structured tool calling
    # Fetch page locally, then use Responses API to extract profile
    fetched = fetch_url(url)

    user_parts: List[Dict[str, Any]] = [
        {"type": "input_text", "text": "Analyze the following web page content and return only company_profile as JSON."},
        {"type": "input_text", "text": f"URL: {url}"},
    ]
    if extra_context:
        user_parts.append({"type": "input_text", "text": f"Context: {extra_context}"})
    if fetched.title:
        user_parts.append({"type": "input_text", "text": f"Page title: {fetched.title}"})
    # Truncate to control tokens
    user_parts.append({"type": "input_text", "text": "Page text (truncated):"})
    user_parts.append({"type": "input_text", "text": fetched.text[:20000]})

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_parts},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    # The Responses API provides output_text with our JSON
    content_text = getattr(resp, "output_text", None)
    if not content_text:
        # Fallback to first text segment
        try:
            # resp.output is a list of items with content parts
            segments = getattr(resp, "output", [])
            if segments:
                first = segments[0]
                parts = getattr(first, "content", [])
                texts = [p.text for p in parts if getattr(p, "type", "") == "output_text"]
                content_text = texts[0] if texts else None
        except Exception:
            content_text = None
    company_profile = {}
    if content_text:
        try:
            company_profile = json.loads(content_text)
        except json.JSONDecodeError:
            # Try to extract JSON object from text
            try:
                start = content_text.find("{")
                end = content_text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    company_profile = json.loads(content_text[start : end + 1])
            except Exception:
                company_profile = {}

    # Local shortlist using deterministic matcher
    shortlist = shortlist_pe_funds(company_profile, dataset_path, top_k=top_k)

    result = {
        "company_profile": company_profile,
        "shortlist": shortlist,
    }
    return result


# ---- Offline heuristic extractor (for demos without API key) ----

def _offline_extract_profile(url: str) -> Dict[str, Any]:
    fetched = fetch_url(url)
    title = (fetched.title or "").strip()
    text = (fetched.text or "").strip()

    # company name from title
    name = title
    for sep in ["|", "–", "-", "::", ":"]:
        if sep in name:
            name = name.split(sep)[0].strip()
            break
    if not name:
        name = url.replace("https://", "").replace("http://", "").split("/")[0]

    # naive industry detection
    industry_map = {
        "software": ["saas", "software", "platform", "cloud"],
        "tech-enabled services": ["managed service", "it services", "digital"],
        "industrial": ["manufacturing", "industrial", "plant", "fabrication"],
        "healthcare": ["clinic", "patient", "medical", "healthcare"],
        "consumer": ["ecommerce", "retail", "brand", "store", "shop"],
        "business services": ["b2b", "consulting", "outsourcing", "agency"],
    }
    tl = text.lower()
    industries: List[str] = []
    for label, kws in industry_map.items():
        if any(k in tl for k in kws):
            industries.append(label.title())
    if not industries:
        industries = ["Business Services"]

    # location heuristic
    locations: List[str] = []
    for token in ["United States", "USA", "US", "Canada", "United Kingdom", "Europe"]:
        if token.lower() in tl:
            locations.append(token)
    locations = list(dict.fromkeys(locations)) or ["United States"]

    # offerings heuristic: take first sentences mentioning "products" or "services"
    offerings: List[str] = []
    for kw in ["products", "services", "solutions", "platform"]:
        m = _first_sentence_with(tl, kw)
        if m:
            offerings.append(m[:140])
    offerings = offerings[:5]

    profile = {
        "company_name": name,
        "url": url,
        "industries": industries,
        "locations": locations,
        "employee_count_range": {"min": 10, "max": 500},
        "revenue_range_usd": {"min": 5000000, "max": 80000000},
        "offerings": offerings,
        "summary": (title or (offerings[0] if offerings else ""))[:280],
        "confidence": 0.45,
    }
    return profile


def _first_sentence_with(text_lower: str, kw: str) -> str | None:
    i = text_lower.find(kw)
    if i == -1:
        return None
    # naive sentence bounds
    start = max(0, text_lower.rfind(".", 0, i) + 1)
    end = text_lower.find(".", i)
    if end == -1:
        end = min(len(text_lower), i + 240)
    return text_lower[start:end].strip().capitalize()
