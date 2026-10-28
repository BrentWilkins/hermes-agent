# Search as code: batched discovery and extraction

Use this when the `execute_code` tool is available. Each round runs as ONE
`execute_code` call: the code fans out every query for the round through the
native `hermes_tools.web_search` / `web_extract` functions, deduplicates and
filters in Python, and prints only the shortlist. Raw snippets and page bodies
never enter the conversation, so a round of 10 queries costs one model turn
and a few hundred tokens of output instead of ten turns of search results.

Rules:

- These are the same native retrieval tools; calling them from code is not a
  bypass. Never call search or extraction services directly (`curl`, vendor
  SDKs, scraping search-engine HTML).
- One `execute_code` call allows at most 50 tool calls. Keep a round to the
  query budget below and extract at most 5 URLs per `web_extract` call.
- Persist the seen-URL set and search log in the run directory so later rounds
  and resumed sessions skip what was already found. Register both files with
  `research_run.py` like any other artifact.
- Printed output is the only thing the model sees. Print compact rows, never
  whole result dicts.

## Round 1: discovery fan-out

Write one query per evidence gap plus deliberate variants: a primary-source
query (official body, filing, dataset, paper), a recency query, and in
standard/deep mode a counter-evidence query for each major theme.

```python
import json, os, re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from hermes_tools import web_search

RUN = "/abs/path/to/RUN"            # the run directory
ROUND = 1
QUERIES = [                          # (gap id, query)
    ("Q1", "..."),
    ("Q1", "... site:gov OR site:europa.eu"),
    ("Q2", "..."),
    ("Q2-counter", "... criticism OR limitations"),
]

TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_src$)")

def canon(url):
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)])
    return urlunsplit((p.scheme.lower() or "https", host, p.path.rstrip("/") or "/", query, ""))

state_path = os.path.join(RUN, "search-state.json")
state = json.load(open(state_path)) if os.path.exists(state_path) else {"seen": {}, "log": []}

fresh = {}
for gap, q in QUERIES:
    try:
        hits = web_search(q, limit=8).get("data", {}).get("web", [])
    except Exception as exc:  # one failed query must not lose the round
        state["log"].append({"round": ROUND, "gap": gap, "query": q, "error": str(exc)[:200]})
        continue
    new = 0
    for h in hits:
        url = canon(h.get("url", ""))
        if not url.startswith("http") or url in state["seen"]:
            continue
        state["seen"][url] = {"round": ROUND, "gap": gap}
        fresh.setdefault(url, {"title": h.get("title", "")[:120],
                               "desc": (h.get("description") or "")[:200], "gaps": set()})
        fresh[url]["gaps"].add(gap)
        new += 1
    state["log"].append({"round": ROUND, "gap": gap, "query": q, "hits": len(hits), "new": new})

json.dump(state, open(state_path, "w"), indent=1)
# Rank: URLs answering several gaps first, then by query order.
rows = sorted(fresh.items(), key=lambda kv: -len(kv[1]["gaps"]))
print(f"round {ROUND}: {len(QUERIES)} queries, {len(rows)} new canonical URLs")
for i, (url, r) in enumerate(rows[:25], 1):
    print(f"{i:>2}. [{','.join(sorted(r['gaps']))}] {r['title']} | {url}\n    {r['desc']}")
```

Read the shortlist, pick the candidates worth extracting (prefer primary and
independent origins), and note queries that returned nothing new: two
consecutive rounds with no new credible canonical URLs end discovery.

## Round 2: extraction with in-code passage selection

```python
import hashlib, json, os, re
from hermes_tools import web_extract

RUN = "/abs/path/to/RUN"
PICKS = {                            # url -> terms that locate the evidence
    "https://example.org/report": ["adoption rate", "2025", "survey"],
}
WINDOW = 2                           # lines of context around each hit

os.makedirs(os.path.join(RUN, "cache"), exist_ok=True)
urls = list(PICKS)
for start in range(0, len(urls), 5):
    batch = urls[start:start + 5]
    for res in web_extract(batch, char_limit=60000).get("results", []):
        url, text = res.get("url", ""), res.get("content") or ""
        if res.get("error") or len(text) < 400:
            print(f"FAILED {url}: {(res.get('error') or 'empty/blocked body')[:120]}")
            continue
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + ".md"
        path = os.path.join(RUN, "cache", name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        lines = text.splitlines()
        terms = [t.lower() for t in PICKS.get(url, [])]
        hits = [i for i, ln in enumerate(lines) if any(t in ln.lower() for t in terms)]
        print(f"\n== {res.get('title', '')[:100]} | {url}\n   cache/{name} ({len(lines)} lines, {len(hits)} term hits)")
        shown = set()
        for i in hits[:6]:
            lo, hi = max(0, i - WINDOW), min(len(lines), i + WINDOW + 1)
            if i in shown:
                continue
            shown.update(range(lo, hi))
            snippet = " ".join(l.strip() for l in lines[lo:hi] if l.strip())[:500]
            print(f"   L{lo + 1}-{hi}: {snippet}")
```

