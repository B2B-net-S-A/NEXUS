# Audyt 06.10.2026 — raport z napraw (przekazanie DL → rekruter, propozycje, wyszukiwanie)

Audyt: `docs/audits/2026-10-06/rekrutacja-przekazanie-i-wyszukiwanie.md`. Decyzje Artura z 06.10:
tak D1, D2, D3, D4, D5, D7, D9; nie D6 i D8; integracja bez `auto_match` → propozycja (chyba że
kandydat aplikował do tej rekrutacji); bez maila o przypisaniu; zamknięcie rekrutacji wygasza propozycje.

## Czeka na Artura

1. **Wypchnięcie commitów scraperów** — `rocketjobs-traffit-scraper` (2973a3e, wcześniej 161b011)
   i `pracuj-traffit-scraper` (bbfe1ba) są tylko lokalnie na Macu: `git push` z tego konta kończy się
   „Repository not found” (brak dostępu do `artur-t-96/*`). Runner launchd używa kodu z dysku, więc
   poprawki już działają; push jest dla kopii w GitHubie.
2. **Rotacja webhooka Slacka scraperów** (S7) — adres był w starych logach `launchd.err.log`. Po
   rotacji mogę wyczyścić stare logi (za Twoją zgodą).
3. **Obsada kategorii** (H5, Head of Recruitment) — 6 kont bez kategorii nie dostaje requestów z automatu.
4. **Numer zamówienia klienta na /jobs/new** — gdy DL wpisze nazwę rekrutacji bez numeru, numer
   odczytany z maila przestaje obowiązywać, a pole prosi o numer. Zostawić tak, czy numer z maila ma
   zostawać? (Jedna linia w `clientReferenceFor`.)
5. **D6 zmieniony przez #2058** — 07.10 w innej sesji zdecydowałeś „każda osoba powyżej progu 70, bez
   limitu 60” i status `expired` po nowszym przeglądzie. Zostawiam to, co jest na mainie; plan z D6 („60
   na noc, bez wygasania”) jest nieaktualny.

## Zmienione

