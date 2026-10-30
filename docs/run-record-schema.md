# Run records, schema 1

A run record is what a checker that runs **outside** Semantext says about one rule: that it ran the rule's
must-pass and must-refuse cases against some files, and how many passed. Semantext reads records and judges them; it
never re-runs anything. A valid, fresh record is the one thing that makes a rule *guarded* on the page.

The machine-readable form is [`semantext/schemas/run-record-1.json`](../semantext/schemas/run-record-1.json) (JSON
Schema, draft 2020-12), shipped in the wheel. **A checker reads that file, never imports the package.** Semantext
validates records by hand, in `semantext/sources/runs.py`; where this page and that code differ, the code is right
and this page is a bug.

## Where records are kept

The person lists folders in their sources file:

```json
"run_records": ["C:\\work\\checks"],
"run_record_days": 30
```

Each record is one line of `runs/<checker>.jsonl` under a listed folder. A checker appends one record per run. A
listed folder must be a full path on this machine (not a network or device path), must exist, and must not be in a
closed place; the `runs` folder and each `.jsonl` file in it must not be a link or a junction. Each is otherwise a
problem, said, and not read.

`run_record_days` is the age bound in days, a whole number over 0; 30 when it is not given.

## One record

```json
{"schema": 1,
 "checker": {"name": "my-checker", "version": "1.0.0", "sha256": "<64 hex>"},
 "rule": {"id": "R1", "sha256": "<64 hex>"},
 "subject": [{"path": "src/app.py", "blob": "<40 or 64 hex>"}],
 "arms": {"must_pass": {"ran": 3, "passed": 3, "how": "pytest -k r1_pass"},
          "must_refuse": {"ran": 2, "refused": 2}},
 "at": "2026-10-23T21:00:00Z",
 "by": "ci", "note": "nightly", "findings": [], "outcome": "clean"}
```

| Field | Required | What it must be |
| --- | --- | --- |
| `schema` | yes | `1`, the number (not `true`, not `"1"`) |
| `checker.name` | yes | plain text: printable characters only, no space at either end, 1 to 100 characters |
| `checker.version` | yes | plain text, as the name |
| `checker.sha256` | no | 64 lowercase hex: the SHA-256 of the checker's own entry file. Shown, never judged |
| `rule.id` | yes | the rule's id as its card gives it (runs of spaces are read as one) |
| `rule.sha256` | yes | 64 lowercase hex: SHA-256 of the UTF-8 bytes of the rule's statement as the card shows it, every run of whitespace joined into one space and the ends trimmed |
| `subject` | yes | a list of at least one `{path, blob}` |
| `subject[].path` | yes | the file checked, relative to the listed folder the record lies under; an absolute path must lie inside a listed folder |
| `subject[].blob` | yes | the git blob id of the bytes checked: SHA-1 (40 hex) or SHA-256 (64 hex) of `blob <length>\0` followed by the bytes |
| `arms.must_pass` | yes | `{ran, passed}`, whole numbers, `ran` at least 1, `passed` no more than `ran`; optional `how`, text |
| `arms.must_refuse` | yes | `{ran, refused}`, as must_pass |
| `at` | yes | when the run finished, UTC, written `YYYY-MM-DDTHH:MM:SSZ` in ASCII digits (`0`-`9`; no other script's digits), with up to six digits of fraction before the `Z` |
| `by`, `built_by`, `note` | no | text: who started the run, who built the checker, a free note. Shown as text. `built_by` is not named in the JSON schema, which allows other properties |
| `findings` | no | a list of short texts the counts cannot carry |
| `outcome` | no | the record's own word for its run: `clean`, `with findings`, `failed` or `not proved` |
| `summary` | no | counts by status and class; shown at most, decides nothing |
| `detail` | no | the cases themselves (below) |

Any other field is allowed and decides nothing.

### detail

When `detail` lists the cases, the counts in `arms` must agree with it, or the record is refused:

- `detail.arms`, a list of cases each with a `class` (`must_pass` or `must_refuse`; other classes are not counted) and
  a `status`: the cases of each class whose status is not `"not-run"` must number that arm's `ran`, and those with
  status `"passed"` must number its `passed` (or `refused`). A case whose status is `"warned-open"` (a warning, with
  the violation let through) ran and was not refused.
- `detail.must_pass` or `detail.must_refuse`, a list of cases: its length must equal that arm's `ran`, and when every
  case carries a boolean `ok`, the number of true ones must equal `passed` (or `refused`).

## What a record earns

For each (rule, checker) pair the **newest** usable record decides (by `at`, then by the order the lines were read).
It earns the rule one of three states, and nothing more:

| State | When |
| --- | --- |
| **guarded** | both arms ran and every case passed (`passed == ran`, `refused == ran`), the outcome is not `failed` or `not proved`, the rule's words hash to `rule.sha256` now, every subject's blob is the git blob id of the bytes in place now, and `at` is within the age bound |
| **stale** (shown as "guarded once") | the same record, but the rule's words, a subject's bytes (changed, gone, not a file, over 64 MiB, or unreadable) or the age no longer hold; it says which |
| **failed** | a well-formed record whose arms did not all pass, or whose own `outcome` is `failed` or `not proved`, whatever its counts say. It earns nothing, and the page says so |

**A record's findings never change its level, and are never hidden behind a passing count**: the page shows "guarded,
with N findings" and each finding as text (at most 100, each cut to 300 characters).

## What refuses a record

Each refused line is a problem with its kind and reason, never dropped:

| Kind | Why |
| --- | --- |
| `too-long` | the line is over 64 KB |
| `not-json` | the line is not JSON (`NaN` and `Infinity` are not JSON) |
| `too-deep` | it is nested deeper than Semantext's JSON reader allows |
| `not-a-record` | it is not a JSON object |
| `no-schema`, `wrong-schema` | it names no schema, or one that is not 1 |
| `bad-checker-name` | the checker's name is not plain text |
| `bad-field` | a required section or field is missing or of the wrong shape, or a count is more than `ran` |
| `arm-not-run` | an arm ran 0 cases, so it shows nothing |
| `detail-disagrees` | `detail` lists cases that do not agree with the counts |
| `bad-findings` | `findings` is not a list of texts |
| `bad-outcome` | `outcome` is not one of the four known words |
| `bad-time` | `at` is not a UTC time in the form above, or not a real time |
| `future-time` | `at` is more than two minutes after the reader's clock |
| `outside-roots` | a subject lies outside every listed folder, or is a network or device path |
| `closed-place` | a subject is in a place the person closed |

## What a record is not

A record is what the checker says. Its shape is checked, and its freshness against the bytes in place now, and nothing
about whether the checker is honest. Files are opened for reading only; nothing is started. A list of what *should*
have a record (the guards file) is not a record, and makes no rule guarded.