Record each passage you will rely on with `evidence_ledger.py add-source`
using the printed `cache/<file>` line range as the locator, and register the
cache files you keep. Open a cached file with `read_file` only when a passage
needs more context than the window showed.

## Round 3: record a batch through the ledger CLI

Record every source and claim from a round in ONE `execute_code` call that
runs the bundled CLI, instead of one `terminal` call per record. Never write
`evidence.json` by hand: the CLI assigns IDs and validates evidence links.
Source IDs are assigned in order (`[1]`, `[2]`, ...) and a source's evidence
items become `S<id>E1`, `S<id>E2`, ...; read the CLI output to confirm them.

```python
import json, subprocess, sys

SKILL = "/abs/path/to/deep-researcher"
LEDGER = "/abs/path/to/RUN/evidence.json"
CLI = [sys.executable, f"{SKILL}/scripts/evidence_ledger.py"]

SOURCES = [   # each passage keeps the cache file + line range printed in round 2
    {"url": "https://example.org/report", "title": "Report title", "source_type": "primary",
     "question": "Q1", "published_date": "2026-03-25", "summary": "One-line finding",
     "evidence": [{"excerpt": "Exact short passage", "locator": "cache/24738271087b3143.md L28-32"}]},
]
CLAIMS = [    # "evidence" uses IDs from the sources above (S<source id>E<n>)
    {"text": "Narrow claim", "question": "Q1", "status": "single-source",
     "source": "1", "evidence": ["S1E1"], "importance": "major"},
]

def run(args):
    out = subprocess.run(CLI + args, capture_output=True, text=True, encoding="utf-8", check=False)
    print((out.stdout or out.stderr).strip()[:300])
    return out.returncode == 0

for src in SOURCES:
    args = ["add-source", LEDGER, "--url", src["url"], "--title", src["title"],
            "--source-type", src["source_type"], "--question", src["question"],
            "--summary", src.get("summary", ""), "--extraction-status", "extracted"]
    if src.get("published_date"):
        args += ["--published-date", src["published_date"]]
    for item in src.get("evidence", []):
        args += ["--evidence", json.dumps(item)]
    run(args)
for claim in CLAIMS:
    args = ["add-claim", LEDGER, "--text", claim["text"], "--question", claim["question"],
            "--status", claim["status"], "--importance", claim.get("importance", "major")]
    if claim.get("source"):
        args += ["--source", claim["source"]]
    if claim.get("counter_source"):
        args += ["--counter-source", claim["counter_source"]]
    for ev in claim.get("evidence", []):
        args += ["--evidence", ev]
    run(args)
run(["check", LEDGER])
```

Other flags: `add-source --independence-group G --independence-note WHY` (only
after tracing the origin), `--limitation`, `--author`, `--publisher`;
`add-claim --counter-source N`, `--caveat`, `--reasoning`. Statuses:
`supported | disputed | single-source | unsupported`; source types:
`primary | secondary | commentary | community`.

## Parallel sub-question research (deep mode)

When `delegate_task` is available and the question splits into three or more
sub-questions that do not depend on each other, dispatch them in ONE
`delegate_task` call (one task per sub-question) instead of researching them
one after another. Each task's context must carry:

- the sub-question, scope, timeframe and exclusions;
- its query budget (the per-mode budget divided across tasks);
- this file's two code recipes (paste them; children cannot read the parent's
  skill directory unless the path is given);
- the required output: a JSON object
  `{"sources": [{"url", "title", "published", "excerpts": [{"excerpt", "locator"}]}],
  "claims": [{"text", "source_urls", "counter": bool}], "gaps": [...]}`.

Children never write the parent's ledger. The parent is the single writer: it
records returned sources and claims with `evidence_ledger.py`, re-reads the
excerpts behind every decisive claim from the cache or with `web_extract`
before relying on them, and treats a child's independence judgement as
unverified until it traces the origin itself.
