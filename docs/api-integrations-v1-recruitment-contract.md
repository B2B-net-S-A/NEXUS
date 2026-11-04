# API v1 — rekrutacja i kandydaci: kontrakt dla budowy (15.10.2026)

Stan: zbudowane — opis dla integratora w `docs/api/integracje-v1.md`
(sekcje „Rekrutacje”, „Kandydaci”, „Rekrutacje — zapis”).

Decyzja Artura 15.10.2026: API integracyjne v1 obejmuje też rekrutację i kandydatów,
z odczytem i zapisem. Ten plik jest wspólnym kontraktem dla czterech równoległych
modułów; po wdrożeniu jego treść trafia do `docs/api/integracje-v1.md`.

## Scope'y (`app/models/service_account.py`)

| Scope | Co otwiera |
|---|---|
| `recruitments:read` | lista i szczegóły rekrutacji, wymagania (Champion), Tablica (karty), historia ruchów, kolumny |
| `recruitments:write` | dodanie osoby do rekrutacji, przesunięcie karty (obejmuje `recruitments:read`) |
| `candidates:read` | lista i profil kandydata BEZ danych kontaktowych |
| `candidates:contact` | pola kontaktowe w profilu: e-mail, telefon, LinkedIn, NIP/REGON/nazwa firmy (bez niego `null` i `contact_redacted: true`) |
| `candidates:cv` | lista plików kandydata, pobranie pliku, tekst CV |
| `candidates:write` | nowy kandydat, wgranie CV (obejmuje `candidates:read`) |
| `notes:read` | notatki, odpowiedzi screeningu, karta rekomendacji |
| `notes:write` | nowa notatka (obejmuje `notes:read`) |

Aliasy zależności: `common.py` — `RecruitmentsRead`, `RecruitmentsWrite`, `CandidatesRead`,
`CandidatesCv`, `CandidatesWrite`, `NotesRead`, `NotesWrite`; pola: `sees_candidate_contact(caller)`,
`reads_candidate_cv(caller)`, `amount_level(caller)`.

## Kwoty

- Oczekiwania kandydata (`salary_expectation`, `expected_rate_hourly`, `rate_from_hourly`,
  `rate_latest_hourly`), budżet rekrutacji dla kandydata (`rate_budget_hourly*`,
  `effective_budget_hourly*`, `salary_min/max`, stawka Championa), `expected_rate_*`
  i `budget_max_at_move` na kartach — **koszt**: tylko `AmountLevel.all`.
- Stawka do klienta na karcie (`client_rate_*`) — **sprzedaż**: `AmountLevel.sales` i wyżej.
- Pole schowane = `null`; obiekt ma `amounts_redacted` / `costs_redacted` jak w zamówieniach.

## Zasady wspólne

- Moduły bez `from __future__ import annotations`; każda trasa z `@limiter.limit(read_rate_limit
  | write_rate_limit, key_func=principal_rate_key)` i docstringiem; router
  `APIRouter(route_class=IntegrationRoute)`; błędy przez `IntegrationApiError` /
  `HTTPException` (koperta v1); stronicowanie `PageQuery`, `PageSizeQuery`, `page_of`.
- Zapis: `idempotent_write` (`Idempotency-Key`), body bez `commit()` w środku — commit po
  paragonie; efekty po commicie (powiadomienia, broadcast, zadania w tle) po commicie.
- Autor: `IntegrationActor` (bez ról, bez id). `user_activities.user_id` jest NOT NULL —
  zapis z klucza NIE tworzy `UserActivity` (to ranking ludzi). `Activity.user_id`,
  `notes.author_id`, `candidates.created_by`, `candidate_stages.moved_by`,
  `candidate_documents.uploaded_by` są nullable — zapis `None`, a `details.via` dopisuje
  stempel sesji (`integration:<slug>`).
- Bramki ról ekranu (`has_any_role`, `has_permission`) NIE dostają `IntegrationActor`
  — o tym, co wolno kluczowi, decydują scope'y; reguły biznesowe (QC, „Zweryfikowany”,
  screening, 12 h dla ludzi, eligibility, blacklista) zostają te same.
- `candidate_claim.is_integration_request(request)` zwraca `True` także dla klucza API:
  osoba, która się nie zgłosiła do rekrutacji, trafia do propozycji; notatka z klucza
  to notatka systemowa; bez 12 h blokady.
- Dane osobowe: odczyt pliku CV przez klucz zapisuje ślad w `candidate_audit`
  (jak pobranie na ekranie); pozostałe odczyty ślad ma w logu żądań (`actor`).
- Bez kandydatów w kwarantannie tożsamości i bez skasowanych (purged).

## Poza tym PR-em

Zakładanie rekrutacji z requestu (`/jobs/new`, łańcuch `job_lifecycle` z AI),
generowanie CV, kalendarz rozmów, Insights, Akademia, zgłoszenia z linku (akceptacja).
