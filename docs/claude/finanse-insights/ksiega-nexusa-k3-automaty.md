# Księga NEXUSA K3 (14.11.2026): PK cykliczne, RMK i paczka do Symfonii

Etap K3 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar),
część pierwsza. Fundament: `ksiega-nexusa-k1-fundament.md`, źródła miesiąca:
`ksiega-nexusa-k2-zrodla.md`. Migracja `0701_ledger_automations`
(`ledger_automation_schema.py`, lustro przez `hr_schema_bundle`).

## Co jest

- Moduł `automations` („Podatki, polisy i PK cykliczne”) ma ekrany od K3a
  (`BUILT`), zakładka „Automaty” (`/accounting/automations`). Wyłączony widzi
  tylko admin, jak każdy moduł Księgowości.
- **PK cykliczne** (`ledger_recurring`): wzór z pozycjami dekretu (grosze, MPK,
  kontrahent), pierwszy i opcjonalnie ostatni miesiąc. Co miesiąc w zakresie
  jeden PK w ostatnim dniu miesiąca, źródło `ledger_recurring` / `<id>:RRRR-MM`.
- **RMK** (`ledger_prepayments`, rozliczenia międzyokresowe kosztów czynne, np.
  polisy): kwota całkowita w N ratach od pierwszego miesiąca; rata = kwota // N,
  ostatnia = reszta (suma rat = kwota co do grosza). PK Wn konto kosztu (MPK) /
  Ma konto RMK, źródło `ledger_prepayment` / `<id>:RRRR-MM`.
- Dokumenty powstają w „Źródłach” (to samo „Zaksięguj miesiąc” co faktury:
  odcisk danych, przebudowa szkicu, problem do storna) — karty „PK cykliczne”
  i „RMK” pokazują się przy otwartym module.

## Zasady, których łatwo nie zauważyć

- **Zatwierdzona przeszłość jest nietykalna**: wzoru ani RMK z zatwierdzonym
  miesiącem nie zmienia się i nie usuwa (409). Zmiana kwoty przerobiłaby
  wszystkie zamknięte miesiące na problemy do storna. Wzór kończy się datą
  (`end_month` nie wcześniej niż ostatni zatwierdzony miesiąc); nowa kwota =
  nowy wzór od następnego miesiąca.
- **Szkice znikają od razu**: usunięcie wzoru albo RMK i każda zmiana treści
  zdejmują jego szkice z bufora, a „Zakończ” — szkice po ostatnim miesiącu.
  Następne „Zaksięguj miesiąc” zrobi je od nowa z nowych danych. Czekanie na
  księgowanie zostawiało w buforze szkic ze starymi kwotami, który dało się
  zatwierdzić (przegląd K3a 14.11.2026).
- Wzory i RMK zakłada lista „Księgowi” albo admin; podgląd „Moduł Finanse”
  przy otwartym module. Pozycje wzoru przechodzą tę samą kontrolę co PK
  (konta z planu, Wn = Ma).
- Dalej w K3: lista płac z pliku Enovy (do czasu K7), kalendarz podatków i ZUS
  z listą zamknięcia miesiąca; wycena walut idzie z rozrachunkami w K4.

## Paczka do Symfonii (K3b, migracja `0702_ledger_exports`)

- Zakładka „Do Symfonii” (`/accounting/symfonia`, moduł `ledger`): zatwierdzone
  dokumenty miesiąca w pliku do importu w Symfonii FK, póki Symfonia jest księgą
  urzędową (tryb roku „symfonia” albo „równolegle”; w trybie NEXUS 409).
  Bez paczki PK z „Automatów” trafiałyby tylko do księgi-cienia, a księgowa
  dalej przepisywałaby je ręcznie.
- **Domyślnie w paczce**: PK z ręki, PK cykliczne, RMK, rozliczenie kosztów na
  „5”. Faktury kosztowe (FVZ) mają własną paczkę E2, sprzedaż (FVS) trafia do
  Symfonii z eBI24 do czasu wystawiania w NEXUSIE, bilans otwarcia przychodzi
  z Symfonii — te rodzaje da się zaznaczyć, ale domyślnie są poza paczką, bo
  Symfonia dostałaby je dwa razy. Storno ma rodzaj dokumentu, który odwraca.
- **Dokument najwyżej w jednej aktywnej paczce** (`ledger_export_documents`,
  indeks unikalny częściowy) — paczka zbiera tylko dokumenty spoza paczek.
  Numer `K/RRRR-MM/n` (blokada doradcza), plik i SHA-256 w bazie: ponowne
  pobranie daje ten sam plik. „Zaksięgowana w Symfonii” zamyka paczkę;
  „Anuluj” (tylko pobraną) zwalnia jej dokumenty do następnej.
- **D2**: dokumenty płacowe idą wyłącznie osobną paczką płacową (robi i widzi
  ją osoba z Płacami albo admin). Mieszana paczka zabrałaby zwykłe dokumenty
  z widoku osoby bez Płac, a samej paczki ta osoba by nie zobaczyła.
- Paczkę, „zaksięgowaną” i anulowanie robi lista „Księgowi” albo admin;
  podgląd i pobranie pliku — „Moduł Finanse”.
- Plik: format neutralny jak w E2 (XLSX albo CSV, wiersz na pozycję dekretu:
  nr w dzienniku, numer, typ, daty, konto, Wn/Ma, MPK, kontrahent z ID
  Symfonii, waluta, storno dokumentu, numer KSeF). Identyfikator kontrahenta
  tylko NIP albo VAT UE — PESEL z kartoteki E1 nie trafia do pliku. Format
  importu Symfonii FK dopiszemy klasą w `ledger/export_file.py` po próbce od
  Finansów.
