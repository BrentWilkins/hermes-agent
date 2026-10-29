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

## Semantic review without repeated full-packet reads

After drafting the report and saving its brief, run through `terminal`:

```sh
python3 SKILL/scripts/semantic_review.py prepare RUN
python3 SKILL/scripts/semantic_review.py show RUN
python3 SKILL/scripts/semantic_review.py show RUN --ids C001 --evidence S1E1 --max-chars 12000
```

`prepare` stores the full hash-bound packet on disk and prints a compact pending
view. `show` returns current hashes, checklist state, pending IDs and short report
contexts. Selecting item IDs shows their linked passages; `--evidence` selects
additional passage IDs. Output omissions and excerpt clipping are explicit; the
stored evidence is unchanged. Increase `--max-chars` or select relevant IDs to
inspect omitted material. Do not treat clipped passages as complete evidence.
Read the original retrieved text when needed. Do not repeatedly read the whole
packet or inspect helper source code to discover how to fill it.

Review every material ledger claim and the complete report. Heuristic name and
word flags are read-only warnings for the four-category audit; they are not
individual tasks and never require a source quote for a label or boilerplate.
Resolve actual factual issues, not formatting flags. The heuristics are prompts,
not complete entity recognition or fact checking. Date
labels are filtered; named organizations and unknown acronyms still need review.
Repeated same-line names share one warning; distinct lines retain distinct
contexts. Report headings, code fences and references are not scanned as claims.

Run `semantic_review.py template RUN` to write RUN/review-decisions.json with the
current hashes, claim IDs, linked passage IDs and current claim decisions. It approves nothing.
Edit the file with native `patch`; do not invent field names or build update code.
Blank pending template entries are left pending by `apply`; completion still
requires a decision for each ledger claim and all four checks. Warnings have no decision fields. Existing templates are never
replaced without `--replace`; report, ledger and registered artifacts are protected.
This synthetic example illustrates the format, not an automatic approval:

```json
{
  "report_sha256": "HASH_FROM_SHOW",
  "ledger_sha256": "HASH_FROM_SHOW",
  "reviewer": "Actual reviewer or model identity",
  "checks": {
    "finality": {"status": "checked", "note": "Explain the final/preliminary/unknown assessment."},
    "independence": {"status": "checked", "note": "Explain traced origins and disclosed limits."},
    "entities": {"status": "checked", "note": "Explain names and acronym verification."},
    "numbers": {"status": "checked", "note": "Explain scope, units and numerical comparison checks."}
  },
  "claims": [{
    "id": "C001",
    "status": "verified",
    "evidence_ids": ["S1E1"],
    "note": "Explain exactly how these passages support this claim.",
    "scope_note": "For numeric claims: period, population/geography, units, denominator and comparison. State unspecified dimensions honestly."
  }]
}
```

```sh
python3 SKILL/scripts/semantic_review.py apply RUN RUN/review-decisions.json
python3 SKILL/scripts/semantic_review.py check RUN
```

Decisions may be partial; `apply` validates all supplied changes, saves them
atomically or saves nothing, and reports remaining work. Repeat for unresolved
IDs. Never generate blanket approvals or custom Python update loops. Reviewer
and check decisions remain explicit; neither prepare nor apply approves anything.
An identical valid retry does not duplicate items. Unknown IDs, altered source
material, stale hashes and unsupported decisions fail before saving.

`check` reports all unresolved items together with IDs and correction guidance.
Use `show --ids ID` to inspect the relevant evidence, then correct the report or
ledger with `patch`. After either artifact changes, run `prepare RUN --replace`
and review the current packet. All earlier decisions become pending: no silent
approval reuse across changed source material. Editing only review decisions does
not require preparing again.

### Correct substantive issues instead of satisfying a checker

Verified claims use their linked passages. Finality labels require explicit
source support; "new annual release" does not establish "final". If unsupported,
remove that label, or visibly state `Final status is unverified` in the same
report paragraph. A qualification must express the actual limitation; repeating
`Final EHPA figures` or supplying an unrelated single-origin caveat is rejected.
Use the entity checklist to trace material names, omit unsupported names, or
label them honestly in the report. A heuristic warning alone does not block
completion. Independence limitations can be disclosed globally, for example
`Single-origin evidence; independent corroboration was not established.`

For a qualified decision supply `status: "qualified"`, `note`, `evidence_ids`
(which may be empty), and `qualification`: the exact explicit limitation in the
report. Correct the report before preparing a new packet. Qualified does not
mean permission to leave unqualified certainty elsewhere in the report.

Every numeric claim also requires a `scope_note`. Keep each measured quantity
bound to its population, period, geography and units. Separate incompatible
series into distinct claims. Do not attach a 16-country baseline to a 21-country
growth rate, or describe a European percentage as a national result. Check
arithmetic and denominator consistency. Where scope is absent, state it as
unknown rather than inventing it. These notes are reviewer attestations, not an
automatic numerical or semantic proof.

Verified independence assertions require two explicitly assessed origins. A
single-origin report may finish with honest, visible limitations. Different
publishers repeating the same dataset do not supply independent corroboration.

### Completion

```sh
python3 SKILL/scripts/research_run.py checkpoint RUN --status complete
```

Completion requires a nonempty report and brief, a valid nonempty ledger,
cited-source summaries, precise linked passages for claim sources, valid
citations, no pending/over-budget searches, and a current complete review.
Archiving repeats these gates before writing or pruning anything. Review all
remaining warnings and substantive findings; do not end corrections early.

A passing checker records an attestation. It cannot prove passage authenticity,
careful reading, correct scope or factual truth. Legacy ledgers remain readable;
old review packets need `prepare --replace` under this version before completion.
URL matching is shared with the ledger: document/version query parameters,
including `ref` and `source`, remain significant; recognized tracking parameters
are removed. Retrieval always uses the supplied URL. References belong last in
the report. A bracketed calendar year is prose unless explicitly defined as a
bibliography number; ordinary citation groups and ranges remain citations.
Individual `add-claim` writes now validate the staged ledger before saving, just
as `add-batch` does. Failed additions leave the ledger and assigned IDs unchanged.
