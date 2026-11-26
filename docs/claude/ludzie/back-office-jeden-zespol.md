# Back office jako jeden zespół — etykiety, „Weź następną”, „Na zewnątrz”, bez opiekunów
<!-- indeks: bo_members, rola w zespole, przyjmuje rozmowy, etykiety zamiast zespołów, folded, Weź następną, Na zewnątrz, outside_team, automatic_assignee, sprawy osób spoza zespołu, ściąga klienta, bo_client_notes, przegląd hurtem, bez Tablicy Opieki (20.11), stare linki ?card= / ?filter=, legacyCareLink, 0746, Ławka a koniec zamówienia, Przedłużenie bez grupy, extend:client -->

Decyzje Artura z 10.11 i 19.11.2026 (makiety: https://claude.ai/artifact/3fRpacW9KwiZyGWkanPPWj).
Ta reguła ma pierwszeństwo przed opisem czterech zespołów w `back-office-kolejka-spraw.md`.

## Jeden zespół, etykiety zamiast zespołów

- Back office to jeden zespół. Opieka / Finanse / Umowy / Zamówienia nie dzielą ludzi:
  dawne kolumny zostają na kartach jako **etykiety** (`board.LABELS`, `bo_cards.team` i `lane`
  bez zmian), a rodzina etykiety (dawny zespół) służy tylko do filtrowania. Bo Artur:
  „wszystko jest w formie etykietowej i kto jest pierwszy dostępny, to rozwiązuje”.
- Skład: `bo_members` (0746) z rolą `deputy` (zastępca Heada, kierownik kolejki pod jego
  nieobecność; jeden naraz, nowy zdejmuje rolę poprzedniemu), `reception`, `accountant`,
  `member` i przełącznikiem `takes_calls`. Head zostaje w „Struktura” (`hr_divisions`);
  19.11 Artur zostawił go pustym — kierownikiem jest admin. Nie wpisuj Heada sam.
- Członek zespołu ma wszystkie etykiety (`Viewer.teams` = wszystkie), więc nie ma „Zastępuję”
  między członkami. Kwoty dalej tylko Płace i admin. Pusty `bo_members` = tryb przejściowy:
  zespół z uprawnień (`default_teams`), także DL-e — ekran „Zespół” mówi to wprost.
  Stara `bo_team_members` zostaje bez DROP-u i nikt jej nie czyta.

## Nikt nie ma przypisanych konsultantów

- Automatyczne sprawy kontraktu (koniec współpracy, zgłoszenia z portalu, „zostań trenerem”)
  idą przez `admin_cases.hooks.automatic_assignee`: przy włączonym module `back_office` bez
  osoby, bo „efektywny opiekun” spada na DL-a klienta. Bez modułu — dawny opiekun.
  Rozmowa zarezerwowana w portalu idzie do osoby, którą wybrał konsultant.
- Ekrany modułu nie pokazują opiekuna ani „Moi / Mój zakres”. Konsultanci i Klienci w module
  mają własne odczyty (`/api/back-office/consultants`, `/clients`) za bramką członka zespołu,
  bez kwot; ekrany Opieki (`/api/care/*`) zostają dla modułu wyłączonego.
- Sprawy osób spoza składu wracają do kolejki tylko kliknięciem kierownika
  („Oddaj do kolejki”, `POST /team/release-outsiders`, wpis `released_outsider` w historii).
  Bez wpisanego składu trasa odmawia (422).

## Jedno zdarzenie = jedna karta

- Na tablicy nie ma kart kroków (`source_kind = step`): krok widać w panelu sprawy,
  zalicza go każdy z zespołu, a eskaluje się sprawa, nie krok. Ławka konsultanta z otwartą
  sprawą wyjścia jest jej pierwszym krokiem i znika z tablicy (`board.folded`); panel sprawy
  pokazuje inne otwarte karty tego kontraktu (`related`).

## Ławka a koniec zamówienia (20.11.2026)

- „Ławka: karta 60 dni przed końcem” (`back-office-kolejka-spraw.md`) liczy koniec **umowy**
  (`contracts.end_date`) i aktywne wpisy „Do przepięcia”. Koniec samego **zamówienia**
  (dla Opieki `CareContract.end_date` = bliższy z `contracts.end_date` i
  `client_order_end_date`, karta „Decyzja: koniec zamówienia”) niesie „Przedłużenie”, 45 dni
  przed końcem: grupa zamówień jak dotąd, a zamówienia bez grupy jedną kartą na klienta
  i datę końca (`extend:client:<klient>:<data>`, „N os. na zamówieniu”). Zamówienie osoby,
  która ma już zamówienie z dalszym końcem, jest przedłużone i się nie liczy.
- Nie przenoś efektywnego końca na ławkę „dla zgodności z Opieką”. Na kopii produkcji z 19.11
  dało to 285 kart na osobę, 240 z nich w grudniu (82 osoby jednego klienta na 31.12),
  a każdą trzeba by zamykać „Nie dotyczy” osobno. Dawnych „Decyzji” nikt nie rozstrzygał:
  `redeploy_queue_items` miało 6 wpisów, wszystkie otwarte. Przedłużenia bez grupy to
  25 kart na 225 osób, a z 218 osób bez żadnej karty zostało 5.
- Osoba, której klient nie przedłuża, wraca na ławkę zwykłą drogą: koniec umowy albo wpis
  „Do przepięcia”. Na `/care` dla DL-i karta „Decyzja” zostaje bez zmian.

## Praca na kolejce

- Kolumny to stan: Nowe · W toku · Czeka na kogoś · **Na zewnątrz** (`outside_team` przy stanie
  `waiting`). „Na zewnątrz” wymaga działu (Rekrutacja/Delivery, Sprzedaż, IT, HR,
  Finanse, Prawnik — słowa Artura z 10.11) i powodu; karta bez osoby dostaje przekazującego, bo ktoś musi
  pilnować odpowiedzi. Każda zmiana stanu czyści dział. Osoby kontaktowe działów leżą
  w `app_settings['back_office'].outside_contacts`.
- **„Weź następną”** (`POST /next`): kolejność liczy serwer — najstarszy termin, potem
  najdłużej bez osoby; przeskakuje karty z akceptem, kroki, sprawy, których osoba nie czyta,
  i cudze ważne pierwszeństwo. Limit 5 przerywa (409 `limit`), brak pracy = 404.
- Nową sprawę człowiek zakłada tylko z etykietą, którą obszar sprawy umie wskazać
  (`AREA_LANE`): Pomoc, Wejście, Wyjście, Aneks / stawka. Reszta etykiet przychodzi z automatów.
- Przegląd przed startem: grupy po etykiecie, sprawy starsze niż 60 dni zamyka się hurtem
  (`POST /review/bulk`, każda z powodem w historii).
- **W Sprawach nie ma kanbanu Opieki** (decyzja Artura z 20.11.2026). Od 19.11 stał tam jako
  trzeci widok „Tablica Opieki”, ale w jednej kolejce tylko dublował te same sprawy, więc warunek
  z 22.10 („kanban zostaje 1:1 pod przełącznikiem”) przy włączonym module nie obowiązuje.
  Nie przywracaj go „dla porządku”: z jednej kolejki znowu zrobiłyby się dwie.
- Stare linki kanbanu w module prowadzą na tablicę Spraw (`legacyCareLink` w
  `components/back-office/board-model.ts`, po odczycie tablicy): `?card=case:<id>` otwiera kartę
  tej sprawy (`?karta=<id karty>`, szukana po `case_id` w `cards` i `triage`), `?filter=po-terminie`
  i `do-piatku` włączają „Po terminie” i „Do piątku”, a karta Opieki bez odpowiednika (popyt
  z dzwonka DL-a `?card=demand:…&area=`, dane klienta) i dawne `?widok=opieka` to sama tablica.
- Kanban 1:1 zostaje na `/care` poza modułem: przy wyłączonym module i dla osób spoza składu
  (DL-e z popytem i opiniami menedżerów). Pilnuje tego `frontend/src/lib/work-board-feature-inventory.json`.

## Ekrany i portal

- Układ: Sprawy · Konsultanci · Klienci · Zespół (kierownik); „Komunikaty” zostają przyciskiem.
  Rozmowy z portalu to karty spraw z terminem (`meeting` na karcie), a FAQ, rozmowy i jakość
  są sekcjami „Zespołu” u kierownika.
- Klienci = ściąga klienta: Rozliczenia (plus sposób z `client_settlement_rules`), Wejście nowej
  osoby, Zamówienia, Kontakty (DL klienta jako kontakt, nie opiekun) — `bo_client_notes`,
  poprawia każdy z zespołu, pusty tekst kasuje blok.
- Portal: osoby do rozmowy to skład z `takes_calls` (`meetings._host_rows`), bez zespołów
  i bez „od tego tematu” (`matches_topic` zawsze `false`). Pusty skład = konsultant nie ma
  z kim umówić rozmowy.

## Start (dopisek do runbooka)

Po wdrożeniu, przed pracą zespołu: skład w „Zespół” (Artur podał 19.11: Sandra, Ania, Kinga,
Patryk, Błażej, Michał Wzorkiewicz), uprawnienie „Sprawy” dla każdego z nich (nadaje Artur
w „Osoby i role”), potem „Oddaj do kolejki” dla spraw osób spoza zespołu (decyzja 19.11).
