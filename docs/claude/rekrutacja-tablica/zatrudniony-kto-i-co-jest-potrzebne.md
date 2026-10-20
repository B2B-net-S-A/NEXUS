# „Zatrudniony”: kto przesuwa i co jest potrzebne (20.10.2026)

Zespół pytał, czy na „Zatrudniony” przesuwa tylko Delivery Lead i czy bez
zamówienia w systemie się nie da. Kod tego nie wymaga — myliły teksty.
Makiety: https://claude.ai/artifact/2m4b7dEXVnogXkcQymPiAA

## Reguły (bez zmian w serwerze)

- **Przesuwa każda rola wewnętrzna** (`RECRUITMENT_TERMINAL_ROLES`
  w `api/recruitment_access.py`), także rekruter.
- **Zamówienie nie jest warunkiem.** Ruch zakłada szkic kontraktu
  i zamówienia (`ensure_b2b_employment_draft`), Delivery Lead i Finanse
  dostają jedną sprawę „uzupełnij zamówienie” (`hired_order_status`).
- **Warunki:** debrief po rozmowie u klienta (409 `DEBRIEF_REQUIRED`, okno
  `DebriefRequiredDialog`) i „Jak podpisano umowę?” (422
  `HIRED_SIGNED_VIA_REQUIRED`).
- **Umowa z Generatora:** podpis potwierdza posiadacz „Podpis B2B”
  (`kontrakty/podpis-umowy-b2b-oznacza-autor-zespol-dl-tcm.md`); bez niego
  „Poproś o potwierdzenie podpisu” idzie do Delivery Leada klienta.

## Jak to mówią ekrany

- **Panel osoby** (`DockContractSteps`): przed zatrudnieniem sekcja
  „Do „Zatrudnionego””, zdanie „Przesuwa każdy z zespołu rekrutacji.
  Zamówienie od klienta nie jest potrzebne.”, krok „Umowa B2B z Generatora”,
  druga droga „Przesuń na „Zatrudniony”…” (umowa spoza Generatora, ten sam
  `onMoveTo` co „Inny etap…”) i osobny blok „Po zatrudnieniu — nie blokuje
  ruchu” z zamówieniem (przerywane kółko, nie „do zrobienia”). Po
  zatrudnieniu bez umowy z Generatora nie ma „Wygeneruj umowę”.
- **Okno zatrudnienia** (`usePipelineMove`): najpierw „Możesz to zapisać sam.
  Zamówienie od klienta nie jest potrzebne”, potem „Jak podpisano umowę?”,
  na końcu „Co stanie się samo po zapisie”.
- **Tablica:** „?” w nagłówku „Zatrudnionego” (`HiredColumnHelp`); brak
  zamówienia na karcie to neutralne „Zamówienie: u Delivery Leada”, nie
  czerwone „Brak zamówienia” (`board-card-badges`).

Nie wracaj do zdań „potwierdza Delivery Lead” bez „podpis tej umowy” ani do
czerwonej plakietki zamówienia — obie wywoływały te pytania. Zmiana reguł
ruchu na „Zatrudniony” = zmiana tekstu w `HiredColumnHelp`.
