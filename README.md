# Kuina dataset quality counts

Public, buildless GitHub Pages dashboard. Code, aggregate quality counts, and an
approved sample of series names, field labels, public source labels and native
intervals are published. The user also authorized the eleven volunteer names (including Vitoria and Olga) and a sanitized
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
uses larger squares that wrap to the available window width. Hover over a square
to read its actual series name, field, public source, native interval and failure
combination. Names are loaded only after their complete closed-schema snapshot
matches the counts digest, audit dates, visible tile quotas and every failure
mask. Missing, stale or invalid names leave the counts and colours available
without assigning a guessed name. The named sample is bounded to 20,000 eligible
and 4,000 excluded squares per dataset type; its JSON download is capped at 32 MiB.
No observed values, timestamp arrays, private paths or private catalogue pages
are included. Each failure reason
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
its checks; the public hover index contains opaque identifiers for matching approved named tiles.

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

`docs/tasks.html` shows available batches, confirmed assignees and filterable
progress. Choose your name explicitly, select an available batch and submit its
prepared GitHub claim issue. The Mac broker validates the request, atomically
reserves the task in the private Native hub and records its result on GitHub.
Requests stay pending until confirmed; selecting a name or opening a link does
not reserve work. There are no dataset leads, effort weights or automatic
assignments in self-service mode.

The participant's own agent then creates the actual persistent worker claim using
the private shared-filesystem CLI in [coordination/README.md](coordination/README.md)
and the hub's `AGENT_TASKS.md`. A reservation is distinct from a worker claim.
Only your own unstarted assignment offers a release request, bound to its current
GitHub assignment issue so an old request cannot release a later reservation.
No participant's agent is installed or run by the website. Source/window overlap
checks prevent duplicate repairs. Completion waits for coordinator verification;
collection repairs require a fresh matching eligibility audit.

Review batches contain at most 500 saved catalogue records. Private selectors pin
the source manifest, page hash and disjoint row ranges. Already-eligible records
in mixed pages are skipped by `read-batch`. Shared findings can be reused across
batches. Source groups with unknown series counts remain separate inventory work.

The public board shows 40 jobs per page, dataset availability and actual assigned
review counts. Its closed schema 3 accepts at most 20,000 tasks and 16 MiB of
status metadata, with no source selectors, observed values, leads, effort or load.
Schemas 1/2 remain readable during transition and expose no claim links. Batched
parents stay unassigned coordination records. Protected legacy sentinels prevent
old clients bypassing the new policy; real existing worker claims are preserved.

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

`series_names.py` exports the displayed named sample from a pinned existing
`kuina-inspection-v1` catalogue. It streams saved audit metadata, verifies every
page hash and all category/failure-mask totals, and copies only the closed public
display fields. It never opens source observations or changes eligibility. Run it
through the approved research execution route; the CLI requires a fresh output
directory and explicit catalogue SHA256. Validate the resulting name index against
the matching counts before publishing it as `docs/series-names.json`. New audit
counts require a matching name export; until then the browser disables stale names
instead of guessing their correspondence. The counts publisher cannot generate
new names from aggregate counts alone.
