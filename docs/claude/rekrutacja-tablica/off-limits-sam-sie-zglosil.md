# Off-limits: „Czy sam(a) się do nas zgłosił(a)?” przy dodaniu do rekrutacji (21.10.2026)

Zespół chciał mieć w NEXUSIE arkusz „Podział klientów i off-limits”. Decyzje
Artura 21.10.2026 (po trzech rundach makiet,
https://claude.ai/artifact/1HLNAApCydpeY1nT8fzLre):

- **Off-limits = firma z co najmniej jednym AKTYWNYM zamówieniem.** Umowy
  z klientami zabraniają aktywnego podbierania ich ludzi. Nikt nie prowadzi
  listy ręcznie; firma wypada sama, gdy kończy się jej ostatnie zamówienie.
  Lista „kto jest czyim klientem / Delivery Lead” i „Zasady współpracy” na
  profilu klienta zostały odrzucone — interesuje nas wyłącznie, z których
  firm nie wyciągamy.
- **Zakazane jest tylko to, że my odzywamy się pierwsi.** Osoba, która sama
  napisała (także na LinkedInie), zaaplikowała albo wcześniej przysłała CV,
  jest w porządku. Także osoba z bazy wymaga przy dodaniu potwierdzenia.
- Stare pola `client_contract_terms.off_limits_*` (usunięte z UI 27.09.2026)
  zostają nieużywane — to nie jest ta funkcja.

## Jak działa

- **Bramka w jednym miejscu:** `transition_process` przy NOWYM procesie, gdy
  dodaje człowiek (`entry_source ∈ HUMAN_ENTRY_SOURCES`, `live_command`),
  pyta `services/client_off_limits.confirm_or_raise`. Bez pytania:
  przepięcie (`reassign`, także wykryte przy `/move`), zgłoszenie do tej
  rekrutacji formularzem (`integration_intake.candidates_with_application_evidence`),
  automat i integracja.
- **„Pracuje teraz”:** `linkedin_current_company`, a gdy go brak — wpis CV
  bez daty końca, który to MÓWI (`company_names.entry_says_current`; sam brak
  dat to artefakt importu z Traffita). Dopasowanie: znormalizowana nazwa firmy
  (`company_names.normalize_company_name`, wspólna z API dla ATLAS-a) zaczyna
  się nazwą klienta całymi słowami (nazwa, wyświetlana, prawna, aliasy
  `client_aliases`); najdłuższa nazwa wygrywa.
- **Potwierdzenie jedzie nagłówkiem** `X-Off-Limits-Confirmation`
  (`{"<id>": "<jak>"}`), czytanym przez `OffLimitsConfirmationMiddleware` do
  zmiennej kontekstu. Dzięki temu każda trasa dodania (proposals/bulk,
  `/pipeline/move`, assign-to-job, shortlist, z LinkedIna, z historii) pyta bez
  zmiany schematu. Nagłówek jest w `allow_headers` CORS.
- **Bez potwierdzenia: 409** `off_limits_confirmation_required` z listą osób
  (`OffLimitsConfirmationRequired` → handler w `main.py`; wyjątek = rollback
  całego żądania). Partia (`add_candidates_to_job`) pyta raz o wszystkie osoby
  przed zapisem; odpowiedź `skip` („Nie, to my się odezwaliśmy”) = osoba
  w `skipped` z powodem `off_limits_declined`, reszta się dodaje.
- **Ślad:** `recruitment_processes.entry_meta["off_limits"]` = klient, firma,
  źródło, sposób, `confirmed_by`, `confirmed_at`. Tablica dostaje
  `entry_off_limits` (`off_limits_badge`): plakietka „Off-limits · sam(a) się
  zgłosił(a)” na karcie i w tabeli osób, ramka w panelu osoby
  (`PersonOffLimits`).
- **Front:** jedno okno na aplikację (`OffLimitsConfirmHost` w root
  layoucie), wołane z interceptora `lib/api.ts`, który ponawia TO SAMO żądanie
  raz. „Nie”/zamknięcie okna = błąd z czytelnym zdaniem
  (`detail.code = off_limits_declined`), pokazywany przez `apiErrorMessage`.
  Wyjątek: partia (`candidate_ids` w ciele), w której są też osoby spoza
  okna — same „Nie” idą nagłówkiem, przycisk mówi „Pomiń te osoby”, a serwer
  wpisuje je do `skipped` i dodaje resztę (audyt 22.10.2026).
  Sposoby zgłoszenia: `lib/off-limits.ts` ↔ `HOW_LABELS` w serwisie.
- **Panel boczny wtyczki LinkedIn** używa `POST /api/extension/candidates`
  oraz `POST /api/extension/candidates/{id}/jobs`, z kluczem wtyczki.
  Przy przypisaniu do rekrutacji brak potwierdzenia off-limits daje
  `409 off_limits_confirmation_required`; całe żądanie jest wycofywane,
  także nowo tworzona osoba. Panel pyta, jak osoba się zgłosiła, i ponawia
  zapis z `off_limits_how` w **ciele żądania** (osoba może jeszcze nie mieć
  identyfikatora). Serwer przenosi tę odpowiedź do tego samego kontekstu
  potwierdzeń co nagłówek. `skip` („Nie, to my”) oznacza zapis tylko do bazy,
  bez nowej rekrutacji. Pozostałe odmowy przypisania, np. weto managera,
  trafiają do `skipped` z powodem.
- Potwierdzenie to deklaracja człowieka (z nazwiskiem i datą), nie zabezpieczenie
  — nagłówek da się wysłać ręcznie; dlatego zostaje ślad przy procesie.
