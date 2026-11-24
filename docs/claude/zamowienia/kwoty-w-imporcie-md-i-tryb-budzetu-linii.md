# Kwoty w imporcie MD i tryb budżetu linii (audyt 24.11.2026)

## Kwota faktury z jednym separatorem i trzema cyframi po nim

- „12.500 zł” (kropka tysięcy z polskiego Excela) i „1,234” (przecinek
  tysięcy z angielskiego) parser czytał jako 12,5 i 1,234. Faktura była
  wtedy 1000 razy za mała, a wiersz dostawał status „Rozliczono kwotowo”.
- Reguła `md_import_parser.money_text_problem`: jeśli tekst kwoty po zdjęciu
  waluty i spacji ma jeden separator (`.` albo `,`), dokładnie trzy cyfry po
  nim i najwyżej trzy przed nim, to jest `invoice_problem` „niejednoznaczny
  zapis kwoty”. MD z wiersza zostają, a faktura czeka na ręczne rozliczenie
  (`invoice_unreadable`). Wiersz kosztowy bez MD idzie do pominiętych
  z tym powodem.
- Jednoznaczne zostają: `12.50`, `0,5`, `12.500,00`, `1,234.56`, `12 500`,
  `1234,567` i każda komórka liczbowa z Excela.

## Zmiana trybu budżetu linii (`PATCH` linii zamówienia)

- Sam `{"input_mode": "md"}` na linii „kwotowej” brał dawną kwotę jako liczbę
  MD. Konto bez `amounts_view` dostawało 200 i odczytywało budżet w złotówkach
  z `md_total`.
- `_assert_amount_budget_write_allowed`: zmiana trybu wymaga jawnego
  `input_value` (422 dla każdego konta). Każda zmiana trybu z „kwoty” lub na
  „kwotę” wymaga prawa do kwot klienta (`_can_write_amounts`). Budżet w MD
  bez zmiany trybu nadal jest operacyjny.
