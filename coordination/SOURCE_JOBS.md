# Free-source collection jobs

Use **Find new data → Confirmed free-source jobs** on the dashboard. Jobs are
provider-wide, so several sectors from the same provider share one owner.
Resume active assignments first. For new discovery, follow the dashboard's
market/sector coverage priorities: classify existing qualified price instruments,
then pursue missing sectors and regions. Do not treat a passing volume or trade
count as a passing price history. Additional crypto venues are lower priority
than an uncovered market. ETF/CFD proxies stay distinct from the underlying
commodity, future, yield or index and cannot close its coverage gap.

1. Choose your participant name and submit **Claim via GitHub**. Wait for the
   confirmation; opening the form does not reserve anything.
2. Give your agent **Copy agent instructions**. It must read the private hub's
   `AGENT_TASKS.md` to set `KUINA_TASK_MANAGER` and `KUINA_TASK_HUB`, then use its
   own approved cluster account. Resume existing work first.
3. For a reserved job, run `prepare-work`, submit its returned GitHub start form,
   wait for confirmation, and run the copied `claim --proof-sha256` command.
   Only that Native UID creates the actual worker. Stop on a failed claim.
4. Read the exact private job with `read-batch`. Inspect existing data first.
   Check two years of actual history, native intervals of 15 minutes or finer,
   instrument meaning and expected-calendar gaps. An archive index alone is
   insufficient. Use the self-service qualification policy below when metadata
   cannot answer a content-level check.
5. Continue under your existing provider claim. Record the exact collection
   scope, existing-data/overlap check, technical evidence and bounded resource
   plan privately. Retrieve through your approved environment, preserve unfilled
   observations and provenance, and use the shared dataset structure. No second
   coordinator admission or plan-verification receipt is required.
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

## Continue without coordinator handoffs

**Current policy, 26 November 2026.** This applies to **all participants and all
confirmed assignments: source jobs, unique repair batches and retained legacy
workers**. The confirmed assignment plus the actual UID-bound worker claim
authorize routine investigation, repair, qualification and collection within
the assignment's scope. Existing legacy workers resume their original claim.
This policy supersedes source-proposal/admission and plan-verification handoffs
in older `AGENT_TASKS.md` copies and frozen source-job descriptions. Keep those
records intact; do not create another worker or modify its ownership.

- Do not wait for a coordinator to run `admit` or `verify`, sign a preflight
  receipt, approve an ordinary output directory, or approve each instrument.
  Existing unadmitted proposals are private evidence; they need no conversion
  into additional tasks. A completed metadata/preflight stage can proceed to
  its next stage without a separate plan-verification receipt.
- Inspect existing datasets, metadata and retained work scopes first. Reuse
  equivalent data. A source job's provider owner coordinates its instruments and
  shared archives. Repair workers combine fields/warnings for the same underlying
  instrument and coordinate actual cross-assignment overlaps. Download a shared
  file once even if it contains several regions or series. Record exact
  provider/instrument/venue/feed/currency/adjustment/window,
  overlap findings and the plan in the existing private worker report or an
  evidence file referenced by that report. An actual overlap with another owner
  remains a blocker; missing administrative paperwork alone is not one.
- Perform and document your own technical preflight. When metadata cannot prove
  content completeness, you may make a **bounded provisional qualification**
  download: at most **256 MiB transferred, 512 requests and 30 minutes total per
  assigned job** (provider-wide for source jobs), one request at a time, with
  bounded retries and provider rate limits. All transferred bytes and requests,
  including retries, count against
  these totals; fetch a shared archive once.
  Stop at the limit and report the remaining evidence gap. Do not evade access
  restrictions. This is a small inspection allowance, not permission for an
  unbounded archive scrape.
- Keep qualification artifacts in a new provisional release/staging directory
  under the appropriate shared dataset category. Follow the shared README;
  choose the ordinary dataset/release names yourself and record provenance.
  Run content processing or collection in your approved execution environment
  (Deigo CPU allocation where required), not as bulk work on a login node.
  Preserve originals and unfilled values. No unrelated jobs may be displaced.
- Before larger collection, record evidence against the assignment's existing
  scientific criteria and a bounded execution/storage/request plan. Financial
  prices and regular series under the current testing profile require the same
  instrument/source, native interval ≤15 minutes, actual two-year history,
  meaning and calendar/gaps. Identity/metadata work retains its own criteria;
  this policy does not add a price-history gate to unrelated work. Your agent performs these
  checks; no coordinator signature is needed. Failed or unresolved technical
  checks stop larger collection. Do not fabricate a `verified: true` receipt.
- Report progress and then `completed` through the existing assignment CLI.
  Report both acquired artifacts and exclusions honestly; a blocked or entirely
  unsuccessful collection is not finished. Neither a coordinator receipt nor a
  final eligibility audit is needed to report collection completion. Only a new
  matching independent audit and publication can certify eligible series or
  change dashboard counts; provisional observations must not enter analyses as
  qualified data before that audit.
- If your own worker is marked `blocked`, resolve the blocker and report
  `in_progress` on that same worker. No coordinator approval is needed to resume.
  Reserve reconciliation for uncertain ownership, release/reassignment or a
  genuinely interrupted state. Keep multi-stage work active until the assignment
  is finished; `completed` is the final report, not a request to approve a plan.

For any already-started assignment, resume directly:

```sh
python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" show JOB_ID
python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" read-batch JOB_ID
python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" report JOB_ID \
  --person YOUR_PERSON_ID --status in_progress --note 'Private plan, overlap check and evidence reference'
```

Resolve the current executable from the private hub's `AGENT_TASKS.md`. Keep
using the actual owner's account. Do not run `prepare-work` or `claim` again for
an existing worker. Do not seek a second security approval for already assigned
work because an old task description mentions per-task human approval. This
policy does not grant unrelated scope, paid access,
credential sharing, account creation, unsupported instruments or larger compute
resources. Newly proposed providers still need confirmation before claiming.

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
