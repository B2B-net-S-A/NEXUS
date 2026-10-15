# „Stawka od” i historia stawek kandydata (0414, 04.10.2026)

Kandydat podaje różne stawki na różne role (140 zł/h jako DevOps, 80 jako
administrator). Do 0414 filtry, AI i plakietki budżetu czytały
`candidates.expected_rate_hourly` — stawkę zapisaną OSTATNIO; stawki z kart
rekomendacji (8 759 par PLN/h) i etapów nie docierały nigdzie. Pomiar: u 67%
z 991 osób z różnymi stawkami profil był wyższy niż najniższa podana. Decyzje
Artura 04.10.2026 (makiety: https://claude.ai/artifact/SxV3wMXBL8FhA2Q743HwEd).

- **Reguła liczenia jest JEDNA i czysta:** `services/candidate_rate_from.py::compute`.
  Najniższa stawka PLN/h z ostatnich 18 miesięcy (`RATE_FROM_WINDOW_MONTHS`);
  zakres „120–140” liczy się dolną granicą; dzień ÷ 8, miesiąc ÷ 168; inna
  waluta albo brak jednostki = w historii, nie w minimum. Jawne minimum
  (telefon praktykanta, „To jego minimum” w edycji stawki profilu, checkbox
  „To jego nowe minimum” przy „Zweryfikowany”) unieważnia STARSZE NIŻSZE
  stawki. Odstające liczą się jak każde inne — wyłącza je człowiek
  („Nie licz jako minimum”, `candidate_rate_decisions`). Bez stawki w oknie =
  ostatnia znana z `rate_from_stale`. Stawki z umów (co płaciliśmy) są tylko
  w historii — to cena, nie oczekiwanie.
- **Obserwacje** (`candidate_rate_observations.collect`): karty
  (`card:{id}`, pole ręczne wygrywa z notatką), etapy (`stage:{id}`), dziennik
  `profile_rate_changed` (`profile:{activity_id}`; `rate_meaning: minimum`
  albo źródło `trainee_call|manual_minimum|stage_minimum` = jawne minimum),
  bieżąca stawka profilu bez śladu w dzienniku (`profile-current`) i zgłoszenia
  osób z bazy (`apply:{id}`). Karta NIE pisze do profilu (decyzja z 03.10
  zostaje) — wpływa na wartość LICZONĄ.
  Od 07.10.2026 także wpis DL-a „X/Y” w notatce (`note:{id}`,
  `client_rate_notes.dl_pair_from_note` — ta sama reguła i bramka autora co
  plan stawki do klienta; wyzwalacz kolejkuje szerzej, decyduje Python): obserwacją jest WYŁĄCZNIE Y, `raw` =
  „{Y} PLN/h” — X to stawka do klienta, a historię stawek widzi każda rola.
  Wpis powtarzający kwotę etapu albo karty tej rekrutacji nie dubluje
  historii. Kolejkę przelicza wyzwalacz `trg_rate_from_notes` (0423,
  `notes_facts_schema.py`; łapie też surowy SQL Traffita), a zapis, edycja
  i usunięcie notatki w API przeliczają od razu.
- **Wynik w kolumnach `candidates.rate_from_*`, `rate_latest_*`,
  `rate_observation_count`**, zapisywany surowym SQL-em — `updated_at`
  nietknięte, więc alerty zapisanych wyszukiwań nie widzą przeliczenia.
  Wyzwalacze na `recommendation_cards`, `candidate_stages`, stawce profilu
  i `application_submissions` dopisują kandydata do `candidate_rate_from_queue`
  (łapią też surowy SQL Traffita); pętla `candidate_rate_from` (heartbeat)
  opróżnia kolejkę, a zapisy z ekranu przeliczają od razu
  (`recompute_safely`, nigdy nie cofa zapisu użytkownika). SQL ma jedno źródło
  (`candidate_rate_from_schema.py`, entrypoint go importuje).
- **Kolejność w `recompute` jest load-bearing (przegląd kodu 04.10.2026):**
  blokada wierszy kandydatów → odczyt wpisów kolejki z `queued_at` →
  obserwacje → zapis → kasowanie WYŁĄCZNIE wpisów z przeczytaną datą.
  Wyzwalacz przy konflikcie PODBIJA `queued_at` (`clock_timestamp()`), więc
  zmiana zapisana w trakcie przeliczenia zostaje w kolejce. Pętla blokuje
  kandydatów z `SKIP LOCKED` i nigdy nie czeka (bez zakleszczeń z żądaniami).
- **Okno przesuwa się samo:** pętla raz dziennie kolejkuje kandydatów, których
  minimum wypadło z 18 miesięcy (`requeue_expiring`) — wyzwalacze reagują tylko
  na zmiany danych.
- **„Nie licz jako minimum” dotyczy kwoty i daty, nie klucza**
  (`candidate_rate_decisions.observed_amount/observed_at`, `active_exclusions`):
  karta przeliczona z nowej notatki znowu się liczy. Poprawka stawki profilu
  przez tę samą osobę w ciągu 10 minut zastępuje poprzedni wpis (literówka nie
  zostaje minimum). Świeżość stawki (listy praktykantów) czyta datę OSTATNIEJ
  stawki (`rate_latest_at`), nie najniższej.
- **Czytaj przez `effective_rate` / `effective_rate_sql` / `rate_summary`,
  nigdy `expected_rate_hourly` wprost** — przed pierwszym przeliczeniem
  kandydata i przy `CANDIDATE_RATE_FROM_ENABLED=false` obowiązuje stawka
  profilu. Pilnuje `tests/test_rate_from_readers_guard.py` (lista modułów
  piszących i edytujących profil). Filtr „Stawka do”, plakietka budżetu
  (`rate_fit`), ocena (`rate_contract` w `scoring_algorithm_version`), listy
  praktykantów i wymagania ruchu czytają „Stawkę od”.
- **API:** `GET /api/candidates/{id}/rate-overview` (historia z powodami,
  umowy z kwotą tylko przy `can_read_client_finance`), `PUT
  …/rate-observations/{key}` (`exclude|null`), `PATCH …/profile-rate`
  z `is_minimum`, `StageMove.expected_rate_is_minimum`. Odpowiedzi listy,
  podglądu, propozycji i tablicy niosą `rate_from_*`; propozycje dodatkowo
  `rate_this_job_hourly` („W tej rekrutacji”).
- **Front:** `lib/candidate-rate.ts` (opisy), kafel „Stawka od” i okno
  `RateHistoryDialog` w profilu (stary `RateHistoryWidget` usunięty — trasy
  `phase5` zostają, ich wpisy są w historii), lista „od 80 zł/h” + „ostatnio
  140 zł/h”, przegląd DL i dok osoby: „W tej rekrutacji” obok „Stawki od”.
  Okno „Zweryfikowany” podpowiada: karta tej rekrutacji → „Stawka od” → profil.
- **Bez plakietki „na podobne stanowisko”** — Artur ją odrzucił 04.10.2026.

## Żywa umowa (15.10.2026, D4/D5)

- **Dopóki osoba ma żywą umowę (`active`/`ending`) po starcie, w PLN, „Stawka
  od” = stawka konsultanta z tej umowy** (`contract_hourly`, ostatni krok
  harmonogramu do dziś). Obserwacja `contract:{id}`, źródło `contract`;
  `compute` ma dla niej gałąź przed regułą minimum: niezależnie od okna
  18 mies., `stale = false`, `latest_*` = umowa, pozostałe obserwacje z powodem
  `contract` („pracuje u nas — liczy się umowa”). Kilka żywych umów — ta
  z najpóźniej obowiązującą stawką (remis: wyższa).
- **Dlaczego nadpisanie, a nie „jawne minimum”:** stawka profilu
  (`profile-current`) ma datę importu, późniejszą niż start umowy, więc jako
  „nowsza” dalej wygrywała — u większości z 99 osób nic by się nie zmieniło.
- **Po końcu umowy** wracamy do reguły wyżej: zakończone umowy są tylko
  w historii („to cena, nie oczekiwanie”).
- **Kolejka:** wyzwalacze `trg_rate_from_contracts` (status, osoba, start,
  pola stawki kosztowej — warunki w ciele funkcji, bez `UPDATE OF`, bo
  entrypoint poszerza kolumny stawek) i `trg_rate_from_contract_rates`
  (`contract_candidate_rates`); migracja 0448 + lustro w `entrypoint.sh`
  (`services/contract_rate_from_schema.py`, po `_RATE_FROM_DDL`). Kalendarz
  (start umowy, krok harmonogramu) przelicza pętla raz dziennie:
  `requeue_live_contracts` kolejkuje wszystkie osoby z żywą umową;
  `requeue_expiring` je pomija.
- **`with_contracts=False`** w `collect` dla `this_job_rates` /
  `candidate_job_rates` — obserwacja z umowy nie ma rekrutacji (`job_id`
  pusty, więc „W tej rekrutacji” i podpowiedź umowy B2B jej nie biorą).
- „Nie licz jako minimum” nie działa dla klucza `contract:` (`_KEY_PATTERN`
  go odrzuca, przycisk ukryty). Kto widzi kwotę — `kandydaci-wyszukiwanie/znacznik-pracuje-u-nas.md`,
  sekcja „Dostępność i stawka z umowy”.
