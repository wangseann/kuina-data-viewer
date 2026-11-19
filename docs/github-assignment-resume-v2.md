# Protected imported reservation continuation

The versioned `coordination.github_assignments_v2.Assignments` subclasses the
frozen V1 authority. Its ledger schema and normal assign, release and working
operations remain unchanged. Integration must explicitly import V2.

`resume_imported(batch_id, person, assignment_issue, proof_sha256, author,
request_issue)` starts only the original, unstarted `origin=migration`
reservation. The stored person, original GitHub author and assignment issue must
match; the frozen catalogue definition and generation must match even when
`assignment_enabled` is false. Missing original author or issue blocks a start.
All legacy fences remain in place.

The private callback is invoked as
`guard(batch_id, 'working', current_assignment, requested_proof_sha256)`. It must
verify the unchanged Native reservation and original definition, a private
preparation token bound to this person/assignment/generation, and absence of an
existing worker or unknown lock. Only `state=clear` with exactly the requested
proof hash permits the CAS. Missing or uncertain evidence blocks it.

One Contents-API CAS retains the imported reservation and changes its status to
active, records the opaque work proof and start issue, and embeds an immutable
working receipt. No private execution permit or worker claim may precede an
observed matching receipt and active record. A repeated exact start issue
reconciles that receipt before protected-status and private-proof checks; changed
bindings are rejected. A started import remains protected if its private token
later disappears. It cannot be released, reassigned or made available.

The private legacy bridge then issues a separate protected permit and writes the
original four-key Native worker record for the original UID. It does not call
through or remove a legacy fence. Existing workers continue their original report
interface. This module does not write Native files or contact a provider.
