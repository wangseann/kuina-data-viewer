# Private task coordination

This Python 3.9+ tool coordinates work in a **private shared filesystem hub**.
It does not collect data, submit jobs, contact participants, certify scientific
evidence, update counts, or turn the website green. Only an independently audited
counts update may change dataset eligibility. A verified triage/metadata/preflight
task certifies its reviewed plan, never the dataset.

The nine explicitly requested names are the roster. Initial seed creates one
bounded triage task per dataset type, including private aggregate issue totals,
source-failure totals, and source audit/assessment timestamps. IDs are stable by
audit/category; repeating a seed creates nothing. Reassessment does not silently
rewrite existing assigned tasks. Each triage effort is one planning unit, not a
claim about the eventual collection cost. Tasks are allocated deterministically
to the participant with least outstanding effort; ties use roster order. Verified
tasks no longer contribute load. Blocked work remains assigned and contributes load.
An unfinished category triage also blocks a new triage from a later audit; its
definition stays immutable while agents consult the latest counts. After that
triage is verified, a new audit can seed a follow-up for the category.

## CLI

Run from this source tree; `counts.py` supplies the accepted category/reason keys.
`HUB` below is a private, coordinator-owned directory outside the public repository.

```sh
python3 -B coordination/task_manager.py --hub "$HUB" init
python3 -B coordination/task_manager.py --hub "$HUB" seed --summary docs/summary.json
python3 -B coordination/task_manager.py --hub "$HUB" list --person juan
python3 -B coordination/task_manager.py --hub "$HUB" claim TASK --person juan
python3 -B coordination/task_manager.py --hub "$HUB" report TASK --person juan --status in_progress --note 'Private progress'
python3 -B coordination/task_manager.py --hub "$HUB" report TASK --person juan --status blocked --note 'Private blocker'
python3 -B coordination/task_manager.py --hub "$HUB" report TASK --person juan --status completed --note 'Evidence ready for review'
python3 -B coordination/task_manager.py --hub "$HUB" propose --file proposal.json --person juan
python3 -B coordination/task_manager.py --hub "$HUB" admit --proposal PROPOSAL_ID
python3 -B coordination/task_manager.py --hub "$HUB" verify TASK --receipt receipt.json
python3 -B coordination/task_manager.py --hub "$HUB" snapshot --output public-task-status.json
```

`list` is private: it includes task definitions and `task_sha256` for receipts.
Only `snapshot` produces publishable records. Never publish the hub, proposals,
private CLI output, notes, scope, or evidence receipts. Snapshot explicitly exports
schema/version, update time, profile, the authorized roster and aggregate status,
and task ID/category/kind/status/assignee/effort/affected-series/safe reason keys/
creation and update times. It omits scopes, paths, instructions, notes and receipts.
Snapshot does not alter or certify the scientific counts metadata.

## Permission and concurrency model

The filesystem must support atomic `mkdir` and atomic same-directory rename, with
normal Unix ownership and sticky-bit semantics (verify these on the actual shared
mount). The coordinator owns the hub root, `tasks`, and `verified`; these must not
be group/world writable. `init` creates sticky `1777` claims/proposals parents.
Each atomic claim creates a persistent claimant-owned directory, recording actual
Unix UID, participant and exact task hash. Child directories are owner-writable
only and readable to trusted research participants, so the coordinator can review
reports. No symlink records are accepted. No claim is stolen, expired or reassigned.
Coordinator mutations and worker report mutations use exclusive directories;
an interrupted write can leave a lock or incomplete claim that requires explicit
manual reconciliation by the coordinator. Do not blindly delete and retry it.

This is coordination for trusted research participants, not authentication against
a malicious participant or root. `--person` is an asserted roster identity tied to
the actual claiming UID, not an identity provider. Multiple people sharing one UID
do not gain filesystem isolation. Admission and verification must run as hub owner.
Never run untrusted task instructions: this tool stores JSON and never executes it.

## Proposals, deduplication and receipts

Proposals accept exactly `category`, `kind` (`metadata`, `preflight`, `collection`),
`effort` (integer 1–100), `affected_series` (nonnegative integer), `issues` (accepted
reason keys), `scope`, and optional `preflight`. Unexpected top-level/scope fields
are rejected. A scope has exactly these keys:

```json
{
  "provider": "private provider", "instrument": "private instrument",
  "venue": "venue", "feed": "feed", "currency": "GBp", "adjustment": "raw",
  "start": "2024-10-01", "end": "2026-10-01", "native_interval_seconds": 900,
  "native_resolution": "verified native resolution requirement",
  "history": "history requirement", "coverage": "coverage requirement",
  "meaning": "variable definition", "budgets": "reviewed resource policy"
}
```

Windows are closed-open ISO dates. Identity fields may be null for metadata
investigation; null conservatively matches any value. Known identities compare
exactly, including currency case (`GBP` and `GBp` remain distinct). Admission
rejects overlapping resource/windows held by any unfinished task, irrespective of
category, warning or numerical field. A verified collection also blocks redundant
same-scope work; a verified noncollection plan permits its next scoped stage.
Identical proposals remain idempotent and never overwrite earlier tasks. It never
silently reassigns a task. Adjacent windows are distinct.

Collection requires a complete known identity, at least two calendar years, and
native intervals no coarser than 900 seconds. Its `preflight` object must have
`kind: "preflight"`, `verified: true`, `scope_sha256` (canonical `digest(scope)`),
nonempty private `evidence`, timezone-aware `verified_at`, and `checks` with literal
`true` for all of `native_resolution`, `history`, `coverage`, `meaning`, `budgets`.
The scope hash binds every requirement and exact window. This is a receipt of a
coordinator's external review, not proof that a JSON boolean validates evidence.
The coordinator must inspect and approve the referenced preflight before admission.

All completion reports enter `awaiting_verification`. A noncollection receipt has
`kind: "plan"`, `verified: true`, `task_sha256`, nonempty private `evidence`, and
`verified_at` after completion (and no later than now). Collection receipts instead
have `kind: "audit"` and additionally require `scope_sha256`, `source_identity`
(exact six identity fields), `window` (exact `start`/`end`), exact configured
`native_interval_seconds` <=900, integer `unexplained_gaps: 0`, `eligible: true`,
and `audited_at` after completion and no later than verification. The window must
span two calendar years; February 29 anniversaries use February 28. Only the
coordinator may persist a verification receipt. The coordinator is responsible for
actually checking external audit evidence; the tool validates its structure,
identity, timing and acceptance profile and never runs or fabricates an audit.

Run the focused checks with:

```sh
python3 -B -m unittest discover -s tests -p test_task_manager.py -v
```
