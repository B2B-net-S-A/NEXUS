# Moduł klienta — PR 1/7: Containment RBAC i bezpieczne projekcje

> Raport ukończenia. Plan źródłowy:
> [client-demand-module-audit-and-claude-implementation-plan-2026-07-16.md](client-demand-module-audit-and-claude-implementation-plan-2026-07-16.md)
> (sekcja 11, PR 1/7). Data realizacji: 2026-07-16.

## Status

- **Branch:** `fix/client-rbac-containment`
- **PR:** [#770](https://github.com/artur-t-96/Nexus/pull/770)
- **Merge/deploy:** squash-merge po zielonym CI; weryfikacja deployu
  (`/api/health.version` = short SHA merge'a, UA `dynaminds-smoke-test/1.0`)
  wykonana po deployu — dowody w komentarzu PR #770.
- **Feature flag:** brak — poprawki P0 RBAC są fail-closed i działają od deployu
  (zgodnie z planem: „deploy bez flagi dla naprawy zapisu").
- **Migracja DB:** brak (audit używa istniejącej tabeli `activities`) →
  brak zmian w `backend/entrypoint.sh`.

## Koordynacja z równoległym R0 (analytics containment, PR #769)

Podczas prac zmergował się równoległy PR #769 (R0 analytics), który nachodził
na moduł klienta. Rozstrzygnięcia przy rebase (bez duplikacji zasad):

- `clients.py` list/detail/profile → guard `OperationalUser` z R0 zostaje
  (viewer nie przechodzi w ogóle — ostrzejsze niż projekcja PR1);
  na wierzchu nakłada się projekcja legal PR1 (`ClientSafeResponse`).
- Redakcja finansów profilu: zostaje mechanizm R0 (`VIEW_FINANCE`
  capability, admin/DL, multi-role) — duplikat `has_financial_access`
  z PR1 usunięty.
- `client_framework_contracts.py` ready: R0 dał `TacPlus`; PR1 unifikuje
  przez `LegalDocsReader`/`ClientAccess.can_view_legal_documents`
  (ten sam zbiór + head_of_recruitment).
- `ClientProfileSummary.active_mrr/ltv` Optional — wersja R0 zostaje.
- HoR przechodzi teraz do `/profile` (OperationalUser), finanse dla HoR
  nadal redagowane (brak VIEW_FINANCE).

## Weryfikacja audytu na origin/main (adcfa43) przed implementacją

| Ustalenie | Wynik |
|---|---|
| M1-SEC-01 — CRUD kontaktów/wiedzy na gołym `CurrentUser`, w tym reassign `key_relationship_owner_id` | ✅ potwierdzone |
| M1-SEC-02 — legal/finansowe/prywatne pola dla każdego zalogowanego (NIP/notes, `relationship_notes`, pobieranie MSA, warunki umów, marże w `/profile`) | ✅ potwierdzone |
| M1-RBAC-02 — porównania pojedynczej roli (`my_clients.py:54,63`, `my_relationships.py:58`, `clients_team.py:69`) | ✅ potwierdzone |
| M1-TEST-01 — brak testów modułu klienta w wymaganym jobie CI | ✅ potwierdzone |

## Co zostało zrobione

### Nowe pliki

- `backend/app/services/client_access.py` — resolver `ClientAccess`
  (jedno źródło decyzji per klient) + dependency FastAPI + helper audytu
  `record_client_audit`. Stabilny kod 403: `client_access_denied`.
- `backend/tests/test_client_access_matrix.py` — tabelaryczna macierz
  9 profili (admin, HoR, DL, TAC, recruiter±Job, sourcer, viewer,
  multi-role) × operacje; projekcje; reguły ownera; 404 vs 403; audit;
  multi-role. Dodany do wymaganego joba CI.

### Zmienione powierzchnie

| Plik | Zmiana |
|---|---|
| `app/api/contacts.py` | CRUD przez `ClientAccess`; `relationship_notes` znika z JSON dla nieuprawnionych (odrębne schematy Safe/Full); owner edytuje tylko pola relacyjne; reassign ownera = admin/HoR (+ claim None→self); audit eventy; globalna lista `/api/contacts` tylko role zarządzające |
| `app/api/client_knowledge.py` | create/delete = admin/HoR/DL/TAC; read + przypisany recruiter/sourcer; audit eventy |
| `app/api/client_materials.py` | one-pagery: bez viewera; `contract-terms` GET: tylko admin/HoR/DL/TAC |
| `app/api/client_framework_contracts.py` | wszystkie GET-y (lista/szczegół/**download MSA**) przez `LegalDocsReader` |
| `app/api/clients.py` | `ClientSafeResponse` (bez `legal_name`/`nip`/`regon`/`notes`) dla ról bez legal; redakcja finansów `/profile` = mechanizm R0 (`VIEW_FINANCE`); audit update loguje nazwy pól, nie wartości |
| `app/api/my_clients.py`, `my_relationships.py`, `clients_team.py` | multi-role: `has_any_role`/`has_role` |
| `app/schemas/client.py`, `client_profile.py` | rozdzielone projekcje; `active_mrr`/`ltv` nullable |
| `frontend/src/types/client-profile.ts` | typy nullable (`formatPLN(null)` → „—") |
| `.github/workflows/ci.yml` | `tests/test_client_access_matrix.py` w wymaganym jobie |

### Macierz polityki (fail-closed)

| Operacja | admin/HoR | DL/TAC | recruiter/sourcer z Jobem | bez Joba | viewer |
|---|---|---|---|---|---|
| Kontakty read | ✅ | ✅ | ✅ (bez prywatnych notatek) | ❌ | ❌ |
| Kontakty write/delete | ✅ | ✅ | ❌ | ❌ | ❌ |
| Reassign ownera relacji | ✅ | ❌ (claim None→self ✅) | ❌ | ❌ | ❌ |
| Prywatne notatki relacyjne | ✅ | owner ✅ / cudze ❌ / nie-zaklaimowane ✅ | ❌ | ❌ | ❌ |
| Wiedza read / write | ✅ / ✅ | ✅ / ✅ | ✅ / ❌ | ❌ | ❌ |
| One-pagery read | ✅ | ✅ | ✅ | ✅ | ❌ |
| Warunki umów / umowy ramowe (MSA) | ✅ | ✅ | ❌ | ❌ | ❌ |
| Pola prawne klienta (NIP/legal/notes) | ✅ | ✅ | ❌ | ❌ | ❌ |
| Finanse (MRR/LTV/marże) | admin ✅ / HoR ❌ | DL ✅ / TAC ❌ | ❌ | ❌ | ❌ |

Finanse = capability `VIEW_FINANCE` z R0 (admin+DL, multi-role) — bez duplikacji zasad;
`ClientAccess.can_view_financials` deleguje do istniejącego `financial_access` (ten sam zbiór).

## Decyzje wymagające potwierdzenia właściciela produktu

1. **Prywatne notatki relacyjne dla przypisanego DL klienta** — teraz: tylko
   owner + admin/HoR (+ nie-zaklaimowane dla ról edytujących). Rekomendacja
   audytu 19.4 zachowana.
2. **Reassign ownera przez DL** — teraz: tylko admin/HoR.
3. **DL/TAC bez wymogu wpisu w assignments** — świadomie w PR1 (twardy wymóg
   zepsułby quick-add hiring managera z formularza Joba — create Job jest
   `TacPlus` bez bramki per klient). Zacieśnienie per klient = PR2
   (`ClientRelationValidator`).
4. ~~HoR nie przechodzi na `/clients/{id}/profile`~~ — rozwiązane przez R0
   (#769): profil jest `OperationalUser`, HoR widzi część operacyjną,
   finanse nadal redagowane (brak `VIEW_FINANCE`).

## Świadome zmiany zachowania UI

- Recruiter bez Joba u klienta: zakładki Kontakty/Wiedza renderują pusto
  (FE ma defaulty `data = []`; 403 nie crashuje strony).
- Recruiter/viewer: brak NIP/legal/notes w karcie klienta; MRR/LTV w profilu
  jako „—".
- Naprawiony footgun data-loss: nie-zaklaimowane notatki relacyjne
  (owner=None — `KeyRelationshipDialog` historycznie nie ustawiał ownera) są
  widoczne dla ról edytujących; inaczej dialog pokazywałby pustkę i przy
  zapisie wymazywał treść.

## Testy i weryfikacja

- Lokalnie: `ruff check` (backend) ✅, `python3 -m py_compile` ✅,
  `tsc --noEmit` (frontend) ✅, `eslint` zmienionego pliku ✅.
- CI: wymagany job `Backend (ruff + pytest)` zawiera nowy suite
  `tests/test_client_access_matrix.py`; merge wyłącznie po zielonym CI.
- Prod smoke po deployu: `/api/health` z UA `dynaminds-smoke-test/1.0`
  (version = short SHA merge'a) + curl endpointów z parsowanym JSON —
  wynik w komentarzu PR #770.

## Rollback

- Rewert commita przywraca poprzednie zachowanie (brak migracji DB).
- Zapisanych audit eventów nie cofamy.
- Jeśli jakiejś roli brakuje legalnego dostępu → poprawić mapowanie w
  `client_access.py` (jedno miejsce), NIE wracać do gołego `CurrentUser`.

## Następne kroki planu

PR 2/7 — kanoniczny klient (`ClientQueryService`, normalizacja, merge/archive,
`ClientRelationValidator`, kompozytowe FK po preflight). Przed PR 3/4 —
potwierdzić decyzje z sekcji 19 planu.
