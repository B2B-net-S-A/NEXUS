# Stawki pary z notatek, gdy etap ich nie ma — raport z wdrożenia

12.10.2026. Reguła: `docs/claude/screening-notatki/stawki-pary-z-notatek-gdy-etap-ich-nie-ma.md`.

## Po co

Delivery Lead zgłosił: chce ponownie wysłać osobę do tego samego klienta,
otwiera rekrutację z września i nie widzi, za ile ją wtedy wysłał — „czy dane
się nie zapisują?”.

## Co pokazał odczyt produkcji (tylko odczyt, przed zmianą)

- Dane były zapisane. Para miała trzy wiersze etapu z Traffita (do „Wysłany
  do Klienta”), wszystkie bez kwot. Oczekiwanie kandydata leżało w karcie
  rekomendacji z notatki rekrutera, a cena wysłania — w notatce Delivery Leada
  napisanej 50 sekund po ruchu, bez przypiętej rekrutacji i z trzema liczbami.
- Import z Traffita nie przenosi stawek (Traffit nie miał takich pól), a oba
  ekrany — profil → „Rekrutacje” i „W tej rekrutacji” w panelu osoby — czytały
  wyłącznie kolumny stawek etapu. Lista propozycji i umowa B2B czytały już
  kartę.
- Skala: z 2 208 par wysłanych do klienta od 07.2026 stawki kandydata na
  etapie nie ma 2 182, w tym 1 762 (81%) mają ją w karcie rekomendacji;
  w całej bazie 8 987 par ma stawkę w karcie i żadnej na etapie. Z 1 531 par
  bez stawki do klienta 583 mają notatkę wysyłającego do 30 minut od ruchu
  (530 do 2 minut). Pomiar B nie zawężał autora do Delivery Leada, więc po
  bramce autora liczba będzie nieco niższa.
- Jednorazowe uzupełnienie stawek do klienta z notatek (03–07.10) tej notatki
  nie wzięło z dwóch powodów naraz: nie ma rekrutacji i nie jest jednoznaczna.

## Co weszło

- **Podpowiedzi, nie stawki** — `services/recruitment_rate_hints.py` niczego
  nie zapisuje. `expected_rate` / `client_rate` zostają puste; obok idą
  `expected_rate_hint` (reguła „W tej rekrutacji” z propozycji) i
  `client_rate_note` (notatka wysyłającego z okolic ruchu na „CV wysłane”).
  Zamówienia i umowy dalej czytają wyłącznie wiersze etapu.
- **Profil → „Rekrutacje”** — `/history` niesie obie podpowiedzi przy każdej
  rekrutacji. Zamiast „—” stoi kwota z karty z dopiskiem, skąd jest
  („Screening (z notatki) · osoba · data”); „Uzupełnij” otwiera pole już
  z tą kwotą i jednostką „/h”. Pod pustą stawką do klienta — „Notatka
  z wysyłki · osoba · data: „…”” i zwykłe „Uzupełnij” z pustym polem.
- **Panel osoby na Tablicy** — `GET /api/candidates/{id}/recruitment-rate-hints`
  (jedno zapytanie na otwartą kartę, tylko gdy stawki brakuje): kwota z karty
  w „W tej rekrutacji” z dopiskiem źródła i wiersz „Do klienta — brak stawki”
  z notatką z wysyłki.
- **Widoczność** — notatka z wysyłki wychodzi wyłącznie do ról, które widzą
  stawkę do klienta (trasa pary nie czyta jej dla innych, `/history` zeruje ją
  razem z `client_rate`). Stawkę kandydata widzi każdy, jak dotąd.
- **Jedna reguła „W tej rekrutacji”** — `candidate_rate_from._newest_by_job`
  dla `this_job_rates` (propozycje, umowa) i nowego `candidate_job_rates`.
- **Przewodnik Jarvisa** `jobs.person` dopisany i przestemplowany; wzorzec
  uprawnień `authz_golden/candidate_rates.json` ma nową trasę z tymi samymi
  literami co `rate-overview`; inwentarze funkcji mają wpisy `r.rate_hints`
  i `dock.rate-hints`.

## Czego świadomie nie ma

- Kwota z notatki nie jest wpisywana do pola stawki do klienta — notatka
  z trzema liczbami nie jest jednoznaczna; czyta ją człowiek.
- Zakończone rekrutacje w profilu nadal nie pokazują wiersza stawek (ani
  podpowiedzi) — tak było przed zmianą.
- Rodzaj zwykłej notatki Delivery Leada z ceną dla klienta (widocznej dla
  rekrutera w „Notatkach”) nie zmienia się w tym PR-ze.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Reguły bez bazy (okno 30 min, autor, rekrutacja, najnowsza wysyłka, zakres kwot, jedna reguła „W tej rekrutacji”) | zielone | `pytest tests/test_recruitment_rate_hints.py` — 23 testy |
| Reguły z bazą (`/history`, trasa pary, rekruter bez notatki, para ze stawkami, 404/422) | sprawdza CI | `tests/test_recruitment_rate_hints_db.py` — 6 testów; lokalnie nie ma Postgresa |
| Strażnicy repo (wzorzec uprawnień, kontrakty tras, indeks reguł, stemple, czytelnicy „Stawki od”) | zielone | 383 testy lokalnie; pozostałe pozycje tych plików wymagają bazy |
| Front: wiersz stawek w profilu i panel osoby | zielone | `npx vitest run` — 11 plików, 498 testów (wiersz stawek 15, panel osoby, harnessy, inwentarze funkcji); `npm run type-check` i `eslint` bez błędów |
| Przeklikanie na harnessach (`/preview/candidate-profile`, `/preview/job-detail`) | zrobione | 1280 × 720: brak przewijania w poziomie, dopiski mieszczą się w karcie (pomiar w DOM); „Uzupełnij” otwiera pole z 90 i „/h”; harness nie wysyła zapytania o podpowiedzi |
| Przegląd kodu (tylko blokery) | bez blokerów | niezależny przegląd diffu; jedna uwaga poniżej progu poprawiona — pole „Uzupełnij” startuje od wartości widocznej teraz, nie z chwili zamontowania (test pada bez poprawki) |
| Przegląd bezpieczeństwa | bez blokerów | notatka z wysyłki ma bramkę `user_can_view_client_rate` w obu ścieżkach i w końcowej redakcji `/history`; z wpisu „X/Y” wychodzi tylko kwota kandydata |

## Po wdrożeniu

1. `/api/health` → `version` = SHA z maina zawierający zmianę.
2. Zgłoszona para przez wdrożoną trasę (token admina mintowany w kontenerze,
   tylko odczyt): `expected_rate_hint` z karty i `client_rate_note` z notatki
   z dnia wysyłki; to samo jako rekruter — bez notatki.
