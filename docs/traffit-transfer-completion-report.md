# Przeniesienie rekrutacji z Traffita do NEXUSA falami — raport z wdrożenia

11.10.2026. Reguły: `docs/claude/integracje/przeniesienie-rekrutacji-z-traffita-falami.md`.

## Po co

Zespół zgłosił, że chce widzieć w NEXUSIE wszystkich swoich kandydatów ze
wszystkich otwartych rekrutacji z Traffita „na odpowiednich polach”. Pomiar na
produkcji pokazał, że dane już tam są — nie widać ich, bo rekrutacje z Traffita
są w NEXUSIE zamknięte jako archiwum, a praca toczy się w Traffit.

## Pomiar (produkcja, 11.10.2026, tylko odczyt)

| Co | Liczba |
|---|---|
| Rekrutacje otwarte w Traffit (bez daty zamknięcia) | 323 |
| …z ruchem z Traffita w ostatnich 30 dniach | 186 (45 założonych w Traffit po 25.09) |
| Osoby na 185 z nich (bez worka „projekty wewnętrzne”) | 6 310 |
| Zgodne z Traffitem co do stanu | 6 258 (99,2%) |
| Inny stan — remis czasu dwóch wpisów historii | 34 |
| Brak karty w NEXUSIE | 9 |
| Karty osób zdjętych z rekrutacji w Traffit | 114 |
| Ruchy w 7 dniach: Traffit / NEXUS | 2 068 / 89 |
| Rekrutacje założone w NEXUSIE po 25.09 z bliźniakiem w Traffit | 45 z 73 |

Porównanie liczone z listy osób per stan
(`/recruitments/{id}/states/{stan}/employees`), nie z historii ruchów.

## Decyzje właściciela (11.10.2026)

- Przeniesienie jednorazowe, falami — nie lustro „na żywo”.
- „Otwarta” = bez daty zamknięcia w Traffit i z ruchem z Traffita w 30 dniach.
- Karty osób zdjętych w Traffit schodzą z Tablicy ze śladem w historii.
- Pilot: jeden klient bez bliźniaków (10 rekrutacji, 354 osoby), 14.10.2026.
- Bliźniaki (która z dwóch rekrutacji zostaje) — po pilocie.

## Co weszło

- `backend/app/services/traffit_transfer_plan.py` — plan jednej rekrutacji
  (czysta funkcja): zgodni, remis do wysunięcia, wiersz do dopisania, karta do
  zdjęcia, ruch NEXUSA na wierzchu, karty tylko NEXUSA, karty już zamknięte,
  osoby nieznane.
- `backend/app/services/recruitment_process_commands.py` —
  `promote_external_stage_row` i `note_external_stage_row`: jedyne dwa zapisy
  istniejących wierszy etapów, przez warstwę komend.
- `backend/app/services/traffit_transfer.py` — fala, lista osób per stan
  z Traffita, raport próby, wykonanie (poprawki + otwarcie funkcjami
  „Otwórz ponownie”), paragon, bieg w tle pod blokadą syncu.
- `backend/app/api/admin_traffit.py` — `POST /api/admin/traffit/transfer`,
  `GET /api/admin/traffit/transfer/status` (admin albo klucz `traffit:sync` /
  `traffit:read`; wykonanie wyłącznie zalogowany administrator).
- Wzorzec bramek `tests/data/authz_golden/admin_traffit.json` — dwie nowe trasy,
  ten sam werdykt co pozostałe trasy Traffita.
- Bez migracji i bez zmian schematu.

## Przegląd kodu przed scaleniem

Niezależny przegląd znalazł dwie rzeczy blokujące, obie poprawione: surowy
`UPDATE candidate_stages` poza adapterem Traffita (strażnik architektury byłby
czerwony w kolejce) oraz zdejmowanie kart już zamkniętych — osoba zatrudniona,
zdjęta potem z rekrutacji w Traffit, dostałaby „Wycofany”. Pusta lista osób
z Traffita jest teraz traktowana jak niekompletna.

## Świadome odstępstwa

- **Osoba zdjęta w Traffit dostaje wiersz „Wycofany”, a nie jest usuwana
  z rekrutacji.** Usunięcie pary kasuje jej wiersze etapów (historię liczoną
  w KPI) i nie ma cofnięcia. Karta schodzi z ośmiu kolumn do „Zamkniętych”.
- **Przeniesienie nie przechodzi bramki braków „Otwórz ponownie”.** Żadna
  z rekrutacji pilota nie ma hiring managera, dziewięć nie ma terminu; raport
  próby wypisuje braki per rekrutacja.
- **Rekrutacje z bliźniakiem w NEXUSIE są pomijane** do czasu decyzji.

## Testy

| Plik | Zakres | Gdzie |
|---|---|---|
| `tests/test_traffit_transfer_plan.py` | 18 przypadków planu, bliźniaków, klucza fali i kolumn | lokalnie i CI |
| `tests/test_priority_work_writer_architecture.py` | zapis wierszy etapów tylko przez warstwę komend | lokalnie i CI |
| `tests/test_traffit_transfer.py` | próba bez zmian; wykonanie (remis, brakujący wiersz, zdjęta osoba, ruch NEXUSA, otwarcie, historia); niekompletna lista; bliźniak; brak wykonawcy; świeżość próby | tylko CI (Postgres) |
| `tests/test_authz_guard_matrix.py` | wzorzec bramek z nowymi trasami | lokalnie i CI |

