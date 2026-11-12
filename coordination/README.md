# Private task coordination

This Python 3.9+ tool coordinates work in a **private shared filesystem hub**.
It does not collect data, submit jobs, contact participants, certify scientific
evidence, update counts, or turn the website green. Only an independently audited
counts update may change dataset eligibility. A verified triage/metadata/preflight
task certifies its reviewed plan, never the dataset.

## Self-service batches (explicit opt-in)

The coordinator enables the current policy once, after the existing catalogue has
been partitioned into batches of at most 500 records:

```sh
python3 -B coordination/task_manager.py --hub "$HUB" enable-self-service
python3 -B coordination/task_manager.py --hub "$HUB" list --available --category stocks --limit 20 --offset 0
python3 -B coordination/task_manager.py --hub "$HUB" assign TASK --person juan --issue 42 --github-author volunteer
python3 -B coordination/task_manager.py --hub "$HUB" assignment-status TASK
python3 -B coordination/task_manager.py --hub "$HUB" claim TASK --person juan
python3 -B coordination/task_manager.py --hub "$HUB" release-assignment TASK --person juan --github-author volunteer
```

People choose available work. There are no category leads, automatic assignments,
or effort weights in this mode. Historical definitions, hashes, catalogue slices,
and genuine existing worker claims remain unchanged. New proposals may omit
`effort`; it is deprecated and has no operational effect. Admitted work and newly
seeded work have no assignee until reserved or claimed. Splitting and historical
allocation/load helpers are disabled after enablement; finish partitioning first.
The older allocation descriptions below apply only while self-service is off.

A Mac broker validates GitHub issue authors and structured requests, then calls
owner-only `assign` or `release-assignment`. This backend has no credentials,
provider calls or polling. An assignment reserves the task without pretending a
worker has started. `assign` returns exactly `{status, task_id, person, issue}`;
repeating the same person retains the original issue and returns the current
status. Another person conflicts. `assignment-status` returns exactly
`{task_id, status, assignee, assignment_issue}`, a safe reconciliation response
without selectors, scopes or paths. `assignment_issue` is null or a positive
GitHub issue number from the current reservation.

The participant's own Native process runs `claim` and records its actual Unix UID,
asserted roster person and unchanged definition hash in `work-claims/TASK/owner.json`.
An available task or that person's reservation may be claimed. `report` requires
the actual owning UID/person/hash, including for grandfathered legacy claims.
`list --person` filters actual assignments and prioritizes active, blocked,
awaiting-verification, then assigned work. `show`/`list` expose the effective
assignee and original `task_sha256`, omitting historical `lead` and `effort`.
`read-batch` retains the original selectors and bounded reader checks.

Reservations live in coordinator-owned, owner-writable `assignments/` (0755,
records 0644), readable by trusted project users and never published. Each record
binds the raw task hash and keeps the original issue/author, current reservation
and release history. Only its origin author (case-insensitive GitHub login) or
an explicit `--coordinator` release may release a reservation, and only before
any real worker claim exists. The owner-only release receipt has the same four
keys as `assign`, with `status: "available"`. No real claim is removed or reassigned.

`work-claims/` and `task-locks/` are coordinator-owned sticky 1777 directories.
Claim directories are actual-worker-owned 0755, with 0644 records independent of
umask. Assignment, release and claim share the same exclusive per-task `mkdir`
lock. An existing lock is never stolen or automatically retried. Sticky parents
prevent another participant removing a worker's claim or lock. This retains the
trusted-participant identity model described below; it adds no login enrollment.

Migration creates legacy-compatible sentinel claims for every unclaimed leaf:
original assignee/hash, actual coordinator UID, and current UTC claim time in the
old `claims/` path. Their exact IDs are stored in protected `self-service.json`.
Legacy clients therefore cannot claim these tasks; current clients ignore
sentinels as worker ownership. Original batched parent reservations keep the old
validation path. A legacy worker winning the exact atomic-mkdir migration race
is preserved as a real claim. Migration does not rewrite definitions or claims.

