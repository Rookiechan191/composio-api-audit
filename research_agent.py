"""
Composio take-home: research agent, Pass 1.

Two-stage pipeline, decoupled on purpose:
  1. SEARCH  -- Tavily API (free tier: 1,000 calls/month, no credit card).
  2. EXTRACT -- plain Groq chat model (llama-3.1-8b-instant, NOT groq/compound)
     reads the search results and produces strict JSON.

Why not groq/compound: it bundles search+generation into one call and burns
through the free-tier tokens-per-minute budget in a single request (chained
search hops), which is what caused the earlier rate-limit wall. Splitting the
two steps means each one stays cheap: one Tavily credit per app, and a small
Groq prompt per app using a model with a much more generous free RPD/TPM quota.

NOTE: switched from llama-3.3-70b-versatile to llama-3.1-8b-instant --
70B's 100K TPD budget is fully burned for today. 8B has a separate 500K TPD /
14,400 RPD pool and is plenty capable for extracting structured JSON out of
short search snippets (not a reasoning-heavy task).

Run:
    1. Get a free key at tavily.com (no card) -> TAVILY_API_KEY
    2. Get a free key at console.groq.com (no card) -> GROQ_API_KEY
    3. Put both in .env (see .env.example)
    4. pip install -r requirements.txt
    5. python research_agent.py

Resume: just re-run. Already-completed (non-error) app ids are skipped.
"""

import json
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq
from tavily import TavilyClient

load_dotenv()

DATA_DIR = Path(__file__).parent / "data"
SEED_FILE = DATA_DIR / "apps_seed.json"
RESULTS_FILE = DATA_DIR / "results.json"

GROQ_MODEL = "llama-3.1-8b-instant"  # 500K TPD / 14,400 RPD -- separate quota
# pool from 70B, which is fully burned for today. Plenty capable for
# extracting structured JSON from short search snippets (not a reasoning task).

SYSTEM_PROMPT = """You are a product-ops researcher. You will be given an app \
name plus a handful of web search results about its developer/API docs. Using \
ONLY the information in those search results (don't invent anything not \
supported by them), answer with STRICT JSON only (no markdown fences, no \
preamble, no commentary). Fields:

{
  "id": <int, echoed back>,
  "name": "<string, echoed back>",
  "category": "<string, echoed back>",
  "one_liner": "<what the app does, 1 sentence>",
  "auth_methods": ["OAuth2" | "API key" | "Basic" | "Token" | "Other" | "Unknown"],
  "access": "self_serve" | "gated_paid" | "gated_partnership" | "gated_admin_approval" | "unknown",
  "access_note": "<short note on the gate, e.g. 'free dev sandbox' or 'requires sales contact'>",
  "api_surface": "<REST/GraphQL, roughly how broad — e.g. 'broad REST, 50+ endpoints'>",
  "existing_mcp": true | false | "unknown",
  "buildable_verdict": "buildable_now" | "buildable_with_workaround" | "blocked",
  "main_blocker": "<if not buildable_now, the main blocker, else null>",
  "evidence_url": "<pick the single most relevant URL from the search results provided>",
  "confidence": "high" | "medium" | "low"
}

Rules:
- If the search results don't clearly answer a field, use "unknown"/null and set
  confidence "low" rather than guessing.
- evidence_url MUST be one of the URLs actually given to you in the search results.
- Output ONLY the JSON object, nothing else.
"""


def load_seed():
    return json.loads(SEED_FILE.read_text())


def load_results():
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text())
    return {}


def save_results(results):
    RESULTS_FILE.write_text(json.dumps(results, indent=2))


def is_rate_limit_error(e):
    msg = str(e).lower()
    return "tokens per minute" in msg or "rate_limit" in msg or "429" in msg or "413" in msg


def with_retries(fn, max_retries=4, label=""):
    last_err = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if is_rate_limit_error(e):
                wait = 20 * (attempt + 1)
                print(f"  {label} rate limited (attempt {attempt + 1}/{max_retries}); waiting {wait}s")
            else:
                wait = 2 ** attempt
                print(f"  {label} attempt {attempt + 1}/{max_retries} failed ({e}); retrying in {wait}s")
            time.sleep(wait)
    raise last_err


def search_app(tavily, app):
    query = f"{app['name']} API documentation authentication developer access"

    def _do():
        return tavily.search(query=query, max_results=3, search_depth="basic")

    resp = with_retries(_do, label="tavily")
    results = resp.get("results", [])
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")[:400]}
        for r in results
    ]


def extract_json(groq_client, app, search_results):
    results_block = "\n\n".join(
        f"URL: {r['url']}\nTitle: {r['title']}\nContent: {r['content']}"
        for r in search_results
    ) or "(no search results found)"

    user_msg = (
        f"App: {app['name']}\n"
        f"Category: {app['category']}\n"
        f"Hint: {app['hint']}\n\n"
        f"Search results:\n{results_block}\n\n"
        "Return the JSON now."
    )

    def _do():
        return groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )

    resp = with_retries(_do, label="groq")
    raw = (resp.choices[0].message.content or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "id": app["id"], "name": app["name"], "category": app["category"],
            "confidence": "low", "parse_error": True, "raw_output": raw[:500],
        }


def research_one(tavily, groq_client, app):
    search_results = search_app(tavily, app)
    return extract_json(groq_client, app, search_results)


def main():
    groq_client = Groq(timeout=60.0)
    tavily = TavilyClient()  # reads TAVILY_API_KEY from env
    apps = load_seed()
    results = load_results()

    try:
        for app in apps:
            key = str(app["id"])
            existing = results.get(key)
            if existing and not existing.get("error") and not existing.get("parse_error"):
                continue
            print(f"[{app['id']}/100] researching {app['name']}...")
            try:
                record = research_one(tavily, groq_client, app)
            except Exception as e:
                print(f"  ERROR on {app['name']}: {e}")
                record = {
                    "id": app["id"], "name": app["name"], "category": app["category"],
                    "confidence": "low", "error": str(e),
                }
            results[key] = record
            save_results(results)
            time.sleep(8)
    except KeyboardInterrupt:
        print(f"\nStopped early. {len(results)}/100 saved in {RESULTS_FILE} -- just re-run to resume.")
        return

    print(f"Done. {len(results)}/100 apps in {RESULTS_FILE}")


if __name__ == "__main__":
    main()