# Księga NEXUSA K3a (14.11.2026): PK cykliczne i RMK — polecenia księgowania co miesiąc same

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
- Dalej w K3: lista płac z pliku Enovy (do czasu K7), kalendarz podatków i ZUS,
  wycena walut (po rozrachunkach w K4), paczki do Symfonii (czeka na próbkę
  pliku importu od Finansów).