Migration starts with a protected `status: "migrating"` record and an exclusive
`.self-service-migration-lock/`. A small fsynced `sentinels.jsonl` journal in that
lock records successfully created sentinel IDs/hashes. Only after all leaves
are reconciled does one atomic write publish `status: "enabled"` and the complete
sentinel list; successful migration then removes its journal/lock. Interruptions
retain state and locks and fail closed for current clients. An interruption
between creating a sentinel and appending its journal entry can leave one
unrecorded directory that must also be inspected. Never delete locks or blindly
repeat an uncertain migration. Manual reconciliation is required; there is no
automatic resume. The mode configuration is cached once per Hub/CLI invocation;
restart long-lived readers after deliberate migration.

Only enabled hubs publish schema 3. Its root has exactly `schema_version`,
`updated_at`, `profile`, `people`, `tasks`, `batch_limit` (500). Each task has exactly
`id`, `category`, `kind`, `status`, `assignee`, `affected_series`, `issues`,
`created_at`, `updated_at`, `parent_id`, `batch_number`, `batch_total`,
`assignment_issue`. Status is `available`, `assigned`, `active`, `blocked`,
`awaiting_verification`, `verified` or `batched`. Only available/batched tasks
have null assignees; batched parents have no person or assignment issue.
Each person has exactly `id`, `name`, `assigned`, `active`,
`awaiting_verification`, `verified`, `remaining_series`. Blocked work counts as
active. Counts include only that person's actual reservations/claims;
`remaining_series` sums unfinished triage leaves, never duplicate parents.
There are no public lead/effort/load fields. The strict validator rejects all
other fields, validates complete parent/batch numbering and recomputes totals.
Schema 1/2 remain unchanged for hubs that have not enabled this policy.

## GitHub request service

The scheduled Mac entry point is `python3 -B -m coordination.claim_service`
with `--config`, `--state` and `--receipt` pointing to private local JSON files.
Its private configuration contains `repo`, `host`, `cli`, `hub` and `publisher`
(an argv list for the existing metadata publisher); optional `gh` selects its CLI.
Do not put tokens or private configuration in this repository. GitHub credentials
come from the Mac's existing authenticated `gh` account.

The service uses a nonblocking local lock, a persistent fair issue cursor and
atomic local terminal receipts written **before** posting/closing GitHub requests.
Successful queue writes additionally retain immutable request outcomes atomically
in the private reservation record. `request-status TASK --issue NUMBER` returns
null or exactly `{task_id, request_issue, action, person, status}`, with
`confirmed` or `released` as the historical result. Reopening a completed request
never repeats its assignment action. Current ownership must still be checked.

Release payloads include the displayed positive `assignment_issue`. The broker
passes `--request-issue` and `--assignment-issue`; the backend checks the original
reservation generation before release. A stale request cannot release a later
reservation. Started work cannot be released. The broker never executes issue
text, runs collection or publishes private reports. Test-labelled integration
requests are ignored by production discovery.

The broker polls once a minute while the maintainer Mac is awake and connected,
then requests a metadata refresh after processed requests. Failed publication is
retained for retry. Worker status changes also use the existing 15-minute sync.
GitHub Pages build latency is separate from the authoritative reservation.

## Legacy allocation policy (self-service off)

The eleven explicitly requested names are the roster: Juan, Emily, Brian, Amir,
Seann, Taha, Saswato, TH, Jion, Vitoria and Olga. Adding a participant does not
rewrite existing task definitions, assignments, claims, category leads or effort. Initial seed creates one
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

## Bounded catalogue review batches

