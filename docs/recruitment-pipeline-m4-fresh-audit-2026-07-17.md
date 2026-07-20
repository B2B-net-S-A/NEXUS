# Moduł 4 — świeży audyt (2026-07-17), poza listą Codexa

> Autor: Claude (Fable 5) · Tryb: read-only audyt gałęzi `feat/recruitment-process-pr06`
> (= pełny moduł M4, PR-00..06) + weryfikacja produkcji.
> Cel zadania Artura: „zrób audyt jak Codex, zobacz czy znajdziesz coś **innego**".
>
> Metoda: bezpośrednia lektura kodu dopisanego w PR-00..06 (którego audyt Codexa
> nie widział, bo powstał po nim) + świeże spojrzenie na moduł. Wieloagentowy
> workflow padł na limicie sesji, więc audyt wykonany ręcznie na krytycznych
> plikach. Każde ustalenie ma dowód (plik:linia) i scenariusz awarii; przy
> multi-head świadomie **zweryfikowałem i obniżyłem** wagę zamiast asertować.

## 0. Zakres różnicowy vs Codex

Audyt Codexa (`...audit-and-claude-implementation-plan-2026-07-16.md`) opisał 30+
ustaleń P0.1–P3.2 dla **stanu przed** implementacją. Ten dokument NIE powtarza
ich — szuka rzeczy, których tam nie ma, w dwóch klasach:

- **A) błędy w kodzie, który sami dopisaliśmy** w PR-00..06 (containment + Fala 1),
- **B) rzeczy systemowe, które pojawiły się po audycie** (równoległe programy M5/M7).

## 1. Ustalenia NOWE

### N1 — [P0 → ROZWIĄZANE] Produkcja NEXUS leżała ~godzinę (Coolify), teraz zdrowa

**Przebieg (2026-07-16 ~21:20 UTC → 2026-07-17 ~12:23 UTC):** `coolify-nexus`
zwracał HTTP 500/502, `api.nexus…/api/health` → „no available server" (Traefik
bez zdrowego backendu); dotyczyło WYŁĄCZNIE serwera NEXUS (compass/atlas OK).
Deploy PR-06 (`882d6bd`) padał (webhook 20×500). Przyczyna wg wzorca: pełny dysk
z churnu 2 równoległych programów PR-owych (jak incydent 2026-05-22).

**Stan końcowy (zweryfikowany live):** Coolify → 302, `/api/health` → 200,
**`version=3add8b7` (nowszy niż PR-06 `b78fe3f`)** → migracja
`0178_recruitment_processes` + tabele workflow (0177) **są już na prodzie**, cały
moduł M4 (PR-00..06) wdrożony. Artur dodał `#811 disk-usage alerting` — adresuje
pierwotną przyczynę (pełny dysk). Pozostaje jednorazowo zweryfikować przez admin
API, że tabele odpowiadają na `shadow-compare` i uruchomić backfill par.

### N2 — [P1, współbieżność] TOCTOU na single-flight guardzie backfillu

**Dowód:** `backend/app/api/admin_recruitment_processes.py:107-112`
```python
if _JOB["running"]:
    raise HTTPException(409, "Backfill już trwa")
asyncio.create_task(_run_backfill(limit_pairs, resync_stale))   # <-- schedule
```
Flaga `_JOB["running"]=True` jest ustawiana **wewnątrz** `_run_backfill`
(linia 61), a nie synchronicznie w handlerze. `asyncio.create_task` tylko
planuje korutynę — nie uruchamia jej natychmiast.

**Scenariusz awarii:** dwa szybkie POST-y `/backfill` (podwójny klik / retry):
żądanie A czyta `running=False`, planuje task A, zwraca. Żądanie B — zanim task A
w ogóle wystartuje i ustawi `running=True` — też czyta `running=False`, planuje
task B. Dwa równoległe backfille wkładają te same pary → kolizja na
`uq_process_attempt` / partial-unique `ux_process_one_open` → `IntegrityError` na
`db.commit()` batcha → jeden job wpada w `except` i ustawia `last_error`, ale oba
zdążyły zainterleave'ować część commitów. **Nie jest to problem Codexa** — kod
PR-06 nie istniał w momencie audytu.

**Naprawa (1 linia):** ustawić `_JOB["running"]=True` **synchronicznie w
handlerze przed** `create_task` (albo `asyncio.Lock`). Wtedy okno TOCTOU znika.

### N3 — [P1, ścieżka migracji] Duch `RecruitmentProcess` po „Usuń z rekrutacji"

**Dowód:** `backend/app/models/recruitment_process.py:100-102`
```python
legacy_current_candidate_stage_id: Mapped[Optional[int]] = mapped_column(
    ForeignKey("candidate_stages.id", ondelete="SET NULL"), nullable=True)
```
Endpoint `DELETE /api/candidates/{id}/recruitments/{job_id}`
(`candidates.py`) kasuje WSZYSTKIE `CandidateStage` pary. FK procesu jest
`ON DELETE SET NULL`, a **sam wiersz procesu nie jest usuwany** (kandydat i job
istnieją, więc CASCADE po nich nie strzela).

