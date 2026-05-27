# Talent Pools — backfill empty pools po Phase 10 A2

## TL;DR

QA 2026-05-27 sygnalizował że w `/talents` pule są w większości puste
(99 z 104 bez członków). To **nie bug aplikacji** — Phase 10 A2 dodał
`talent_pool_auto_add` który napełnia pools przy każdym przejściu
kandydata do stage `cv_sent`. Ale 18,498 historycznych `cv_sent` stages
sprzed wdrożenia Phase 10 A2 NIE były replayowane → puste pools.

Naprawienie wymaga jednorazowego odpalenia `backend/scripts/backfill_talent_pools.py`
na prod. Skrypt jest idempotent (UniqueConstraint `uq_pool_candidate`).

## Pre-flight check

DB query potwierdzający stan:

```sql
SELECT
  COUNT(*) AS total_pools,
  COUNT(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM talent_pool_memberships m WHERE m.talent_pool_id = tp.id
  )) AS pools_with_members,
  (SELECT COUNT(*) FROM talent_pool_memberships) AS total_memberships,
  (SELECT COUNT(*) FROM candidate_stages WHERE stage = 'cv_sent') AS cv_sent_stages
FROM talent_pools tp;
```

Aktualnie (snapshot 2026-05-27):
- total_pools: 104
- pools_with_members: 5 (Senior Angular, DevOps, QA, Java Backend, Targ)
- total_memberships: 35
- cv_sent_stages: 18,498 (potencjał wzrost memberships do ~kilkudziesięciu tysięcy)

## Procedure

### 1. Dry run (verify zakres)

SSH na prod server lub via Coolify Terminal:

```bash
cd /var/www/html/backend  # lub container working dir
python -m scripts.backfill_talent_pools --dry-run
```

Output sygnalizuje:
- Phase A: ile pools dostanie CC update (mode po memberships)
- Phase B: ile cv_sent stages zostanie replayed

### 2. Wykonanie

```bash
python -m scripts.backfill_talent_pools --commit
```

Skrypt commituje w batchach po 500. Idempotent — można re-run jeśli
przerwany. Errory loguje per kandydata, nie przerywa całości.

### 3. Verification

Re-run pre-flight query — `pools_with_members` powinno wzrosnąć z 5
do >= 70% pools (zależy od pokrycia subcategory/seniority w jobs).

Centroid sync background task automatycznie odświeży vectorów dla nowo
zapełnionych pools w przeciągu 24h (`cc_centroid_sync.py` co `STALE_DAYS`
threshold). Manualny refresh:

```bash
python -m scripts.refresh_pool_centroids  # jeśli istnieje
# lub w Python REPL:
# from app.services.cc_centroid_service import refresh_stale_centroids
# await refresh_stale_centroids(db, stale_days=0)
```

## Skip cases

Skrypt NIE wsteczna napełni puli kandydatami, jeśli:
- Job nie miał `competence_category_id` → pool zostaje bez CC
- Pool ma kryteria (`criteria` JSONB) niezgodne ze stage → szybsze
  to manualne re-tag w UI niż backfill

## When to skip the backfill entirely

Jeśli baza Twardowski et al. ma > 50% kandydatów z @b2bnet.pl legacy
domain → backfill może zaśmiecić pools wpisami legacy. Wtedy lepiej
poczekać aż natural CV-sent flow zapełni pools świeżymi kandydatami.

## Audit

Wynik backfill loguje się w `logs/talent_pool_backfill_YYYYMMDD.log`
(lub stdout w containerze). Activity records też tworzone — query:

```sql
SELECT COUNT(*) FROM activities WHERE type LIKE 'pool_%' AND created_at > NOW() - INTERVAL '1 day';
```
