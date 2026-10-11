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
  zdjęcia, ruch NEXUSA na wierzchu, karty tylko NEXUSA, osoby nieznane.
- `backend/app/services/traffit_transfer.py` — fala, lista osób per stan
  z Traffita, raport próby, wykonanie (poprawki + otwarcie funkcjami
  „Otwórz ponownie”), paragon, bieg w tle pod blokadą syncu.
- `backend/app/api/admin_traffit.py` — `POST /api/admin/traffit/transfer`,
  `GET /api/admin/traffit/transfer/status` (admin albo klucz `traffit:sync` /
  `traffit:read`; wykonanie wyłącznie zalogowany administrator).
- Wzorzec bramek `tests/data/authz_golden/admin_traffit.json` — dwie nowe trasy,
  ten sam werdykt co pozostałe trasy Traffita.
- Bez migracji i bez zmian schematu.

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
| `tests/test_traffit_transfer_plan.py` | 16 przypadków planu, bliźniaków, klucza fali i kolumn | lokalnie i CI |
| `tests/test_traffit_transfer.py` | próba bez zmian; wykonanie (remis, brakujący wiersz, zdjęta osoba, ruch NEXUSA, otwarcie, historia); niekompletna lista; bliźniak; brak wykonawcy; świeżość próby | tylko CI (Postgres) |
| `tests/test_authz_guard_matrix.py` | wzorzec bramek z nowymi trasami | lokalnie i CI |

## Co wywoła otwarcie fali pilota

Jeden prowadzący (zarazem Delivery Lead) dostanie 10 dzwonków „Nowy request do
pracy” oraz przypomnienia o kartach z Traffita: 10 × „CV wysłane czeka” i do
136 × „utknął na etapie” (112 z nich to „Nowi”). Narzędzie tego nie wycisza.

## Niepotwierdzone / poza zakresem

- Remis czasu w imporcie dotyczy wszystkich rekrutacji z Traffita; ta zmiana
  poprawia go tylko dla przenoszonych.
- Przyczyna 9 brakujących kart nie jest ustalona (kandydat istnieje, wpisu
  historii w NEXUSIE nie ma) — przeniesienie dopisuje wiersz.
- 2 055 kart scrapera (`posting`) na 104 rekrutacjach zbioru — po otwarciu
  trafią do „Nowych” jako „Z ogłoszenia”.
- Scalanie bliźniaków i ekran w Ustawieniach — kolejna fala prac.