An existing saved `kuina-inspection-v1` manifest supplies dataset `id`, `type`,
`series`, `eligible`, and page references with exactly `path`, `bytes`, `sha256`,
`rows`. Only unclaimed triage parents with a nonwholly eligible dataset are split.
Missing categories (including empty inventory categories) remain original tasks.
Splitting reads manifest metadata, never observations or catalogue page contents.
Before staging or reserving any parent, it checks the declared profile is exactly
900 seconds/two years, the declared ISO window spans at least two calendar years,
and each parent audit epoch matches the manifest when the parent records one.
Every referenced page must already be a regular file of the declared size, at
most 32 MiB, inside the manifest package. Absolute paths, traversal, backslashes
and symlink page components are rejected. These checks use filesystem metadata
without reading catalogue records. The externally verified manifest hash remains
the authority for selecting the intended package and calendar window.
Each page is partitioned into disjoint `[start, stop)` slices of at most 500 saved
catalogue records; mixed pages retain known eligible records in these selectors.

```sh
python3 -B coordination/task_manager.py --hub "$HUB" split --manifest /private/package/manifest.json --assignment balanced --batch-size 500
python3 -B coordination/task_manager.py --hub "$HUB" list --person juan --limit 20 --offset 0
python3 -B coordination/task_manager.py --hub "$HUB" list --all
python3 -B coordination/task_manager.py --hub "$HUB" show TASK
python3 -B coordination/task_manager.py --hub "$HUB" read-batch TASK
```

`--assignment lead` assigns every child to its original parent assignee.
`balanced` greedily selects the person with the fewest outstanding triage leaf
review records, including remaining nonsplit work; ties follow roster order.
Both retain the original category owner as `lead`. A child's effort is
`min(5, ceil(records / 100))`, a planning unit rather than claimed work hours.
`list` defaults to 20 unfinished leaf tasks, prioritizing active, blocked,
awaiting verification, then queued work. `--all` includes parents and verified
tasks and removes the row limit; `--offset` still applies. `show` looks up a
specific task with its private definition, selectors and receipt hash.

Child IDs are `batch-<original-parent-hash-first-24>-000001` and upward. Their
private `batch_spec` pins manifest path and SHA256, dataset ID, complete page
reference and row boundaries. `read-batch` verifies both hashes, page size,
dataset identity and row counts, with a 32 MiB compressed/decoded page bound.
It returns `selected`, `skipped_eligible`, and only `INELIGIBLE` catalogue metadata
records. Its output is private and does not certify eligibility or run an audit.

The protected coordinator stages children and `plan.json` outside live `tasks`
in `batch-plans/.<parent>.incoming/`. After staging, it exclusively reserves the
original parent's persistent `claims/<parent>/owner.json` using actual coordinator
UID, original assignee and original task hash. Only then does atomic rename to
`batch-plans/<parent>/` activate children. Original definitions and real worker
claims remain unchanged. A legacy reader sees the reserved parent as active and
cannot claim it or discover children in root `tasks`. Current readers show it as
`batched` and exclude its duplicate workload. Existing claims are deferred;
exclusive directory creation settles claim races. Incomplete staging or a
reservation without completed activation must be manually reconciled. Never
remove claims or staging and blindly retry an uncertain migration. Repeating a
complete split with the same manifest path/hash, size and policy creates zero
children; changing those pins requires explicit reconciliation.

Snapshots remain schema 1 until an activated batch plan exists. Schema 2 adds
root `batch_limit: 500`; each task adds `lead`, nullable `parent_id`, `batch_number`
(0 on parents/nonbatches), and `batch_total` (0 on unbatched tasks; child count on
parents and children). `batched` is a public parent status. Each person adds
`batched` and `remaining_series`, the sum of unfinished triage leaf records only.
The strict validator checks exact fields, roster totals, category/lead continuity,
parent relationships and complete numbering, with a 20,000-task cap. The public
snapshot never includes private selectors, hashes, paths or catalogue metadata.

Roster rollout: new snapshots include all eleven participants. Readers temporarily
accept the complete historical nine-person roster as well as the complete new
roster; partial rosters are rejected. Assigned people and legacy category leads
must occur in the actual snapshot roster. Vitoria and Olga choose available work
through the same request, reservation, worker-claim and report flow as everyone
else; adding their names performs no allocation.
