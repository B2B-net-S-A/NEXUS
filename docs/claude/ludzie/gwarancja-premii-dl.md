# Gwarancja premii Delivery Leada: zwrot, gdy konsultant nie przepracuje 12 miesięcy (0653, 05.11.2026)

Zasada Artura z 05.11.2026: jeśli konsultant nie przepracuje 12 miesięcy, DL
zwraca wypłaconą premię za ten placement, a kwota potrąca się z jego kolejnych
premii. Kod: `services/hr/bonus_guarantee.py`, schemat
`services/hr_bonus_guarantee_schema.py` (migracja 0653, lustro przez
`hr_schema_bundle`).

## Decyzje Artura (05.11.2026)

- **12 miesięcy od startu kontraktu** (`contracts.start_date`), nie od terminu
  premii. Kontrakt musi trwać do dnia przed rocznicą startu (`guarantee_until`);
  start 29 lutego → do 28 lutego następnego roku.
- **Tylko premie DL**: kategoria `delivery_lead`, czyli rola `dl` i `dl_extra`.
  Premii rekrutera gwarancja nie obejmuje.
- **Zwrot to cała premia**, bez proporcji do przepracowanych miesięcy.
- **Dług zakłada automat albo Płace**:
  - automat — kontrakt skończył się przed `guarantee_until` (data końca już
    minęła albo status `ended` bez daty); hak końca kontraktu w
    `placement_bonuses._hook` i nocny przebieg `sync_guarantees` w pętli
    premii (kontrakty z przyznaną premią DL ze startem w ostatnich 400 dniach);
  - Płace ręcznie: „Zwrot z gwarancji” przy przyznanej premii DL
    (`POST /api/hr/payroll/bonuses/{id}/clawback`, powód 3–500 znaków), gdy
    konsultant odszedł, a kontrakt w NEXUSIE jeszcze trwa. Odmowy: własna premia
    403, inna kategoria albo premia nieprzyznana 409, drugi zwrot 409,
    kontrakt przepracował 12 miesięcy 409.
- **Potrącenie idzie samo, Płace widzą je przed zamknięciem**: raport otwartego
  miesiąca (`payroll_report.compute_live`) odejmuje dług od przyznanych premii
  osoby w tej samej walucie, najwyżej do ich sumy; reszta przechodzi dalej.
  Długi idą od najstarszego. Wcześniejsze otwarte miesiące biorą swoją część
  pierwsze, więc późniejsze zamknięcie wcześniejszego miesiąca nie potrąci
  więcej, niż zostało.
- **Widok**: osoba ma kartę „Do zwrotu z gwarancji” nad premiami w „Moim czasie”
  (`GET /me` → `clawbacks`) i „premie − potrącenie = razem” w podsumowaniu
  miesiąca. Płace mają kolumnę „Potrącenie” w tabeli osób miesiąca (tylko gdy
  ktoś ma potrącenie), sekcję „Zwroty z gwarancji” z „Zdejmij” pod premiami
  miesiąca i znacznik „zwrot z gwarancji” przy premii.

## Zmiany z 09.11.2026

- **Każdy powód końca kontraktu** łamie gwarancję. Zastępstwo nie ma wpływu.
- **Przepięcie:** następny kontrakt tej samej osoby do 31 dni od końca poprzedniego,
  u dowolnego klienta, nie łamie gwarancji. Liczy się koniec ostatniego kontraktu
  w łańcuchu, od startu pierwszego. Taki kontrakt nie daje nowej premii DL, rekruter
  swoją dostaje (`placement_bonuses.continues_earlier_contract`).
- **Przy 200%** wraca cała wypłacona kwota.
- **Premie z importu Compassa** nie mają kontraktu. Po włączeniu samego przyznawania
  nocny przebieg dopasowuje je po imieniu i nazwisku z opisu (jednoznacznie, start
  kontraktu od 4 miesięcy przed miesiącem premii do miesiąca po nim). Premii bez
  nazwiska w opisie gwarancja nie obejmuje. Premie rozliczone w październiku przez
  usunięcie nowej premii są wyłączone stałą `SETTLED_BEFORE_AUTOMATION`.
- Zakładanie i zdejmowanie zwrotu ręcznie: tylko admin (`ludzie/premie-z-automatu.md`).

## Jak to działa

- `hr_bonus_clawbacks` — dług za jedną premię: kwota i waluta premii, skąd
  (`automatic`/`manual`), start, koniec, `guarantee_until`, powód. Jeden żywy
  dług na premię (`uq_hr_bonus_clawbacks_live`). Stany: `open` → `settled`
  (potrącenia ≥ kwota) albo `cancelled`. Nikt nie zakłada ani nie zdejmuje
  długu sobie (CHECK-i i 403).
- `hr_bonus_clawback_offsets` — potrącenie zamrożone przy zamknięciu miesiąca
  (dług × okres). `close_month` blokuje otwarte długi przed liczeniem raportu
  (`lock_open`), zapisuje potrącenia i przestawia spłacone na `settled`.
  `reopen_month` kasuje potrącenia okresu i wraca dług do `open`.
- `payroll_lines.bonus_total` jest **po potrąceniu**: eksport, Symfonia,
  rozliczenia z KSeF i „wypłacone w roku” biorą kwotę netto bez zmian w swoim
  kodzie. Potrącenie stoi w `clawback_total`, premie przed nim to suma obu.
  Przełożony widzi premie zespołu już po potrąceniu (bez osobnej kolumny).
- **Cofnięcie końca kontraktu** zdejmuje otwarty dług automatu
  (`contract_restored`). Dług ręczny zostaje — to decyzja Płac. Dług zdjęty
  ręcznie (`cancel_reason = manual`) automat już nie zakłada.
- **Anulowanie premii** w otwartym miesiącu zdejmuje jej dług
  (`bonus_cancelled`): premia nie wyszła, nie ma czego zwracać.
- **Potrącone, a dług anulowany** (np. cofnięty koniec po zamkniętym miesiącu)
  zostaje na listach jako „do oddania” (`refund_due`). Oddaje się to ręczną
  premią — automat zwrotu nie zakłada.
- Dług w innej walucie niż premie miesiąca się nie potrąca (kursów nie ma).
- Premia z arkusza za październik 2026 (×2 „na ryzyko firmy”, 30.10.2026)
  podlega gwarancji jak każda premia DL — pierwszy przypadek z 05.11.2026 to
  właśnie taka premia.

## Poza zakresem (nie dopisuj „przy okazji”)

- Dzwonek i mail do DL-a o nowym długu — osoba widzi kartę w „Moim czasie”.
- Ręczna zmiana kwoty długu (dziś zawsze cała premia).
- Gwarancja premii rekrutera.
