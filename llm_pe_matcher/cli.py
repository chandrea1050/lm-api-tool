from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from .agent import run_agent

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "pe_funds.json"

console = Console()


def main():
    parser = argparse.ArgumentParser(description="SMB → PE Fund Matcher (Prototype)")
    parser.add_argument("url", help="Company website URL")
    parser.add_argument("--k", type=int, default=5, help="Top-K funds (default 5)")
    parser.add_argument("--model", type=str, default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), help="OpenAI model")
    parser.add_argument("--json-output", type=str, help="Path to save full JSON output")
    parser.add_argument("--offline", action="store_true", help="Run without OpenAI (heuristic extractor)")
    parser.add_argument("--context", type=str, help="Optional extra context (e.g., size, HQ, preferences)")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        console.print(f"[red]Dataset not found at {DATA_PATH}[/red]")
        raise SystemExit(1)

    console.print(f"[bold]Analyzing[/bold]: {args.url}")
    result = run_agent(
        args.url,
        str(DATA_PATH),
        model=args.model,
        top_k=args.k,
        offline=bool(args.offline),
        extra_context=args.context,
    )

    company = result.get("company_profile", {})
    shortlist = result.get("shortlist", [])

    # Pretty print
    console.rule("Company profile")
    console.print_json(data=company)

    console.rule("Shortlist")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Fund")
    table.add_column("Score", justify="right")
    table.add_column("Rationale")
    for r in shortlist:
        rationale = r.get("rationale", {})
        summary = rationale.get("summary", "")
        table.add_row(r.get("fund", ""), f"{r.get('score', 0):.2f}", summary)
    console.print(table)

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        console.print(f"Saved JSON to {args.json_output}")


if __name__ == "__main__":
    main()
