# Composio API Access Audit

**Take-home assignment: AI Product Ops Intern @ Composio**
100 apps researched by an agent, not by hand — auth, access gates, API surface,
and buildability — with real verification loops and an honest account of
where the agent got it wrong.

**Live page:** [add your GitHub Pages URL here]
**Repo:** this one

---

## What this actually is

Composio's brief: research 100 apps across 10 categories to figure out what it'd
take to turn each into an agent-callable toolkit — auth method, whether access
is self-serve or gated, API surface, and whether an MCP already exists. Build
the research with an agent, not by hand. Verify it. Present it as one
self-explanatory page.

This repo is the pipeline. `composio_api_audit.html` is the deliverable.

---

## Architecture

Three stages, deliberately decoupled:

```
Tavily (search) → Groq (extract to JSON) → Composio SDK (cross-check) → HTML
```

1. **`research_agent.py`** — Pass 1. For each of the 100 apps: Tavily searches
   for its developer docs, a plain Groq model (`llama-3.1-8b-instant`) reads
   the search results and extracts a strict 13-field JSON record. Checkpointed
   to `data/results.json` after every single app — safe to kill and resume.
2. **`composio_toolkit_check.py`** — cross-checks Pass 1's `existing_mcp`
   guesses against Composio's own live toolkit registry (1,249 toolkits,
   fetched via `composio.toolkits.list()`). This is the actual "use Composio's
   own SDK" requirement from the brief, not a decorative wrapper.
3. **Verification** — a schema/consistency pass (pure logic, no API calls) plus
   an independent hand fact-check against real docs on a 10-app sample.
4. **`composio_api_audit.html`** — single static page. Findings table,
   patterns, workflow diagram, verification results, all inline.

---

## Decisions made (and why they changed)

**Orchestrator, v1 → v3:**
- v1 (planned): Anthropic API with native web_search. Dropped — no Anthropic
  key available.
- v2: `groq/compound` — has web search built in, one call does search +
  generation. Dropped — free-tier token-per-minute budget got blown by
  compound's own internal multi-hop search in a single call, causing constant
  rate-limit walls (mislabeled by Groq as a 413, actually a TPM cap).
- v3 (current, shipped): **Tavily (search) + plain Groq (extraction), split
  into two stages.** Tavily's free tier (1,000 searches/month, no card) does
  the actual search. A plain Groq model — not compound — just reads the
  results and returns JSON, which uses a completely different, far more
  generous free-tier quota since it isn't running its own search loop.

**Extraction model, 70B → 8B:**
Started on `llama-3.3-70b-versatile` (100K tokens/day free budget), hit the
daily cap around app #61. Switched to `llama-3.1-8b-instant` (500K tokens/day).
Structured JSON extraction from short search snippets doesn't need 70B-level
reasoning, so this was a free trade, not a quality compromise.

**Why not the Composio SDK for Pass 1 itself:**
Wanted to demonstrate a framework-agnostic agentic research loop first, then
use Composio's SDK for the one thing it's uniquely authoritative for: whether
a toolkit already exists. Their toolkit registry is ground truth for that
question in a way generic web search can never be — Composio is the source.

**No card, anywhere:**
Every API used (Tavily, Groq, Composio) has a genuinely free tier with no
credit card required. This was a hard constraint, not a preference — see
`.env.example` for what's needed.

---

## Verification — three independent loops

### 1. Schema/consistency check (automated, no external calls)
106 structural issues caught across 100 records:
- 97 records where the model's returned `id` didn't match the seed — **not a
  data-quality issue**: the extraction prompt never actually included the
  app's real `id`, so the model had nothing to echo and was guessing. Fixed
  by trusting the seed `id` directly (a future version should stamp `id` from
  the seed post-hoc instead of asking the model for it at all).
- 2 parse errors from malformed model output — manually reconstructed from
  salvageable fields.
- 2 cases of `auth_methods` returned as a bare string instead of a list —
  normalized.
- 2 invalid enum values outside the schema — remapped or flagged.
- 1 internal contradiction (self-serve access + blocked verdict) — traced to
  the excluded iPayX record (see below).

### 2. Hand fact-check against real docs (n=10, independent of the pipeline)
10 records independently checked by hand against real developer documentation:
**6/10 correct** — Ramp, Attio, Devin, GitHub, WhatsApp Business, Stripe.
**4/10 wrong:**
- **Ahrefs** — record said almost everything "unknown." Reality: full
  documented API v3, a free no-subscription tier, and an official MCP server.
  The search step simply failed to surface Ahrefs's own docs.
- **Otter AI** — record claimed free self-serve API. Reality: Otter's public
  API is Enterprise-only, gated behind an account manager.
- **Mermaid CLI** — record described a REST API with OAuth2. Reality: that's
  the API for an unrelated coral-reef data nonprofit that happens to share the
  name "MERMAID." The actual diagramming CLI has no REST API — it's a local
  command-line renderer.
- **iPayX** — no real company matching this name turned up in an independent
  check. Its evidence URL was identical to an unrelated record's URL, a strong
  sign of a recycled/fabricated result. **Excluded from all headline stats.**

### 3. Composio SDK cross-check (live, run against the real API)
`composio_toolkit_check.py` fetched Composio's actual toolkit registry
(1,249 toolkits) and compared it against Pass 1's `existing_mcp` guess for all
98 valid records.

**Result: 31 disagreements (32%).**
- **27 were Pass 1 being too conservative** — Composio already has a toolkit
  for the app (Pipedrive, Discord, Jira, Asana, QuickBooks, and 22 others) but
  the agent's web search couldn't confirm it and marked "unknown" or false.
- **4 were the agent overclaiming** — said an MCP existed when Composio's
  registry shows it doesn't (Ecwid, Vercel, NotebookLM, Otter AI).

**Headline finding:** the research agent under-reports MCP coverage rather
than fabricating it — the safer failure mode, but it means `existing_mcp` in
the main dataset should be read as a floor, not a ceiling. Composio's own
registry is the better source of truth for that one field specifically.

---

## How to run it yourself

```bash
git clone <this repo>
cd composio-research
pip install -r requirements.txt
cp .env.example .env
# fill in .env: GROQ_API_KEY, TAVILY_API_KEY, COMPOSIO_API_KEY
# (all free, no credit card, links in .env.example)

python research_agent.py            # Pass 1: ~100 apps, resumable, ~15-30 min
python composio_toolkit_check.py    # SDK cross-check against live registry
```

Outputs land in `data/`: `results.json` (raw), `results_cleaned.json`
(post-verification), `aggregated_table.json` (category-level patterns),
`composio_crosscheck.json` (SDK cross-check).

---

## Known gaps / honest limitations

- **Fact-check sample is n=10 (10%)**, not the full 100. Directionally useful
  (found real errors the automated pass couldn't), but a larger sample would
  be more statistically defensible.
- **`existing_mcp` in the main table predates the Composio cross-check** — the
  27 false negatives found there aren't yet merged back into the primary
  dataset, they're a separate finding layered on top. A cleaner v2 would fold
  `composio_crosscheck.json` back into the main record set before rendering
  the table.
- **iPayX (#85)** is unverifiable and excluded from stats rather than guessed at.
- The extraction model (`llama-3.1-8b-instant`) is a small model chosen for
  free-tier budget reasons, not maximum capability — occasional misses like
  Ahrefs/Otter/Mermaid CLI are partly attributable to that tradeoff, not just
  bad luck.

---

## Stack

Python · Tavily (search) · Groq (`llama-3.1-8b-instant`, extraction) ·
Composio SDK (toolkit registry cross-check) · static HTML/CSS/JS (no build step)
