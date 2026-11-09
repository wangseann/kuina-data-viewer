# Kuina dataset quality counts

Public, buildless GitHub Pages dashboard. Only code and aggregate quality counts
are published. Observations, data-bearing plot exports and delegation tasks stay
in the private project storage.

The confirmed registry and provisional sentiment signals are separate. Each
numeric field counts as one series; assets/accounts are shown separately.

`docs/summary.json` follows the closed schema in `counts.py`. The builder rejects
unknown fields, non-integer counts, duplicate categories and observation payloads.

Schema 2 adds `issues` to each dataset type: a list of approved reason IDs and
integer counts. Red issues are measured failures; orange issues need verification.
Possible gaps measured on an unverified calendar remain orange. One field can
have several issues, so reason counts overlap. Additional-source variants may
also overlap the confirmed registry. Group/schema failures are counted separately
from fields. Empty numeric slots are excluded from the field counts.

Schema 1 remains readable but explicitly shows when no reason breakdown was
supplied. No arbitrary issue text, series identifiers or observations are accepted.
The reason summary describes the saved audit window, not all current files.

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