## Co wywoła otwarcie fali pilota

Jeden prowadzący (zarazem Delivery Lead) dostanie 10 dzwonków „Nowy request do
pracy”. Przypomnienia o zaległych kartach z Traffita (10 × „CV wysłane czeka”
i do 136 × „utknął na etapie”) zostały wyciszone osobną zmianą: etap z importu
Traffita budzi dopiero po pierwszym ruchu karty w NEXUSIE (decyzja Artura
11.10.2026, `notification_triggers._set_in_nexus`,
`tests/test_notification_triggers.py`).

## Migracja całego zespołu — 12.10.2026

Decyzja Artura 12.10.2026: nie pilot, tylko cały zespół od razu; od 13.10
jedynym źródłem prawdy jest NEXUS, a przypisane osoby mają się nie zmieniać.
Biegi wykonane przez wdrożoną trasę na koncie administratora:

| Bieg (UTC) | Co | Wynik |
|---|---|---|
| 07:23–08:01 | rekrutacje bez bliźniaka | 133 otwarte; 20 wysuniętych wierszy, 7 dopisanych, 94 osoby zdjęte w Traffit → „Wycofany”; 49 bliźniaków i worek pominięte |
| 08:32–08:35 | karty scrapera → propozycje na tych rekrutacjach | 1 416 przeniesionych (79 rekrutacji), 0 błędów, 7 pominiętych (ktoś już nad nimi pracował) |

