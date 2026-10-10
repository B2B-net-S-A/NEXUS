# Integracja COMPASS ↔ NEXUS (kontraktorzy + cykl życia)

Druga apka (COMPASS, HR, Next.js/Supabase) i NEXUS wymieniają dwie rzeczy poza
dniami roboczymi z D5. **Kod wdrożony (#1368), aktywacja częściowo credential-gated.**

**Dwa kierunki, dwa różne sekrety — łatwo pomylić:**

| Przepływ | Endpoint (źródło) | Uwierzytelnienie | Konsument |
|---|---|---|---|
| Kontraktorzy: **Compass ← NEXUS** | `GET /api/integrations/compass/contractors` | `X-API-Key` = klucz konta serwisowego scope `contractors:read` | cron Compassa |
| Cykl życia: **NEXUS ← Compass** | Compass `GET /api/internal/roster` | `Bearer` = `COMPASS_LIFECYCLE_SECRET` | pętla `compass_lifecycle_sync` |

- **`/api/integrations/compass/contractors`** (`app/api/integrations_compass.py`) —
  tożsamość + zaangażowanie, **BEZ kwot** (decyzja produktowa). Reużywa kształtu
  `contractors.list_contractors` minus stawki, więc NIE woła `effective_rate_fields`
  (brak pułapki `RATE_SCHEDULE_LOADS`). `lacks_current_order` = sygnał ławki (Etap 4).
  Ścieżka CELOWO pod `/api/integrations/…`, nie pod `/api/candidates|jobs|clients|users`
  — `test_key_cannot_reach_domain_data` wymaga tam 401 dla klucza. Moduł **bez**
  `from __future__ import annotations` (slowapi #579) i **na liście `_RATE_LIMITED_MODULES`**
  w `test_public_surface_hardening.py`.
- **Scope `contractors:read`** (`app/models/service_account.py`) — nazwa NIE może brzmieć
  `candidate:read`/`client:read` (`test_no_candidate_data_scope_exists` je zakazuje).
- **`compass_lifecycle_sync`** (`app/services/compass_lifecycle.py` + `app/tasks/`) —
  pętla tła, deaktywuje `users.is_active` osób ze statusem `exited` w Compassie.
  **Jednokierunkowa** (nigdy nie reaktywuje), **`offboarding` NIE deaktywuje**
  (offboarding trwa po ostatnim dniu pracy), **pusty roster = awaria, nie masowe
  odejście**. Nie rusza rankingów wypłacających nagrody (`competitions.py:194`
  zostaje). Domyślnie WYŁĄCZONA (`COMPASS_LIFECYCLE_ENABLED=false`).
  **Ręczne przywrócenie konta przez admina wygrywa — ale tylko w bieżącym
  epizodzie odejścia** (od 11.09.2026). Aktywne konto osoby `exited` jest
  deaktywowane, CHYBA ŻE ostatnia jawna decyzja admina to przywrócenie
  (Activity `active_changed` z `to=True`, `PUT /api/admin/users/{id}`) nowsze
  niż początek bieżącego epizodu. Początek epizodu = chwila, w której pętla
  zobaczyła zmianę statusu na `exited` (per osoba w
  `app_settings['compass_lifecycle_state']`, wersja 2); przy pierwszej
  obserwacji — ostatnie Activity `compass_lifecycle_deactivated`, a bez niego
  `now()`. Włączenie konta bez takiego Activity (logowanie SSO z grupą AAD,
  resync AAD) NIE liczy się — następny bieg wyłącza je znowu; stare,
  niezwiązane przywrócenie sprzed odejścia też nie. Do 11.09 każdy sync
  wyłączał wszystkich `exited`, więc przywrócenie przez admina znikało po ≤6 h;
  pierwsza wersja poprawki („tylko przy zmianie statusu”) zostawiała dostęp na
  zawsze po takim przywróceniu (przegląd adwersarialny 11.09). Stara pętla nie
  zostawiała śladu, więc konto przywrócone PRZED wdrożeniem zostanie wyłączone
  raz. Zapis stanu to upsert (dwa kontenery przy deployu); logi niosą liczby
  i ID, bez e-maili.
- **`GET /api/insights/reconciliation/placements`** (`app/api/insights_reconciliation.py`)
  — read-only raport uzgadniający placementy w OBU rodzinach atrybucji (FULL OUTER,
  LEFT JOIN na sieroty). Tłumaczy rozjazd 213/228/317/332, **nie usuwa go**; NIE
  rusza `VERIFIER_ANCHORED_CTE`. Nazwiska kandydatów tylko dla ról z odczytem
  kandydatów (`user_has_candidate_read`); pozostali dostają `candidate_id`
  i flagę `candidate_names_redacted`.
- **Sonda `checks.compass_workdays`** w `/api/health` (0276 `CompassWorkdaysSyncState`) —
  patrz sekcja o D5; `healthy` wymaga `last_status=='ok'`, nie samej świeżości.

**Env (Coolify, przez workflow „Coolify set env"):** `COMPASS_LIFECYCLE_ENABLED`,
`COMPASS_LIFECYCLE_URL` (`https://compass.dynaminds.pl/api/internal/roster`),
`COMPASS_LIFECYCLE_SECRET` (**= Compass `ROSTER_EXPORT_SECRET`**). Klucz konta
serwisowego wydaje admin przez API — `POST /api/settings/service-accounts/{id}/keys`
z tokenem admina (aplikacja NIE ma ekranu kont serwisowych, audyt 25.09.2026);
mintuje żywe poświadczenie, więc nie da się z CI (`coolify-ops.yml` świadomie
nie ma `command`).
