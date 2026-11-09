# Public counts-only website

Publish only viewer source and the strict counts metadata accepted by counts.py.
Never commit dataset observations, data-bearing HTML exports, timestamp arrays,
credentials, participant lists or delegation tasks. The private Kuina hub owns
collection/delegation; this repository does not run collection or scientific audits.

Historical snapshots treated 129 derived sentiment signals as provisional.
New snapshots must pass the full mandatory checks; a complete derived grid alone
does not certify scrape completeness or historical feature availability.
Do not sum overlapping audit scopes or promote data because files appeared.
Keep the actual audit date; a publish/sync time is not a new scientific audit.

Run `python3 -B -m unittest discover -s tests -v` before publication.
