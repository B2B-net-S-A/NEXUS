# NEXUS AI rollout, rollback and cleanup runbook

## Safety baseline

- Global production routing remains `v1_current` until a canary reaches 100%,
  completes its final observation window and is explicitly completed.
- A rollout may reference only code-owned registries. Model/provider names are
  not accepted from the UI.
- Stable assignment is derived from `feature + client`, then `feature + user`;
  system calls without a stable subject stay on the baseline.
- Stages are fixed: offline gate → shadow → 5% → 10% → 25% → 50% → 100%.
  Each online stage lasts 48–72 hours (72 by default); stages cannot be skipped.
- Candidate rejection is never an autonomous AI action.

## Start and advance

1. Record a passing offline evaluation artifact/gold-set reference.
2. `POST /api/admin/ai-rollouts/start` with baseline `v1_current`, target
   `v2_tiered`, the artifact reference, reason and `offline_gate_passed=true`.
3. Shadow traffic never changes the user-visible route. After its minimum
   window, advance with the current optimistic `lock_version`.
4. Submit monitoring windows to
   `POST /api/admin/ai-rollouts/{feature}/observations`. The observation must
   identify the target registry.
5. At 100%, wait the full stage window and complete the rollout. Completion
   atomically makes the target the global route and opens four weeks of weekly
   monitoring plus monthly frozen regression tracking.

## Automatic rollback gates

Rollback is immediate for a privacy incident. It is also automatic when any
window crosses: critical hallucinations >0.5%; provider errors >1% over at
least ten minutes; p95 latency +50%; cost +25%; Recall@20 drop >1 pp;
nDCG@10 drop >3%; or an important slice drop >3 pp.

Route rollback is always applied. If the rollout includes four complete Qdrant
alias snapshots, all aliases are switched atomically back to the baseline.
An index rollback failure is written to the append-only event; it never keeps
the target route active.

Manual rollback uses
`POST /api/admin/ai-rollouts/{feature}/rollback` with optimistic locking and a
reason. Never delete old collections as part of rollback.

## Retention and cleanup

- Old route code and physical vector collections remain available for at least
  14 days after completion.
- Weekly quality reports are required for four weeks; a frozen regression run
  is required monthly.
- The rollout API reports `cleanup_eligible=true` only after the 14-day rollback
  window. Before that flag is true, do not remove legacy JSON parsing, cache
  formats, `salary_range`, hardcoded legacy names or fallback compatibility.
- Cleanup is a separate reviewed PR after the monitoring window. Remove only
  paths proved unused by ledger/route metrics; retain encrypted eval-output
  deletion (14 days) and ledger retention (13 months).

## Production verification

After every merge, verify `/api/health` with
`User-Agent: dynaminds-smoke-test/1.0`. `status` must not be `unhealthy` and
`version` must begin with the deployed commit's seven-character SHA. Verify
Settings → AI and the affected recruiter flow in the production Chrome profile.

## Background tasks

NEXUS has 24 lifespan tasks. AI maintenance reuses `embedding_index_sync` for
ledger retention, eval-output deletion and rollout observation evaluation; it
does not add another process or increase concurrency on the CAX21 host.