| Część | Stan | Dowód |
|---|---|---|
| PR 1 — dane po scraperze i bramka integracji ([#2055](https://github.com/B2B-net-S-A/NEXUS/pull/2055)) | na prodzie | `/api/health` `cc291f060` |
| Poprawka cofania stawek po scaleniu kandydatów ([#2060](https://github.com/B2B-net-S-A/NEXUS/pull/2060)) | na prodzie | `/api/health` `e5b7fd91c` |
| D4 — karty scrapera | zrobione 07.10 00:55 | 1 159 przeniesionych do „Do przejrzenia”, 1 271 usuniętych z zamkniętych rekrutacji, 0 błędów; 07.10 SQL: 0 otwartych kart integracji w opublikowanych rekrutacjach |
| D5 — stawki scrapera | zrobione 06.10 23:37 UTC | 1 900 cofniętych (konto 244), 2 pominięte (inna waluta); 07.10 SQL: 1 900/1 900 nadal przywrócone, 0 zmian po cofnięciu (także po nocnym odczycie notatek), kolejka „Stawka od” 0 |
| D9 — job JJIT w NEXUSIE wyłączony | na prodzie | `JJIT_ENABLED False` w kontenerze |
| PR 3 — wyszukiwanie z rekrutacji ([#2056](https://github.com/B2B-net-S-A/NEXUS/pull/2056)) | na prodzie | `8cab994c8`; `eval_manual_search_order` (120 rekrutacji): 90,8% rekrutacji z właściwą osobą na 1. stronie, MRR 0,427, mediana 73 (przed: 90,8% / 0,438 / 72); ekran sprawdzony w Chrome |
| D3 — złożony korpus słów kluczowych | na prodzie | `KEYWORD_SEARCH_FOLDED_FTS True`; „c#” jako wiersz wymagań 0,26–0,31 s (przed 5,9 s), „java” 0,28 s, „c#\|.net” 0,30 s |
| PR 2 — przekazanie, propozycje, Champion ([#2061](https://github.com/B2B-net-S-A/NEXUS/pull/2061)) | na prodzie | `/api/health` `75eabfc29` (07.10 02:00 UTC); jednorazowo 172 propozycje w 22 zamkniętych rekrutacjach → `expired` (paragon `job_proposals_closed_jobs_expired_2026_10`), w zamkniętych 0 otwartych; ekrany w Chrome: pulpit „Czeka na Ciebie”, okno „Propozycje z bazy”, edytor „Czego szukamy” (licznik obowiązkowych z krytycznych, „Słowo bardzo ogólne” przy ~18 tys.), krok 1 `/jobs/new` |
| Trivy: `sharp` 0.35.5 i `source-map-js` 1.2.2 ([#2067](https://github.com/B2B-net-S-A/NEXUS/pull/2067)) | na prodzie | pełny bieg CI 37557493657 zielony z Trivy; `ff668e0a3` w wersji z `/api/health` |
| Scraper S3–S9 (repo poza NEXUSEM) | działa lokalnie | testy `tests/test_audit_2026_10_06.py` 7/7, próg 70 w `.env` obu runnerów |

Szczegóły zmian per PR są w opisach PR-ów. W skrócie:
- **PR 1**: tryb `delete` narzędzia kart dla rekrutacji zamkniętych, `&nbsp;` w notatkach automatu,
  `first_seen_at` = data otwarcia procesu; `POST /api/admin/candidates/scraper-rates/revert`
  (z wykluczeniem starej kwoty ze „Stawki od”); bramka integracji (`services/integration_intake.py`):
  żądanie integracji bez `auto_match` → propozycja, chyba że kandydat aplikował do tej rekrutacji;
  zawieszone przebiegi integracji > 6 h → `failed`; nocny odczyt faktów pomija linię „szacunek stawki”.
- **PR 3**: obowiązkowe są wyłącznie umiejętności krytyczne z serwera (`critical_resolution`), ekran
  mówi źródło; jeden punkt za wiersz; fraza przeskakuje nawiasy i przecinki; QC CV po całych słowach;
  nazwiska tylko dla górnego pola; poprawki ekranu „Szukaj ręcznie” (paczki po 100, „Dodano”, Escape,
  fokus); `MUST_GATE_POLICY_VERSION = critical-v10.1`.
- **PR 2**: dzwonek przy każdej ręcznej zmianie rekrutera (jedno miejsce), sekcja „Nowe requesty dla
  Ciebie” w „Czeka na Ciebie” (bez maila), uczestnicy kategorii bez dzwonków (D7), jeden poranny dzwonek
  o propozycjach w dni robocze, wygaszanie propozycji na każdej ścieżce zamknięcia + jednorazowo 172
  w zamkniętych, „Pomiń zaznaczone”, „Przypisz” z listy kandydatów → „Nowi” z blokadą 12 h, Champion bez
  gubienia szkicu i bez nadpisywania cudzych zmian (`expected_profile_hash`), odczyt maila z odmianą
  technologii, limity wierszy, liczba osób wymagana przy przekazaniu.
- **Scraper**: koniec zapisu stawki profilu z oczekiwań miesięcznych, notatka bez „szacunku stawki B2B”,
  tożsamość z panelu aplikującego (kontakt z CV tylko przy zgodnym nazwisku), Traffit po e-mailu
  sprawdza e-mail, ponowienia 5xx (30/60/90 s), licznik płatnych odczytów, `httpx` na WARNING, próg 70.

## Znalezione

- **Górne pole listy w trybie „dosłownie” z „c#” trwa 10–30 s** (podłańcuch `ILIKE '%c#%'` po CV
  i notatkach; trigram nie pomaga przy 2 znakach). W trybie automatycznym nazwy technologii od #2056
  idą jako wiersze wymagań (0,3 s), więc dotyczy tylko jawnego wyboru „dosłownie”. Do osobnej poprawki
  (np. słowo ze słownika technologii w trybie dosłownym → indeks).
- **Trivy był czerwony na każdym PR-ze** od 07.10 (`sharp`), po podbiciu wyszła druga podatność
  (`source-map-js`). Job nie jest wymaganym kontekstem rulesetu, więc nikt tego nie widział.
- Restart Postgresa przy deployach (osobne zadanie, zgłoszone wcześniej).
- **Okno „Propozycje z bazy” dziś pokazuje „Request lub profil punktacji zmienił się”** w części rekrutacji:
  15 z 25 nocnych przeglądów z 07.10 policzono przed wdrożeniem PR 3 (`critical-v9.1`/`v10`, teraz
  `critical-v10.1`). Skrzynka propozycji działa; następna noc przelicza je nową wersją. Przy kolejnym
  podbiciu `MUST_GATE_POLICY_VERSION` warto wdrażać przed oknem 01–05.
- **Licznik kafla i zakładki propozycji różni się do najbliższego przeglądu** (np. 749973: kafel 55,
  zakładka 210) — ostatnia publikacja była jeszcze z limitem 60 sprzed #2058, a zakładka dokleja wiersze
  żywego przeglądu bez limitu.
- **Poranny dzwonek o propozycjach** (8:00–17:00 w dni robocze) — pierwszy wychodzi 07.10 rano; wynik
  dopiszę po odczycie z bazy.
