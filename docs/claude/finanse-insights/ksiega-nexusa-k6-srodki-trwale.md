# Księga NEXUSA K6 (14.11.2026): środki trwałe i WNiP zamiast Symfonii Środki Trwałe

Etap K6 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar).
Fundament (lata, okresy, bufor, dziennik, storno, blokady) opisuje
`ksiega-nexusa-k1-fundament.md`, maszynę „Źródeł” — `ksiega-nexusa-k2-zrodla.md`.
Migracja `0703_ledger_assets` (`ledger_assets_schema.py`, lustro przez
`hr_schema_bundle`), trasy `api/ledger_assets.py`, wzorzec bramek
`tests/data/authz_golden/ledger_assets.json`.

## Co jest

- Moduł `assets` ma ekrany (`BUILT`), zakładka „Środki trwałe”
  (`/accounting/assets`). Wyłączony widzi tylko admin, jak każdy moduł.
- **Ewidencja** (`ledger_assets`): numer inwentarzowy (`ST/RRRR/NNN`,
  `WNiP/RRRR/NNN` albo własny), KŚT 2016 (wymagany dla środka trwałego),
  data przyjęcia, wartość początkowa (grosze, bez ulepszeń), konto środka
  (010/020) i umorzenia (070/071), MPK (`FO`, `BO`, `OG`, `K<id klienta>` —
  te same kody co rozliczenie kosztów K2), metoda i stawka osobno dla planu
  bilansowego i podatkowego, współczynnik degresywnej, stan, powiązanie
  z pozycją „Sprzętu” (jedna pozycja — jeden środek).
- **Plan amortyzacji** (`services/ledger/depreciation.py`, czyste funkcje):
  odpisy od miesiąca po przyjęciu; liniowa = wartość × stawka / 12 do grosza
  (połówki w górę), ostatni odpis = reszta; degresywna od wartości netto
  z początku roku (pierwszy rok od wartości początkowej), liniowa od roku,
  w którym degresywny odpis roczny byłby niższy; jednorazowa w pierwszym
  miesiącu; ulepszenie podnosi wartość od następnego miesiąca (w degresywnej
  także podstawę roku) i wznawia odpisy umorzonego środka; likwidacja
  i sprzedaż — odpis jeszcze za swój miesiąc. Plan bilansowy idzie do księgi,
  podatkowy czeka na CIT (K8). WNiP podatkowo nie bywa degresywny (art. 16k).
- **Dokumenty środka** (`ledger_asset_operations`): OT (z nowym środkiem,
  także z faktury z kolejki kosztów, bez faktur osób zespołu), UL
  (ulepszenie), MT (zmiana MPK, bez zapisu — zmienia podział AM od swojego
  miesiąca), LT (likwidacja), SP (sprzedaż; przychód księguje faktura). Numer
  `OT 1/2026` — typ i kolejny w roku. Dokument w księdze to PK z numerem
  dokumentu środka: OT i UL Wn konto środka / Ma konto przeciwstawne (080),
  LT i SP Wn umorzenie (z odpisem za miesiąc zbycia) i Wn wartość netto (761)
  / Ma wartość początkowa. Opis zapisu (`title`) jest zamrożony przy
  dokumencie, więc zmiana nazwy środka nie zmienia zatwierdzonego zapisu.
- **AM miesiąca** (źródło `assets_month` / `RRRR-MM`): odpisy bilansowe
  wszystkich środków — Wn 401 z MPK, Ma 070/071, i od razu podział na „5”
  (Wn konta „5” z rozliczenia kosztów K2 według MPK, Ma 490). Rozliczenie
  kosztów K2 bierze tylko FVZ, więc AM dzieli się sam. `meta.assets` to
  rozbicie na środki `[id, kwota, MPK, konto umorzenia]`; odcisk danych
  obejmuje jego skrót (`meta.detail_hash` — tylko w AM, odciski innych źródeł
  bez zmian).
