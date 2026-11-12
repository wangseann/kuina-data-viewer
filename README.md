# Kuina dataset quality counts

Public, buildless GitHub Pages dashboard. Only code and aggregate quality counts
are published. The user also authorized the nine volunteer names and a sanitized
task-status board. Observations, data-bearing plot exports, collection scopes and
agent reports stay in private project storage.

Each numeric field counts as one series; assets/accounts are shown separately.
The full audit counts eligible and excluded fields separately. Missing mandatory
evidence excludes a field even when its observed grid looks complete.

`docs/summary.json` follows the closed schema in `counts.py`. The builder rejects
unknown fields, non-integer counts, duplicate categories and observation payloads.

Schema 4 adds the current strict profile: regular series require native intervals
of 15 minutes or finer and at least two years of valid history. It records the
original source-audit timestamp separately from the metadata reassessment time.
Blue identifies measured missing data/gaps, orange identifies coarse resolution,
purple identifies short history, and grey identifies other failures or missing
proof. A striped square retains every applicable failure colour. Each excluded
series occupies exactly one failure-combination bucket; overlapping reason
counts must never be summed as if they were distinct series. Large grids display
a labelled sample while the tables retain the exact counts. The current viewer
uses larger squares that wrap to the available window width. Each failure reason
has a plain-English explanation, including why missing proof prevents a pass.

The shared `failure_codes.py` is a metadata-only policy helper; this repository
does not read observations or acquire data. The private research workflow
reassesses the already measured audit records and provides the aggregate snapshot.

Schema 3 represents the complete audited inventory. All excluded fields are red,
with aggregate counts for each failed requirement. Measured failures and
evidence-only exclusions sum to the excluded total. Reason counts can overlap.
Unreadable sources or groups without a validated time/value table are counted
separately; their unknown series counts are never estimated. Duplicate versions
do not add series, while distinct sources, quote variants and native intervals
remain separate. The private Kuina report lists each identified series and all
its checks; this public site contains no series identifiers.

Schemas 1 and 2 remain readable for historical snapshots. Their provisional
sentiment and overlapping additional-source counts must not be added to the
new full-audit totals. No arbitrary issue text or observations are accepted.
The audit timestamp identifies the actual checks, not the publication time.

Build from an explicitly approved counts snapshot:

```sh
python3 -B counts.py --input approved-counts.json --out docs
python3 -B -m unittest discover -s tests -v
```

GitHub Pages publishes `docs/` on `main`. A private publisher on the maintainer's
Mac checks approved counts and shared task status every 15 minutes and pushes
changed metadata (with a daily status heartbeat). No SSH
keys or cluster credentials are held in GitHub or GitHub Actions. The Mac must
be available and able to reach the source. Publishing does not run another audit;
if no new verified snapshot exists, the audit date and counts remain unchanged.

To update eligibility, the research workflow must first produce and approve a
new consolidated counts snapshot. This website cannot certify a dataset itself.

The code-only `docs/explorer.html` adds private dataset/source selection, paged
series lists, daily coverage heatmaps, selected-series charts and repair-brief
exports. It reads a user-selected private inspection folder in the browser;
its CSP blocks network connections. No observations or populated private
catalogues belong in this repository. Historical HTML payloads can be imported
as data, without executing the selected HTML or trusting its old pass labels.

`docs/tasks.html` shows dataset leads, bounded review batches and filterable progress. The static
website cannot claim tasks. Agents use the private shared-filesystem CLI described
in [coordination/README.md](coordination/README.md) and the private hub's
`AGENT_TASKS.md`. Exclusive persistent claims prevent duplicate work; source and
window overlap checks combine warnings for the same repair. Completion waits for
coordinator verification, and collection repairs need a fresh matching eligibility
audit. No participant's agent is installed or run by this website.

Review batches contain at most 500 saved catalogue records. Original dataset
leads remain responsible for shared decisions; batches can be distributed by
outstanding record count across the team. Private selectors pin the source
manifest, page hash and disjoint row ranges. Already-eligible records in mixed
pages are skipped when agents read a batch. Source groups with unknown series
counts remain separate inventory work, visible in the quality counts.

The public board shows 40 jobs at a time, distinguishes lead from assignee, and
counts review records rather than treating every category as one unit of work.
Its closed schema accepts at most 20,000 tasks and 16 MiB of status metadata.
It contains no source selectors or observed values. Earlier queued parent jobs
are retained as coordination records; persistent reservations prevent older
clients from claiming them after subdivision. Existing worker claims are kept.

The series inspector preserves known field meanings and shows the outcome of each
warning review, including what existing information was checked and what remains
unresolved. Catalogues without measured previews do not imply known daily gaps;
their chart and coverage availability is explicitly shown.

A new private package uses `kuina-inspection-v1`, with hash-pinned gzip catalogue
pages and separate lazy preview pages. The source audit date, assessment date,
15-minute interval and two-year window are explicit. Unknown daily coverage is
grey; endpoint dates alone never imply complete coverage. The catalogue generator
and observation-preview pipeline run under the research project's execution
rules. An empty viewer is not evidence that the complete catalogue was generated.