Błędy pierwszego biegu i poprawki (#2130 i następny PR):

- Osoba odpowiedzialna z Traffita to zwykle Delivery Lead; po otwarciu została
  policzona jako rekruter (103 ze 133 rekrutacji, „Obłożenie”). Naprawa:
  `_settle_owner` + `repair_transferred_owners`.
- Automat wpisał głównego DL-a klienta zamiast DL-a prowadzącego rekrutację
  (35 rekrutacji jednej osoby). Naprawa: DL z Traffita zastępuje DL-a
  z automatu.
- Cztery rekrutacje przełączone ręcznie w trakcie biegu zostały zamknięte.
  Naprawa: fala wskazana wprost je otwiera.
- Pewność bliźniaka liczona bez numeru requestu dawała cudzy zespół ośmiu
  kopiom. Naprawa: `assign_twins`.

Kolejne biegi tego dnia (po #2130 i #2132):

| Bieg (UTC) | Co | Wynik |
|---|---|---|
| 09:24–09:37 | 28 kopii z pewnym bliźniakiem (z zespołem rekrutacji NEXUSA), 13 z podobnym tytułem, 3 przełączone ręcznie | 44 otwarte |
| 10:06–10:09 | 8 kopii, których tytuł pasował do cudzego numeru requestu — bez zmiany zespołu | 8 otwartych |
| po biegach | naprawa prowadzących, karty scrapera → propozycje | 103 rekrutacje bez Delivery Leada w roli rekrutera; 2 047 kart przeniesionych łącznie |

Stan po migracji: 185 rekrutacji przeniesionych, jedyna aktywna
nieprzeniesiona to worek zgłoszeń „projekty wewnętrzne”.

## Scalenie duplikatów — 12.10.2026

28 requestów stało na liście dwa razy: kopia z Traffita (kandydaci) i
rekrutacja założona w NEXUSIE (zespół, Profil Championa, propozycje). Pomiar
przed budową (produkcja, tylko odczyt): w kopiach 870 osób z kartą, z czego 10
ma kartę także w rekrutacji NEXUSA; 13 ma tam unieważniony proces po karcie ze
scrapera; na kopiach 343 otwarte propozycje (214 zgłoszeń z ogłoszeń); jedna
z 28 rekrutacji NEXUSA jest zamknięta.

Co weszło:

- `backend/app/services/job_twin_merge.py` — pary z paragonów przeniesienia,
  próba (raport per para), wykonanie (para we własnej transakcji), paragon
  z id przeniesionych kandydatów; raport w
  `app_settings['traffit_twins_merge_dry_run']`, paragon w
  `…['traffit_twins_merge_log']`.
- `recruitment_process_commands.move_pairs_to_job` — przepięcie wierszy etapów
  i procesów pary (jedyne miejsce, które wolno ruszać te wiersze).
- `job_proposals.move_open_to_job` — otwarte propozycje kopii przechodzą.
- `backend/app/api/admin_traffit.py` — `POST /api/admin/traffit/twins-merge`,
  `GET …/twins-merge/status`; ten sam werdykt bramek co przeniesienie.
- Bez migracji i bez zmian schematu.

Niezależny przegląd kodu przed scaleniem wskazał dwie rzeczy blokujące, obie
sprawdzone na produkcji (tylko odczyt) i poprawione:

- Lista tabel idących za osobą nie miała terminów rozmów, prepów, feedbacku,
  zaplanowanych maili odmowy ani wykluczeń placementów — bramka debriefu
  i wysyłka maila zgubiłyby parę. Na 28 kopiach było w nich 0 wierszy; tabele
  dopisane, bo ludzie pracują w kopiach na bieżąco.
- Unieważniony proces rekrutacji NEXUSA mógłby zabrać kredyt KPI kamieniom
  milowym kopii. U wszystkich 13 osób z takim procesem proces z Traffita
  otworzył się wcześniej, więc 0 kamieni wpadało w lukę; narzędzie dostało
  strażnika (`kpi_hold`).

Z uwag nieblokujących weszły: scalona kopia nie wraca do fali przeniesienia,
paragon przy kopii w transakcji pary, wykonanie tylko par z próby, przepięcie
nie rusza `updated_at`.

Świadome wybory: osoba z kartą w obu rekrutacjach nie jest przenoszona;
kopia zamyka się bez daty i powodu zamknięcia (nie jest zamkniętym requestem);
zespół rekrutacji NEXUSA się nie zmienia; zamknięta rekrutacja NEXUSA nie
przyjmuje ludzi — tę parę rozstrzyga Delivery Lead.

| Plik | Zakres | Gdzie |
|---|---|---|
| `tests/test_job_twin_merge_plan.py` | kiedy para jest parą, powody pominięcia, lista tabel idących za osobą, zakres trasy | lokalnie i CI |
| `tests/test_job_twin_merge.py` | próba bez zmian; przepięcie z historią, numery prób, notatki, karta, termin rozmowy, „Stawka od”, propozycje i ich notatki, `updated_at` bez zmian, zamknięcie kopii, przypisania, zespół bez zmian, paragon przy kopii, scalona kopia poza falą; osoba wstrzymana przez kredyt KPI; tylko pary z próby; zamknięta rekrutacja NEXUSA; podobny tytuł; brak wykonawcy; kopia zamknięta przez człowieka; świeżość próby | tylko CI (Postgres) |

### Bieg scalenia na produkcji (12.10.2026, konto administratora)

Próba 11:57 UTC, wykonanie po decyzji Artura („Scal teraz”): para próbna
o 12:00:14 UTC, pozostałe 26 par 12:01:05–12:01:35 UTC.

| Co | Liczba |
|---|---|
| Pary scalone / nieudane | 27 / 0 |
| Para pominięta | 1 — rekrutację NEXUSA zamknął tego dnia Delivery Lead, zostaje kopia |
| Osoby przeniesione z historią | 825 |
| Osoby z kartą w obu rekrutacjach (nieprzenoszone) | 16 |
| Osoby wstrzymane przez kredyt KPI | 0 |
| Notatki / karty rekomendacji / wygenerowane CV | 744 / 132 / 36 |
| Otwarte propozycje przeniesione | 302 |

Sprawdzenie po biegu (produkcja, tylko odczyt): wiersze etapów, procesy
i notatki w parach przed i po — 2312 / 1928 / 1588, bez zmian; zespoły 28
rekrutacji NEXUSA (prowadzący, DL, współpracownicy, przypisania) bez zmian;
kredyt KPI (`VERIFIER_ANCHORED_CTE`) 456 → 458 wierszy, żaden nie ubył, dwa
nowe z pracy rekrutera tego dnia; Tablica scalonych rekrutacji przez API
zgodna z kolumnami z próby. Paragon: `app_settings['traffit_twins_merge_log']`
i wpis `traffit_twin_merged` przy każdej kopii.

## Nocny import z Traffita wyłączony — 12.10.2026

Decyzja Artura po scaleniu: z Traffita nikt już nie korzysta, import nie jest
potrzebny. `TRAFFIT_SYNC_ENABLED=false` (12:17 UTC) i plik stop starego crona
na hoście. Co stanęło razem z importem, co zostało tylko w Traffit i jak zrobić
ostatni import przed rezygnacją z Traffita:
`docs/claude/integracje/traffit-daily-sync-scheduled-import.md`.

## Niepotwierdzone / poza zakresem

- Remis czasu w imporcie dotyczy wszystkich rekrutacji z Traffita; ta zmiana
  poprawia go tylko dla przenoszonych.
- Przyczyna 9 brakujących kart nie jest ustalona (kandydat istnieje, wpisu
  historii w NEXUSIE nie ma) — przeniesienie dopisuje wiersz.
- 2 055 kart scrapera (`posting`) na 104 rekrutacjach zbioru — po otwarciu
  trafią do „Nowych” jako „Z ogłoszenia”. Decyzja Artura 11.10.2026: u klienta
  pilota (80 kart) przenieść je do propozycji; narzędzie
  `convert-integration-cards` dostało zawężenie `job_ids`, rekrutacje
  „Prowadzone w NEXUSIE” i karty scrapera sprzed oznaczania wpisów. Bieg po
  otwarciu fali.
- Ekran w Ustawieniach dla przeniesienia i scalania — narzędzia działają przez trasy administratora.
- 13 kopii z podobnym tytułem i 8 z cudzym numerem requestu nie jest scalanych — to mogą być różne requesty; rozstrzyga Delivery Lead.
