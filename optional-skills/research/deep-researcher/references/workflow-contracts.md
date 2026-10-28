# Evidence and completion contracts

These local helpers require Python 3.11+ and no third-party packages. Run them
through `terminal`; use native retrieval and file tools for collection and editing.
SKILL and RUN stand for absolute directories, quoted when they contain spaces.

## Atomic evidence ingestion

Create RUN/batch.json with `write_file`, using this shape:

```json
{
  "batch_id": "round-1",
  "sources": [{
    "key": "dataset",
    "url": "https://example.org/data",
    "title": "Dataset",
    "source_type": "primary",
    "questions": ["Q1"],
    "summary": "Reports growth of 10% in the observed sample.",
    "evidence": [{"excerpt": "Growth in this sample was 10%.", "locator": "Results, paragraph 1"}],
    "limitations": ["Single observed sample; no independent replication."]
  }],
  "claims": [{
    "key": "growth",
    "text": "The observed sample grew by 10%.",
    "question": "Q1",
    "status": "single-source",
    "sources": ["dataset"],
    "evidence": ["dataset:1"],
    "caveat": "Single-origin evidence; independent replication was not established."
  }]
}
```

```sh
python3 SKILL/scripts/evidence_ledger.py add-batch RUN/evidence.json RUN/batch.json
python3 SKILL/scripts/evidence_ledger.py check RUN/evidence.json
python3 SKILL/scripts/evidence_ledger.py brief RUN/evidence.json
```

Save brief output to RUN/evidence-brief.md. The example is synthetic; use only
retrieved evidence for real runs. Keys start with a letter and contain at most
64 letters, digits, underscores, or hyphens. They are unique across committed
records of the same type. Source references use keys; `dataset:1` means the first
passage on that source. The helper assigns numeric source IDs, evidence IDs,
and claim IDs and returns a receipt. Later batches may reference earlier source keys.

Required top-level fields are `batch_id`, `sources`, `claims` (arrays).
Required source fields are `key`, `url`, `title`, `source_type`, `questions`,
`summary`, `evidence`. Optional source fields are `publisher`, `author`,
`published_date`, `accessed_date`, `independence_group`, `independence_note`,
`limitations`, and `extraction_status` (`extracted` or `failed`). Source types are
`primary`, `secondary`, `commentary`, or `community`. Required claim fields are
`key`, `text`, `question`, `status`, `sources`, `evidence`. Optional claim fields
are `counter_sources` (source keys), `importance` (`major` or `minor`), `caveat`,
and `reasoning`. Claim statuses are `supported`, `disputed`, `single-source`, or
`unsupported`. Include passage references for counter-sources as well as supports.

The whole staged ledger is validated before one atomic replacement. An invalid
later claim leaves earlier sources uncommitted. An identical retry of a batch ID
returns its receipt without changing the ledger; a changed payload under the same
ID is rejected. Use a new batch ID and new record keys for new records. Corrections
to existing records use `patch`, followed by validation and a fresh semantic review.
Do not concurrently write the same ledger or manifest from multiple workers;
atomic replacement prevents partial writes, not lost updates between writers.

Independence remains unassessed unless both origin group and explanatory note
are supplied after tracing the original data. Different domains do not establish
independence. An honest single-origin limitation is allowed at completion.

## Semantic review

After the report and brief exist:

```sh
python3 SKILL/scripts/semantic_review.py prepare RUN
```

Read RUN/semantic-review.json with `read_file`. The packet binds exact report and
ledger hashes and includes retained passages and all ledger claims. Heuristics
also flag finality/independence language and potentially unverified named entities.
They are prompts for review, not complete entity recognition or fact checking.
Review the entire report, including names or assertions the heuristic missed.

Use `patch` to fill only these review fields:

- `reviewer`: nonempty reviewer/model identity.
- Each entry under `checks` (`finality`, `independence`, `entities`):
  `status: "checked"` and a specific nonempty `note` explaining the review.
- Every claim/assertion: `status: "verified"` or `"qualified"`, a specific `note`,
  and `evidence_ids` identifying the actual retained support.
- For qualified entries, `qualification`: at least eight characters of explicit
  limitation text that occurs in the report. This must address the actual claim;
  an unrelated disclaimer does not resolve an unsupported assertion.

Verified claims use their own linked passage IDs. Verified finality flags require
an explicit finality label in the selected passage; entity flags require the name
there; independence flags require two explicitly assessed origins. These are
necessary structural conditions, not sufficient proof of semantic support. Read
scope, dates, populations, negations, names, and methods before approving.
Do not relabel preliminary/partial/unknown data as final. Trace organization names
to the source instead of expanding unfamiliar acronyms from model memory.

Do not change hashes, retained evidence, immutable claim/assertion fields, or
coverage to silence failures. If the report or ledger changes, regenerate with
`prepare RUN --replace` and review the new packet. Pending, dropped, tampered,
or stale decisions fail the checker.

```sh
python3 SKILL/scripts/semantic_review.py check RUN
python3 SKILL/scripts/research_run.py checkpoint RUN --status complete
```

Completion requires a nonempty report and brief, a structurally valid nonempty
ledger, summaries for cited sources, linked precise passages for claim sources,
valid report citations, no pending/over-budget recorded searches, and a current
review. Core artifacts are registered automatically. Report and independence
warnings remain visible; they need reasoned review, not fabricated extra sources.
Archiving repeats these gates before writing or pruning anything.

A passing checker records a review attestation. It cannot prove that the reviewer
read carefully, the original passage is authentic, or the conclusion is true.
Legacy ledgers remain readable; old runs need the brief/provenance and current
review before being completed or archived under the stronger contract.
