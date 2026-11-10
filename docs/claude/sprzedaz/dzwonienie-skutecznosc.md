# Dzwonienie → Skuteczność: lejek, kampanie, listy, pory dnia i ranking — decyzje Artura 11.11.2026
<!-- indeks: ekran Skuteczność pod zakładką Dzwonienie, GET /api/sales/calling/effectiveness, calling_stats.py, external_source call_queue i external_id rekord:próba, rozmowa = wynik inny niż Nie odebrał, spotkanie z terminem, werdykt Warto z bloku przekazania, ranking osób z sortowaniem, tylko Sprzedaż: edycja, wnioski regułami z progiem próby, bez AI -->

Powód: Artur chce rozumieć, co daje dzwonienie (dwie osoby dzwoniące, kampanie i listy)
i mieć analizę na bieżąco. Makieta na danych stagingu (prywatny artefakt):
https://claude.ai/artifact/C4xhRXxv9dgwVfd2dbq3Pi. Stan wyjściowy z kopii produkcji
10.11.2026: 94 szanse z telefonów w 3 dni robocze, 0 wpisów rozmów w dzienniku, żadne
z 30 umówionych spotkań bez terminu w NEXUSIE, 62 z 94 wyników wpisane hurtem po 16:00.

Kod: `backend/app/services/sales/calling_stats.py` (czysta funkcja `summarize` i odczyt),
trasa `GET /api/sales/calling/effectiveness` w `api/sales_calling.py`, front
`frontend/src/components/sales/calling/EffectivenessView.tsx`, adres
`/sales/calling/effectiveness` (przełącznik „Kolejka | Skuteczność” w `CallingModeSwitch.tsx`;
jedenasta zakładka Sprzedaży zawinęłaby rząd przy 1280 px).

## Decyzje

- **Ranking osób jest pełny i z sortowaniem** (wybór Artura 11.11.2026 spośród: tylko
  kampanie, osoba widzi siebie na tle zespołu, pełny ranking). Domyślnie po liczbie
  umówionych spotkań, klik w nagłówek sortuje po innej kolumnie, remis alfabetycznie.
  To dotyczy wyłącznie ekranu „Skuteczność”: **kolejka dalej nie ma rankingu, celu
  dziennego ani przełącznika osoby** (`dzwonienie-kampanie-i-import-listy.md`).
- **Dostęp: „Sprzedaż: edycja”** (trasa i przełącznik). Z samym podglądem 403.
- **„Moje / Zespół”** zawęża cały ekran do telefonów zalogowanej osoby.

## Co liczymy

- Źródło to telefony z dziennika (`sales_activities.kind = 'call'` z wynikiem), także
  te zapisane na karcie szansy. **Telefon z kolejki ma `external_source = 'call_queue'`
  i `external_id = "<id rekordu>:<numer próby>"`** (`calling.apply_outcome`). Numer
  próby jest konieczny: `ux_sales_activities_outlook` jest unikalny na
  `(external_source, external_id, company_id)`, a do jednego rekordu dzwoni się wiele razy.
  Bez tego znacznika telefon nie trafi do kampanii ani listy.
- **Rozmowa** = wynik inny niż „Nie odebrał”. Konwersje w lejku są liczone do
  poprzedniego sensownego kroku (rozmowy z telefonów, oferta i spotkanie z rozmów).
- **Spotkanie z terminem**: termin w bloku przekazania (`custom_fields.handoff.meeting_at`)
  albo spotkanie w dzienniku firmy od dnia założenia szansy (ten sam warunek co
  „spotkania bez terminu” w kolejce). **Werdykt** z bloku przekazania; odbyte = werdykty
  z `HELD_VERDICTS`, „Warto” = `qualified`.
- **Kampanie**: lista i „Nowe” to stan dziś, reszta z okresu. „Starczy na” = nowe
  rekordy ÷ (różne rekordy obdzwonione w okresie ÷ dni robocze okresu).
- **Listy** grupują po „Skąd kontakt” z importu; szanse z etapu „Lead” i telefony
  z karty szansy mają własne wiersze.
- **Kiedy odbierają**: pon–pt, 8–17 w kalendarzu firmy; komórka z mniej niż 5
  telefonami nie ma procentu.
- **Oferta ogólna → co dalej**: dzisiejszy stan rekordów, którym w okresie wysłano ofertę.
- **Wnioski liczą reguły z progiem próby, nie model AI**: godziny dopiero od 100
  telefonów (i 20 w godzinie), porównanie list od 30 rozmów na listę. Poniżej progu
  zdanie się nie pojawia, bo przy kilkunastu rozmowach różnica procentów to szum.

Testy: `backend/tests/test_sales_calling_stats.py`,
`frontend/src/components/sales/__tests__/sales-calling-effectiveness.test.tsx`.
