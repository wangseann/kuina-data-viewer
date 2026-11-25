# Free-source collection jobs

Use **Find new data → Confirmed free-source jobs** on the dashboard. Jobs are
provider-wide, so several sectors from the same provider share one owner.

1. Choose your participant name and submit **Claim via GitHub**. Wait for the
   confirmation; opening the form does not reserve anything.
2. Give your agent **Copy agent instructions**. It must read the private hub's
   `AGENT_TASKS.md` to set `KUINA_TASK_MANAGER` and `KUINA_TASK_HUB`, then use its
   own approved cluster account. Resume existing work first.
3. For a reserved job, run `prepare-work`, submit its returned GitHub start form,
   wait for confirmation, and run the copied `claim --proof-sha256` command.
   Only that Native UID creates the actual worker. Stop on a failed claim.
4. Read the exact private job with `read-batch`. Inspect existing data first.
   Verify two years of actual history, native intervals of 15 minutes or finer,
   instrument meaning and expected-calendar gaps. An archive index alone is
   insufficient. Missing qualification evidence means blocked, not permission
   to bulk-download prices.
5. Follow the existing private **source proposal/admission** workflow for each
   exact collection scope. It checks overlaps and the matching preflight and
   resource policy. Then retrieve through the approved environment, preserve
   unfilled observations and provenance, and use the shared dataset structure.
6. Report progress through the assignment CLI:

```sh
python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" report JOB_ID \
  --person YOUR_PERSON_ID --status in_progress --note 'Private progress evidence'
python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" report JOB_ID \
  --person YOUR_PERSON_ID --status completed --note 'Private artifact hashes, coverage and omissions'
```

Use `--status blocked` when work cannot finish. Only the actual owner may report.
Never share credentials, buy data, evade provider limits, or publish private paths,
observations or reports in GitHub issues. Keep observations remote and unfilled.
Do not repeat collection or start another worker because a snapshot looks stale.

The board shows **Open**, **In progress · person**, and **Finished · person**.
Reserved and blocked work remain owned. Finished means the owner reported
completion; a matching independent audit must still establish data eligibility.
Progress publishes approximately every 15 minutes while the maintainer Mac is
online. **Refresh progress** reloads the last published confirmed snapshot.

## Post a source

Use **Propose a free source**, including its official documentation, market,
sector, free-access evidence, native interval and history. A proposal is not a
claimable collection job. The coordinator confirms free access and publishes
the protected job definition; exact instruments and collection evidence remain
private. Existing provider jobs are reused instead of creating duplicate jobs.

For the coordinator's agent, stage an additive definition locally:

```sh
python3 -B -m coordination.source_jobs \
  --sources docs/acquisition-sources.json \
  --source-ids crypto-spot-kraken \
  --base-generation BASE_GENERATION_SHA256 \
  --previous PREVIOUS_PRIVATE_SOURCE_MANIFEST \
  --out NEW_PRIVATE_SOURCE_MANIFEST \
  --public-out NEW_PUBLIC_SOURCE_JOB_DEFINITIONS
```

Omit `--previous` only for the first package. Output files must be new. The
coordinator publishes a new immutable package and updates the protected pointer
and pinned public catalogue together, retaining every prior job definition,
assignment and worker. Publish the generated public definitions to
`coordination/source_job_definitions.json`. The existing publisher derives job
ownership from GitHub and completion from proof-bound Native reports. Do not
edit snapshots, assignment receipts, frozen queues or worker claims by hand.
