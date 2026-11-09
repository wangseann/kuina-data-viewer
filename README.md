# Kuina dataset quality counts

Public, buildless GitHub Pages dashboard. Only code and aggregate quality counts
are published. Observations, data-bearing plot exports and delegation tasks stay
in the private project storage.

Each numeric field counts as one series; assets/accounts are shown separately.
The full audit counts eligible and excluded fields separately. Missing mandatory
evidence excludes a field even when its observed grid looks complete.

`docs/summary.json` follows the closed schema in `counts.py`. The builder rejects
unknown fields, non-integer counts, duplicate categories and observation payloads.

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
Mac checks the approved counts snapshot daily and pushes changed counts. No SSH
keys or cluster credentials are held in GitHub or GitHub Actions. The Mac must
be available and able to reach the source. Publishing does not run another audit;
if no new verified snapshot exists, the audit date and counts remain unchanged.

To update eligibility, the research workflow must first produce and approve a
new consolidated counts snapshot. This website cannot certify a dataset itself.
