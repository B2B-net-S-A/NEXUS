# Moduł 4 (pipeline/submission/placement) — raport ukończenia Fali 0 (containment)

> Data: 2026-07-16 · Wykonanie: Claude Code (Opus 4.8) · Decyzje: Artur
> Plan: `docs/recruitment-pipeline-submission-placement-module-audit-and-claude-implementation-plan-2026-07-16.md`

## Kontekst

Audyt Codex (22-PR plan) został **zweryfikowany przed startem — 13/13 sprawdzonych
twierdzeń potwierdzonych w kodzie co do linii**. Artur zdecydował: pełny plan 22 PR,
wykonywany falami. Ten raport zamyka **Falę 0 (PR-00…PR-04)**.

Decyzje wykonawcze Artura (2026-07-16):
1. pełny plan (nie sam containment),
2. normalizacja stawek **168 h/mc, 21 dni/mc**; waluta ≠ PLN → manual review,
3. share tokeny CV — **pełne v2** od razu,
4. hard delete rekrutacji z hired/kontraktem — **blokada + admin override**.

## Zrealizowane PR-y

| PR | # | Status | Zakres |
|---|---|---|---|
| PR-00 inventory | #780 | MERGED+DEPLOYED+VERIFIED | `GET /api/admin/pipeline-inventory` — 16 klas anomalii, read-only, zero PII |
| PR-01 RBAC | #782 | MERGED+DEPLOYED+VERIFIED | `recruitment_access.py`, viewer out z lifecycle, sourcer bez terminal/verified/rate, multi-role fixes, migracja 0175 (FK CASCADE ×2) |
| PR-02 integrity | #784 | MERGED+DEPLOYED+VERIFIED | normalizacja stawek w gate, pending-block, walidacja targetu/powodów, restore→cancel maili, side effects po commicie, bulk hygiene, hard-delete guard, tiebreaker ×11, template guards |
| PR-03 frontend | #786 | MERGED | Kanban: rollback optimistic, nowy ID z response, hired confirm, compact z akcjami, multi-role; shortlist: taksonomia błędów + retry |
| PR-04 share/HTML | #788 | PR otwarty (CI) | sanitizer allowlist, token v2 (hash, TTL 14/90, max views, lista/revoke, audit, no-store), scheduler escaping + kategoria, mail body scope |

Migracje: `0175_stage_notif_user_fk_cascade`, `0176_cv_share_token_v2` — obie
zmirrorowane idempotentnie w `backend/entrypoint.sh` (prod alembic orphaned).

## Produkcyjny baseline anomalii (PR-00, query_version `m4-pr00-v1`)

Pierwsze twarde liczby (2026-07-16, 176 634 wierszy stage / 79 581 par / 53 818 otwartych):

| Severity | Klasa | Liczba |
|---|---|---|
| P0 | stage_def poza template'em joba (latest) | **79 488** |
| P0 | hired bez kontraktu | **499** |
| P0 | pending-not-current | 0 |
| P1 | duplicate latest ties (niejednoznaczny current) | **4 544** |
| P1 | latest(time) ≠ latest(id) — backdated | 2 647 |
| P1 | terminal→aktywny (niejawny reopen) | 276 |
| P1 | >1 live contract na kandydata | **48** |
| P2 | aktywni na zamkniętym jobie | 34 040 |
| P2 | cv_sent bez snapshotu CV | 19 750 |
| P2 | karty >90 dni | 15 554 |
| — | czyste: share-tokeny bez expiry, backlog maili, duplicate external IDs, contract-bez-hired | 0 |

Interpretacja: dominująca anomalia (79 k) to systemowy skutek importu Traffit
(joby bez `pipeline_template_id` zgodnego ze stage'ami) — dlatego walidacja
w PR-02 dotyczy **wyłącznie targetu** ruchu; naprawa danych = fale 1+ (backfill).

## Weryfikacja produkcyjna

- `/api/health` po każdym merge (exact-SHA), status `healthy`,
- PR-01: 5 read-surfaces 200 dla admina po deployu (SLA, funnel, kalendarz, feedback, pending),
- PR-02: authed fetch — bulk missing→422, bulk verified→422 (blokada), unset-only-default→409,
- PR-03: UI Chrome (drag/hired-dialog) — do wykonania po deployu frontendu,
- PR-04: po merge — utworzyć link v2 na testowym CV i sprawdzić listę/revoke/no-store.

## Świadome odstępstwa od planu (odnotowane w PR-ach)

1. **Resource scope (owner/collaborator) odroczony** — brak modelu collaboratorów; wchodzi z command service (PR-07+).
2. **HoR bez terminal capability** — route-level `/move` = RecruiterPlus; containment nie poszerza dostępu.
3. **Preflight requirements w FE** — wymaga API z PR-07; do tego czasu FE uczciwie pokazuje 409/422 backendu i wraca do prawdy serwera.
4. **CSP publicznej strony `/cv/[token]`** → PR-21 (fala UI).
5. **Legacy `rejected` bez powodu nadal przechodzi** — zaostrzenie wymaga decyzji produktowej; `withdrawn` egzekwowane (DB CHECK).

## Nowe kontrakty (nie cofać bez decyzji)

- `backend/app/api/recruitment_access.py` — capability sets lifecycle (wzorzec `candidate_access.py`),
- `backend/app/services/rate_normalization.py` — `POLICY_VERSION="168h-21d-v1"`,
- bulk-move: `verified`/`hired` = 422 dla wszystkich; limit 100; dedupe,
- share tokeny: sekret tylko jako SHA-256; raw pokazywany raz.

## Następne kroki (Fala 1 — PR-05…PR-11)

Wymagane decyzje z sekcji 20 planu **przed** startem:
- (§20.2) granica „reopen tego samego attempt" vs „nowa re-aplikacja" — blokuje PR-06,
- (§20.1) kanoniczny lifecycle / znaczenie `hired` vs `placement_active` — wpływa na PR-05 mapping,
- (§20.9) authority NEXUS vs Traffit per pole/stan — przed PR-10.

Bez tych decyzji Fala 1 nie powinna ruszyć (wymóg planu: brak decyzji = feature OFF, nie ukryte założenie).
