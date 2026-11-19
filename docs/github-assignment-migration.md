# Read-only Native migration export

`coordination.github_migration.export(private_catalogue)` produces one closed
`kuina-github-migration-export-v1` envelope containing `catalogue`, `migration`,
`summary` and count/hash-only `provenance`. `encode(envelope)` returns compact JSON
and gzip bytes, bounded to 8 MiB and 1 MiB respectively. Neither call writes a file
or contacts GitHub. Execution belongs to the reviewed coordinator operator.

Before export, the coordinator must fence every referenced legacy leaf and every
additional current legacy reservation/worker with the matching generation and
definition. The exporter refuses missing or unknown fences. Old unique mutable
parents must either all remain absent or have the recognized authority freeze;
any old unique claim or assignment file requires explicit reconciliation.

The exporter reads the full immutable queue membership and censuses every Native
claim, work-claim, assignment, verification and task-lock entry. Original batched
parents and validated self-service sentinels are excluded from worker counts.
Current workers retain their actual participant, status and source timestamps;
an opaque owner-file hash replaces private owner details. Each reservation must
have zero history and exactly its original confirmed assignment receipt. Other
history, missing receipts, unknown journals, unbound definitions or reused issues
block export. In the five known Native namespaces, an exact coordinator-owned
regular `.keep` file with mode `0644` and zero bytes is preserved and excluded
from task counts. Unexpected marker contents, types, ownership or changes block
the export.

Every imported row is permanently protected with `origin=migration`. Original
legacy IDs and definition hashes are appended as disabled `legacy_definitions`
in the public catalogue. Explicit V2 imported continuation preserves the original
reservation and all fences; ordinary assignment/release cannot alter it.

The queue's protected publication record supplies the closed summary, bound to
the same manifest generation. The source digest commits to actual private
metadata content hashes, definition hashes and file/directory identity epochs.
Private paths, UID values, report text, target memberships and observations are
never emitted. Strict final live-epoch checks reject concurrent claim, report,
reservation, verification, fence or unknown-lock changes. A subsequent export
starts a new epoch. Missing Native folders are never recreated.
