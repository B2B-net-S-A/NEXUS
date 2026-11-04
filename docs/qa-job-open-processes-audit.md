# Otwarte procesy na zamkniętej rekrutacji QA 603652 — audyt (20.10.2026)

Odczyt produkcji wyłącznie read-only (`SET default_transaction_read_only = on`,
zgoda Artura w sesji), zapytania o id, liczby i daty. Nic nie zostało zmienione.
Raport bez nazwisk — repo jest publiczne.

## W skrócie

- **Skąd karty:** 479 kart w „Ogłoszeniach” na rekrutacji QA 603652 (i 36 na
  603653) to karty **scrapera Pracuj.pl / RocketJobs** z 16–23.09.2026. Konto 244
  to użytkownik serwisowy klienta OAuth „Scrapery pracuj.pl + JJIT” (rola
  `talent_community_manager` nadana kontu serwisowemu), nie człowiek.
- **Dlaczego zostały:** sprzątanie kart scrapera z 06.10.2026 (`mode=delete`,
  1 271 kart) znało tylko karty oznaczone `entry_source='auto_match'`. Karty
  z 16–23.09 są sprzed oznaczania (`entry_source` puste albo `added_manual`).
  Rozpoznawanie ich dopisano 11.10.2026 (#2125), ale **tylko w trybie
  `convert`** — tryb `delete` wycina je celowo powodem `untagged_scraper_card`.
- **Zamknięcie rekrutacji nie zamyka procesów — z założenia** (reguła
  `rekrutacja-tablica/zamkniecie-rekrutacji-osoby-w-toku.md`, 13.10.2026:
  ostrzeżenie 409 `active_cards_warning`, potem zamknięcie „jak dotąd”, karty
  zostają). To nie jest pojedynczy błąd QA: **73 zamknięte rekrutacje
  z NEXUSA mają 4 835 otwartych procesów**, z czego **4 006 to nietknięte karty
  scrapera** w 24 rekrutacjach.

## 1. Skąd konto 244 wrzuciło karty

| Fakt | Wartość |
|---|---|
| Konto 244 | założone 16.09.2026, aktywne, rola `talent_community_manager`, adres w domenie firmy o kształcie konta serwisowego; jest `acting_user_id` klienta OAuth (`oauth_clients`) |
| Wszystkie wiersze etapu konta 244 | 7 600, **wyłącznie `posting`**, 159 rekrutacji, 16.09–04.10.2026 |
| `activities` konta 244 | tylko akcje automatu: `snapshot_created` (CV etapu) 12 083, `cv_uploaded` 5 849, `updated` 5 398, `created_from_cv` 4 276, `profile_rate_changed` 1 903 — żadnych ruchów ręcznych |
| Godziny wstawiania na 603652 | seriami całą dobę, także 02:00–04:00 i 20:00–22:00; mediana odstępu między kartami 114 s, 10. percentyl 10 s |
| Notatki automatu | 458 z 460 procesów bez `entry_source` i 19 z 20 `added_manual` ma notatkę `kind='automatch'` z „Auto-match score:” |
| `candidate_source_events` na 603652/603653 | 0 |

Mechanizm (repo scrapera poza NEXUSEM, `pracuj-traffit-scraper/nexus_pipeline.py`):
po wgraniu CV scraper pyta `GET /api/candidates/{id}/recommendations?only_open=true`
i dla każdej rekrutacji z wynikiem ≥ progu oraz statusem `published` woła
`POST /api/jobs/{job_id}/proposals/bulk`. Do 05.10 bez pola `auto_match`, więc
serwer zakładał kartę w „Ogłoszeniach” zamiast propozycji. Rekrutacja QA 603652
była wtedy opublikowana (zamknięta 24.09.2026 przez konto 82), więc rekomendacje
podsuwały ją jak każdą inną — ostatnia karta 23.09, dzień przed zamknięciem.

Na 603652 jest jeszcze jedna osoba dodana ręcznie przez konto 82 (14.10, `new` →
`screening`) i 33 procesy `voided` — to karty `auto_match` usunięte sprzątaniem
06.10 (33 × `removed_from_recruitment`).

## 2. Procesy na klientach QA

| Rekrutacja | Status | Procesy otwarte | z tego karty scrapera (1 etap `posting`, notatka automatu) | Inne |
|---|---|---|---|---|
| 603652 (klient 64636) | closed | 480 | 477 (458 bez `entry_source`, 19 `added_manual`) | 2 bez notatki automatu, 1 karta ręczna konta 82 |
| 603653 (klient 64637) | closed | 36 | 36 | — |
| 680768 (QA) | closed | 27 | (nie badane szczegółowo) | 3 closed, 36 voided |
| 680769, 693761 (QA) | closed | 1 + 1 | (nie badane) | |

451 osób z otwartym procesem na 603652/603653 nie ma żadnego innego otwartego
procesu w opublikowanej rekrutacji.

## 3. Skala poza QA

Otwarte procesy według statusu rekrutacji:

| Rekrutacja | Rekrutacje | Otwarte procesy |
|---|---|---|
| opublikowana | 190 | 3 351 |
| zamknięta, z NEXUSA (albo z Traffita „Prowadzona w NEXUSIE”) | 73 | 4 835 |
| zamknięta, archiwum Traffita | 3 723 | 58 881 |

Zamknięte rekrutacje z NEXUSA — co stoi w otwartych procesach:

| Rodzaj | Procesy | Rekrutacje | Osoby |
|---|---|---|---|
| Karta scrapera (ostatni etap `posting` od konta integracji) | 4 006 | 24 | 2 710 |
| Pozostałe (`new` 343, `screening` 282, `cv_sent` 130, `interview` 34, `verified` 27, `client_interview` 7, `acceptance` 5, `rejected` 1) | 829 | 55 | 762 |

Karty scrapera na zamkniętych rekrutacjach z NEXUSA wg kryteriów narzędzia:

| `entry_source` | notatka automatu z wynikiem | inne notatki | jeden etap | Procesy | Daty kart |
|---|---|---|---|---|---|
| puste | tak | nie | tak | 3 852 | 16–22.09 |
| `added_manual` | tak | nie | tak | 129 | 23.09 |
| puste | nie | nie | tak | 23 | 16.09 |
| `auto_match` | tak | nie / tak | tak | 1 + 1 | 29.09, 04.10 |

Czyli 3 981 kart scrapera spełnia dziś bazę narzędzia (trzecia gałąź z #2125)
i odpada w trybie `delete` wyłącznie powodem `untagged_scraper_card`. Największe
rekrutacje: 5 (876 otwartych procesów), 603652 (480), 2 (473), 6 (452), 13 (376),
1 (353), 3 (344).

Do archiwum Traffita (58 881) ten raport się nie odnosi — tam otwarte procesy to
lustro stanu z Traffita, a fale przenoszone do NEXUSA mają zostać propozycjami
(powód wycięcia w `job_board_cards_to_proposals._UNTAGGED_CARD`).

## 4. Gdzie otwarte procesy na zamkniętej rekrutacji są widoczne

Wszystkie otwarte procesy QA (i 4 006 kart scrapera na zamkniętych rekrutacjach
z NEXUSA) mają `owner_user_id = opened_by_user_id = 244` (konto serwisowe),
`credit_user_id` puste, `priority_compliant_at_open` puste, `kpi_eligible = true`,
`origin_kind = assigned`, stan `identified`.

| Miejsce | Czy widać / liczy się | Dowód |
|---|---|---|
| Lista kandydatów: kolumna „W procesie” i filtr „bez procesu w toku” | **Nie** — reguła pomija rekrutacje zamknięte | `services/candidate_recruitment_filter.py:84` (`Job.status != JobStatus.closed`) |
| Lista kandydatów: „Brał udział” i zakres po kliencie / rekrutacji | **Tak** — liczy każdy wiersz etapu, także na zamkniętej. 99 osób „brało udział” wyłącznie przez kartę scrapera na QA | `candidate_recruitment_filter.py:80` (`_in_any_recruitment`), `scope_clause` |
| Tablica rekrutacji 603652 | **Tak**, po otwarciu zamkniętej rekrutacji — 477 kart w kolumnie „Nowi” (`posting` → „Nowi”) | `services/board_stage_badges.py:163` |
| Ostrzeżenie przy zamykaniu | Liczyłoby te karty jako „w toku” (dla zamkniętej rekrutacji już bez znaczenia) | `services/job_active_cards.py:30` |
| Priority Work — „Przeniesione” (carry-over) | Zapytanie nie filtruje statusu rekrutacji, ale właścicielem jest konto 244, które nie ma roli rekrutera, więc nie ma go w `/api/priority-work/team`, a jako aktywne nie trafia do „bez właściciela” | `services/priority_work_service.py:944`, `api/priority_work.py:622` |
| Obłożenie (workforce availability) | **Nie** — zamknięta rekrutacja liczy się tylko przez proces z `priority_compliant_at_open = true` | `services/workforce_availability.py:373` |
| KPI, Liga, Insights | Liczą kamienie milowe par, nie status procesu; zamknięcie procesów historii nie zmieni. Karty mają tylko `posting`, a kredyt szedłby na konto 244. Czy `posting` konta serwisowego wchodzi w jakiś licznik, **niepotwierdzone** (sprawdzone `kpi_panel.py:215–300`, nie sprawdzone liczniki „Pozyskani”) | `services/kpi_panel.py:231` |
| Dzwonki | **Nie** — 0 powiadomień z linkiem do 603652/603653 | `notifications.link` |

Wniosek: dla ludzi te procesy są dziś prawie niewidoczne. Przeszkadzają w trzech
miejscach: „Brał udział” na liście kandydatów, Tablica zamkniętej rekrutacji
i każdy przyszły odczyt, który weźmie `recruitment_processes.status = 'open'`
bez statusu rekrutacji (np. carry-over po zmianie właściciela).

## 5. Czy zamknięcie powinno było zamknąć procesy

Według obowiązującej reguły (13.10.2026) — nie: zamknięcie ostrzega o osobach
w toku i zamyka rekrutację, karty zostają, bo są historią pary. Ostrzeżenie
liczy wyłącznie karty poza „Zamknięci” i „Zatrudniony”; etap `posting` trafia
na Tablicy do kolumny „Nowi” (`board_stage_badges.py:163`), więc karty scrapera
też wywołują ostrzeżenie. QA 603652 zamknięto 24.09, przed tą regułą, bez ostrzeżenia.

Błąd nie leży więc w zamykaniu, tylko w tym, że:

1. sprzątanie kart scrapera na zamkniętych rekrutacjach z NEXUSA nie objęło
   kart sprzed 23.09 (luka między #2055 z 06.10 a #2125 z 11.10);
2. odczyty, które traktują `recruitment_processes.status='open'` jako „w procesie”
   bez sprawdzenia statusu rekrutacji (sekcja 4).

## Warianty naprawy (do decyzji Artura)

Wstępne liczby (filtr przybliżony, bez sprawdzenia FK — dokładne poda próba
na sucho narzędzia):

| Zbiór | Rekrutacje | Karty |
|---|---|---|
| QA 603652 + 603653 | 2 | 513 |
| inne zamknięte rekrutacje założone w NEXUSIE | 17 | 3 419 |
| zamknięte rekrutacje z Traffita „Prowadzona w NEXUSIE” | 2 | 49 |

- **A. Domknąć lukę narzędzia (rekomendowane).** W `job_board_cards_to_proposals`
  tryb `delete` przyjmuje karty scrapera sprzed oznaczania (trzecia gałąź bazy)
  na zamkniętych rekrutacjach **założonych w NEXUSIE** (`external_source` różne
  od `traffit`); fale z Traffita zostają przy `convert`. Potem po wdrożeniu
  (okno 19:00) próba na sucho i zapis przez istniejące
  `POST /api/admin/proposals/convert-integration-cards?mode=delete`. Karta znika
  drogą „Usuń z rekrutacji” (archiwum `candidate_stage_removals`, proces
  `voided`, dane do odwrócenia), ok. 3 932 karty w 19 rekrutacjach, w tym 513 QA.
- **B. Tylko QA.** Ta sama zmiana kodu, ale bieg zawężony `job_ids=603652,603653`
  (513 kart). Reszta 3 419 kart zostaje do osobnej decyzji.
- **C. Zostawić.** Procesy nie liczą się w „W procesie”, obłożeniu ani dzwonkach;
  zostaje „Brał udział” dla 99 osób i 477 kart na Tablicy zamkniętej rekrutacji.

Nie proponuję zamykania procesów przy zamknięciu rekrutacji: obowiązująca reguła
(13.10.2026) celowo zostawia karty jako historię pary, a 829 pozostałych otwartych
procesów na zamkniętych rekrutacjach to prawdziwe osoby w toku (`new`, `screening`,
`cv_sent`…), o których decydują ludzie.