**Scenariusz awarii:** po hard-delete zwykłej pary (PR-02 blokuje tylko
hired/kontrakt; admin ma override) zostaje osierocony `RecruitmentProcess` z
`legacy_current_candidate_stage_id = NULL`, potencjalnie `status='open'`,
`current_semantic_state` wskazującym stan, którego już nie ma. W shadow mode
nieszkodliwe. Ale przy przejęciu authority w **PR-07/08** ten duch (otwarty
proces bez historii) wróci do Kanbanu/raportów jako „zombie". Codex P0.8
dotyczył kasowania historii, ale nie interakcji z agregatem — bo agregat wtedy
nie istniał.

**Naprawa:** przy adopcji agregatu (PR-07) komenda „remove from recruitment"
musi `void`ować proces; do tego czasu dodać klasę reconciliation
`process_without_legacy_history` do preflightu/komparatora (`process_backfill.
compare_shadow_state`) żeby duchy były policzalne.

### N4 — [P2, housekeeping migracji] Multi-head przy 0174 bez migracji-merge

**Dowód (zweryfikowane, świadomie obniżone z „P0"):** dwa żywe heady rozchodzą
się przy `0174_analytics_v1_foundation`:
- łańcuch M4: `0175_stage_notif` → `0176_cv_share_token_v2` → `0177_workflow_revisions` → `0178_recruitment_processes`
- łańcuch M5/M7: `0175_analytics_milestones` → `0176_finance_filled_at` → `0177_analytics_snapshots_cutovers`

**Dlaczego NIE jest blockerem:** cały repo używa `alembic upgrade heads` (mnoga)
— `ci.yml:85` i `entrypoint.sh:71` — więc oba łańcuchy aplikują się poprawnie.
To chroniczny wzorzec repo, rozwiązywany okresowo migracjami-merge
(`0081_merge…`, `0091_merge…`, `0098_merge_heads`, `0109_merge_three_heads`).

**Co jest NOWE i realne:** dla tego rozjazdu **brak migracji-merge**, więc:
`alembic revision --autogenerate` rzuci „Multiple head revisions"; `alembic
downgrade` jest niejednoznaczny; a `docker-compose.prod.yml:41` + `CLAUDE.md:114`
wciąż dokumentują `upgrade head` (poj.), które by padło, gdyby ktoś je odpalił.

**Naprawa:** dodać `0179_merge_m4_m5m7` z `down_revision =
("0178_recruitment_processes", "0177_analytics_snapshots_cutovers")` (jak
0098/0109). Zero DDL, sam scala graf.

### N5 — [P3, zweryfikowane-benign] Semantyka `onboarding`/`interview` vs kolejność Kanbanu

`semantic_states.LEGACY_TO_SEMANTIC` mapuje `onboarding→contract_preparation`
i `interview→internal_review` — decyzje oddające ZNACZENIE, nie kolejność
kolumny. W domyślnym template „Zatrudniony" (hired) stoi PRZED „Onboarding"
(Codex P2.5), więc proces na `onboarding` mapuje się na `contract_preparation`
(pre-hire) mimo pozycji po hired. **Nie jest to nowy bug** — to inherentny
bałagan legacy template'u; w shadow bez skutku. Do odnotowania: PR-07 przy
adopcji musi liczyć lejek po `semantic_state`, nie po kolejności kolumn, inaczej
te procesy „cofną się" w metrykach.

## 2. Co sprawdziłem i uznałem za POPRAWNE (żeby nie było fałszywych alarmów)

- **`process_backfill`**: keyset-pagination `(candidate_id, job_id) > last_pair`,
  kanoniczny porządek `(moved_at ASC, id ASC)`, idempotencja insert-only,
  `resync_stale` tylko dla `source_authority='backfill'` — deterministyczne,
  rerun-safe. OK.
- **`compare_shadow_state`**: definicja „latest" identyczna z backfillem
  (`moved_at DESC, id DESC`). OK.
- **Partial unique `ux_process_one_open`** + `uq_process_attempt` — poprawnie
  egzekwują „najwyżej jeden otwarty proces pary" (Codex P0.1). OK.
- **`workflow_registry_service` bootstrap** — mapping albo kwarantanna `unmapped`
  (nigdy zgadywanie), pełny digraf krawędzi = parity z legacy brakiem walidacji
  przejść. Zweryfikowane na prodzie: 3 workflow, 5 etapów kwarantanny → po
  Twoim mappingu 100% zmapowane. OK.

## 3. Rekomendacja

Priorytet: **N1** (przywrócić prod — akcja Artura, konsola Hetzner) →
**N2** (1-liniowy fix TOCTOU, follow-up PR do PR-06) → **N4** (migracja-merge
0179, trywialna) → **N3** (uwzględnić w scope PR-07). N5 tylko do świadomości.

Żadne z N1–N5 nie podważa Fali 0 (containment) — to są kwestie w NOWYM kodzie
Fali 1 (PR-06) i w koordynacji równoległych programów, których audyt Codexa
z natury nie mógł objąć.
