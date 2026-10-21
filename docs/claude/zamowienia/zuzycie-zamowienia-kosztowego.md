# Zakładka „Zużycie” przy zamówieniu kosztowym (0493, 21.10.2026)

Ticket Ani 21.10.2026, wersja B makiet (https://claude.ai/artifact/1X9rpuc2FGjr4So6QexVe8), decyzje Artura.

- **Kafelki i saldo opisują WSPÓLNY budżet zamówienia, nie osobę.** Kwota mieszka
  na grupie (`client_order_groups.budget_amount`), więc „Pozostało” i „Saldo”
  liczone per osoba pokazywałyby za dużo, gdy resztę zużył ktoś inny (w makiecie A:
  36 500 zł zamiast 18 000 zł). Udział osób stoi pod paskiem. Kolumna „Saldo
  zamówienia” = `balance_after_months` z zapisanych `settled_amount` wszystkich linii.
- **Trasy:** `GET/PUT/DELETE /api/clients/{c}/order-groups/{g}/lines/{l}/cost-consumptions[/{RRRR-MM}]`.
  Każda liczba jest kwotą, więc odczyt wymaga `_can_see_finance` (403), a zapis
  `_can_write_amounts`. Front pokazuje zakładkę tylko, gdy `group.budget_amount`
  nie jest zredagowane.
- **Przekroczenie wolno zapisać.** `settle_group` zostawia nadwyżkę jako
  `unsettled_amount`, zamówienie dostaje `exhausted`, DL alert (`emit_cost_order_exhausted`).
  Front liczy podgląd i „Przekroczenie budżetu o X zł” PRZED zapisem w
  `lib/cost-consumption.ts` — lustro `settle_group` (kolejność miesiąc, linia;
  grosze). Zmieniając jedno, zmień drugie.
- **Ręczny wpis wygrywa z importem Finansów** (decyzja Artura 21.10.2026 — inaczej
  niż przy „Zużyciu MD”, gdzie import nadpisuje). `run_md_import` pomija linię
  z wpisem `source='manual'` za ten miesiąc, wiersz arkusza dostaje
  `cost_status='manual_kept'` („Jest ręczny wpis za ten miesiąc — faktura
  pominięta”) i opis do weryfikacji. „Sprawdź dopasowanie Polkomtel” już wcześniej
  odmawiał przy ręcznym wpisie (konflikt całej partii).
- **„Brak zejścia za {miesiąc}”** znika sam po zapisie: flaga liczy się z istnienia
  wiersza faktury za ostatni importowany miesiąc.
- **Historia:** ręczny wpis kosztowy (`payload.changed = ["zejście kosztowe"]`)
  zostaje w historii zamówienia z opisem i kwotą (`format_pln`); rolom bez finansów
  kwoty redaguje `_redact_amounts`. Zejścia MD dalej z historii nie trafiają.
- **Przypadek z ticketu (SAP 4500720711):** zamówienie założono godzinę PO imporcie
  wrześniowym, więc wiersz arkusza dostał `unmatched_number`. Naprawa bez kodu:
  Finanse → Import zużycia MD → wrzesień → „Sprawdź dopasowanie Polkomtel”.
