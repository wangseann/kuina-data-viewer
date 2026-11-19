# Confirmed assignment authority

GitHub stores permanent confirmed reservations in one Contents API file. Kuina
keeps observations, worker identities and proofs, collection context, reports and
scientific decisions private. Nothing in this ledger certifies data eligibility
or completes a repair task.

`coordination.github_assignments.Assignments(github, catalogue, private_guard,
path='coordination/assignments.json', branch='main')` reuses `GitHub.api`.
`requires_receipt = True` tells the broker to forbid confirmation based only on
an assignee. Each request must have its exact observed issue receipt.

The single ledger has exactly `schema` (`kuina-github-assignments-v1`),
`migration`, `assignments` and `receipts`. Both maps are sparse. Assignments are
keyed by batch ID; immutable receipts are keyed by decimal issue number.
Assignment and receipt are committed together with one file-SHA PUT. A follow-up
GET must observe the exact receipt before confirmation. A lost acknowledgement
uses that GET, never an unqualified repeated write. Only definite CAS conflicts
retry, at most three attempts by default (maximum five).

The decoded payload is capped at 512 KiB. Capacity exhaustion stops writes;
history is never expired, discarded, compacted or silently overwritten. This
bound stays inside GitHub's base64 Contents API support for small files. See
[GitHub's Contents API contract](https://docs.github.com/en/rest/repos/contents).
Only this adapter should update the authority file; ordinary repository access
controls remain responsible for preventing unrelated manual edits.

## Integration contracts

Catalogue is a read-only callback with one frozen generation:

```python
catalogue(batch_id) -> {
    'schema': 'kuina-assignment-catalogue-v1',
    'batch_id': batch_id,
    'generation': '<64 lowercase hex>',
    'definition_sha256': '<64 lowercase hex>',
    'assignment_enabled': True,  # real assignment blockers, not scientific warnings
}
```

The callback is rechecked before mutation. Existing assignments retain their
original generation and definition hash. A changed definition cannot be silently
borrowed by a release or start. Imported legacy IDs also need catalogue entries;
those entries normally have `assignment_enabled=False`.

Root's private coordinator supplies the sanitized guard callback:

```python
private_guard(batch_id, action, assignment, proof_sha256=None) -> {
    'schema': 'kuina-assignment-guard-v1',
    'state': 'clear',  # clear | working | blocked | unknown
    'proof_sha256': '<64 lowercase hex>',  # null only for non-clear evidence
}
```

`action` is `assign`, `release` or `working`. `assignment` is the closed public
record or `None`. The fourth argument is always supplied: `None` for assignment
and release, the exact requested token SHA for working. Working requires that
same SHA back and state `clear` or `working`. Assignment/release require `clear`
and a proof hash. Unknown, absent or malformed private evidence fails closed.
The adapter itself performs no private writes; root owns private fence/proof
installation and verification. No private paths or UID metadata belong in the
callback response.

Workers must commit and observe GitHub working state **before** acquiring the
private work claim. If private start subsequently fails, the GitHub working
reservation remains protected until explicit coordinator reconciliation. A
read-only check alone cannot make release atomic with an unrelated legacy
writer; deployment must fence legacy starts and route new starts through this
protocol. Started or imported records cannot be released by this API.

## Public metadata schemas

Every assignment record has exactly:

- `batch_id`, `person`, `author`, `assignment_issue`, `status`
- `definition_sha256`, `catalogue_generation`, `created_at`, `updated_at`
- `origin` (`github` or `migration`), `work_proof_sha256`, `working_request_issue`

`person` is one of the existing eleven participants. `author` is a GitHub login.
Migration may use null author, issue, proof and working issue; an unknown person
may be null only in protected migration records. Status is `assigned`, `active`,
`blocked`, `awaiting_verification` or `verified`. New GitHub records are assigned
or active. No status expires. Imported assigned records display as blocked until
explicit reconciliation; imported started work stays active even without
private proof.

Every receipt has exactly `request_issue`, `batch_id`, `action`, `person`,
`author`, `assignment_issue`, `proof_sha256`, `status`, `recorded_at`,
`definition_sha256`, `catalogue_generation` and `origin`. Actions are assign,
release and working; outcomes are confirmed, released, started or rejected as
appropriate. Assign uses null assignment/proof references; release binds the
original assignment issue; working binds that issue and the requested proof.
Actor/action/person/batch/proof changes under a reused issue are rejected.

Initialization is explicit and cannot replace existing authority:

```python
store.initialize({
    'schema': 'kuina-assignment-migration-v1', 'complete': True,
    'source_sha256': '<sanitized reviewed migration hash>',
    'catalogue_generation': '<64 lowercase hex>',
    'records': [],  # complete protected legacy/current records, full schema above
    'receipts': [], # known sanitized history, full schema above
})
```

Each imported item has `origin='migration'`; original hashes, times, reservations
and history are retained. An incomplete migration is rejected. Missing ledger
never creates an empty available queue. The migration must account for every
current legacy and old unique claim/reservation before it asserts completeness.

## Methods used by the broker and worker protocol

- `status(batch_id)` returns the existing four-field native status shape.
- `assign(batch_id, person, issue, author)` and
  `release(batch_id, person, author, issue, assignment_issue, coordinator=False)`
  return the five-field observed issue status. Only the original requester or
  the actual repository owner with coordinator flag may release; stale issue
  references cannot release a later reservation.
- `request_status(batch_id, issue, *, action=None, person=None, author=None,
  assignment_issue=None, proof_sha256=None)` retains the five-field shape.
  The broker should supply request binding arguments. `request_receipt` exposes
  the complete closed receipt for audit/integration.
- `set_working(batch_id, person, assignment_issue, proof_sha256, *, author=None,
  request_issue=None)` commits the protected marker. Supplying both optional
  arguments creates the immutable structured-start receipt atomically and records
  `working_request_issue`. A trusted internal call without either returns only
  the observed native status; it does not invent a GitHub request receipt.
- `snapshot()` returns `{ledger_sha, ledger}` from one validated GET. Publishers
  can read this once rather than fetching per row. Mutations never use a cached
  snapshot.

GitHub file SHA is verified against the actual Git blob content. All ledger
objects reject unknown keys, including arbitrary reports, private paths, UIDs,
context and observations. Transport or guard errors use fixed public-safe errors;
private diagnostics must remain in private coordinator logs.
