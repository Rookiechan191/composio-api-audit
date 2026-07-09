"""
Composio take-home: SDK cross-check.

Uses Composio's own SDK to fetch their real toolkit registry, then checks it
against each app's `existing_mcp` guess from research_agent.py's Pass 1.

Run:
    1. Free key, no card: https://app.composio.dev -> Settings -> API Keys
    2. Add COMPOSIO_API_KEY to .env
    3. pip install composio (already in requirements.txt)
    4. python composio_toolkit_check.py
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from composio import Composio

load_dotenv()

DATA_DIR = Path(__file__).parent / "data"
RESULTS_FILE = DATA_DIR / "results.json"
CROSSCHECK_FILE = DATA_DIR / "composio_crosscheck.json"


def load_results():
    return json.loads(RESULTS_FILE.read_text())


def fetch_composio_toolkit_names(client):
    """Fetch every toolkit slug/name Composio actually has built."""
    names = set()
    resp = client.toolkits.list()
    items = getattr(resp, "items", resp)  # handle either shape
    for tk in items:
        slug = getattr(tk, "slug", None) if not isinstance(tk, dict) else tk.get("slug")
        name = getattr(tk, "name", None) if not isinstance(tk, dict) else tk.get("name")
        if slug:
            names.add(str(slug).lower())
        if name:
            names.add(str(name).lower())
    return names


def normalize(name):
    return "".join(c for c in name.lower() if c.isalnum())


def matches_registry(app_name, toolkit_names):
    target = normalize(app_name)
    for tk in toolkit_names:
        tk_norm = normalize(tk)
        if tk_norm == target or tk_norm in target or target in tk_norm:
            return True
    return False


def main():
    client = Composio()  # reads COMPOSIO_API_KEY from .env
    print("Fetching Composio's toolkit registry...")
    toolkit_names = fetch_composio_toolkit_names(client)
    print(f"  {len(toolkit_names)} toolkit names/slugs loaded.")

    results = load_results()
    crosscheck = []
    disagreements = 0

    for key, record in results.items():
        if record.get("error") or record.get("parse_error"):
            continue
        name = record.get("name", "")
        guessed = record.get("existing_mcp", "unknown")
        actual = matches_registry(name, toolkit_names)

        agree = (guessed is True and actual) or (guessed is False and not actual) or (guessed == "unknown")
        if not agree:
            disagreements += 1

        crosscheck.append({
            "id": record.get("id"),
            "name": name,
            "pass1_guessed_existing_mcp": guessed,
            "composio_registry_has_toolkit": actual,
            "agrees_with_pass1": agree,
        })

    CROSSCHECK_FILE.write_text(json.dumps(crosscheck, indent=2))
    print(f"Done. {len(crosscheck)} apps checked, {disagreements} disagreements "
          f"with Pass 1's existing_mcp guess. Written to {CROSSCHECK_FILE}")


if __name__ == "__main__":
    main()