- **„Nalicz amortyzację”** (`POST /assets/sync`, „Moduł Finanse”) to
  „Zaksięguj miesiąc” dwóch źródeł: dokumenty środków, potem AM — szkice
  w buforze, zatwierdza lista „Księgowi”. Oba źródła są też w „Źródłach”
  i na liście zamknięcia miesiąca (pozycja „Amortyzacja — Symfonia ŚT” znika
  z etapów w drodze, gdy moduł jest otwarty).
- Konta modułu (`app_settings['ledger'].assets`: amortyzacja 401, przyjęcie
  080, wartość netto zbycia 761) ustawia admin (`PUT /assets/settings`), każde
  z planu kont. Bez kont „5” AM czeka w „Źródłach” z problemem.

## Zasady, których łatwo nie zauważyć

- **Zatwierdzona przeszłość jest nietykalna**: każda zmiana ewidencji
  (nowy środek, edycja, dokument, usunięcie) jest sprawdzana z rozbiciem
  zatwierdzonych AM — gdy przestawiłaby odpis środka (kwotę, MPK, konto)
  w miesiącu z zatwierdzonym AM, dostaje 409 z numerem zapisu. Dlatego środka
  przyjętego wstecz, MT i LT z datą w zamkniętym miesiącu ani usunięcia
  takiego dokumentu nie ma bez storna AM. Parametrów planu środka
  z jakimkolwiek zatwierdzonym zapisem (OT, AM) nie zmienia się wcale —
  zmianę robi dokument (ulepszenie, likwidacja) albo storno.
- **Szkice znikają od razu**: każda zmiana planu (nowy środek, parametry,
  dokument, usunięcie) zdejmuje z bufora szkice AM i dokumentów środka (jak
  automaty K3a); następne „Nalicz amortyzację” robi je z nowych danych. Sama
  zmiana opisu (nazwa, numer, uwagi, „Sprzęt”) zdejmuje tylko szkice
  dokumentów tego środka — AM jej nie zawiera.
- Usuwa się tylko ostatni dokument środka bez zapisu w dzienniku; OT —
  wyłącznie z całym środkiem.
- **Daty dokumentów**: UL, MT, LT i SP nie mogą być sprzed przyjęcia ani
  w miesiącu stanu z Symfonii (albo przed nim) — także po zmianie daty
  przyjęcia albo miesiąca stanu na karcie (422). Inaczej LT trafiał do księgi
  przed OT, a ulepszenie z okresu stanu liczyło się dwa razy (przegląd K6
  14.11.2026). Wartości spoza liczb („NaN”) w pliku i formularzu to błąd
  wiersza, nie 500.
- **Stan z Symfonii** (import albo ręcznie): umorzenie bilansowe i podatkowe
  na koniec miesiąca, odpisy od następnego. Taki środek nie dostaje OT
  w księdze — wartość i umorzenie przychodzą bilansem otwarcia (K2).
  Degresywna ze stanem nie na koniec grudnia potrzebuje umorzenia na początek
  roku (podstawa odpisów roku). Dokumenty z datą do miesiąca stanu są
  w Symfonii (422).
- **Import** (`POST /assets/import?year=&month=&save=`, lista „Księgowi”):
  XLSX albo CSV, nagłówki po aliasach (najdłuższy wygrywa: „Umorzenie
  podatkowe” to nie „Umorzenie”), stawka < 1 to ułamek z Excela, środki
  zlikwidowane i sprzedane pomijane. Wszystko albo nic: błędny wiersz, numer
  już w ewidencji albo konto spoza planu blokują zapis pliku.
- **Do Symfonii** (K3b): AM i dokumenty środków da się zaznaczyć w paczce,
  ale domyślnie są poza nią — do przełączenia AM liczy też Symfonia ŚT
  (porównania miesięczne K9).
- „Niskocenne w „Sprzęcie”” na ekranie = pozycje „Sprzętu” firmy (`nasz`,
  bez wycofanych i zgubionych) bez karty środka.
- Poza K6: JPK_ST_KR (zwolniony za 2026–2028), inwentaryzacja z listy
  „Sprzętu”, zmiana stawki od roku, aktualizacja wyceny.
