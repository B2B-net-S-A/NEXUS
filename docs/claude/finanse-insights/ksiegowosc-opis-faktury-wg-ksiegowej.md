# Opis faktury kosztowej wg „Ogólnych założeń” głównej księgowej (E2, 22.11.2026)

18.11.2026 główna księgowa przysłała arkusz „Ogólne założenia”: pola, które
Finanse wybierają przy opisie faktury w eBI24, i dwie próbki eksportu do
Symfonii (samochód FVZP, import usług IU). Decyzja Artura z 22.11.2026:
budujemy wg arkusza teraz, test z księgową po 25.11; wyciągi i PK / listy płac
zostają w Symfonii, NEXUS jest kopią. Arkusz i próbki leżą u Artura, nie
w repo (dane firmy); testy są na zmyślonych fakturach.

Kod: `services/finance_ledger/posting_options.py` (listy, walidacja wyborów),
`posting.compute` (dekret), trasa `PUT /api/finance/posting/entries/{id}/description`
i `GET /api/finance/posting/choice-lists`, karta faktury → „Dekret do Symfonii FK”
→ „Opisz do księgowania” (`DecreeDescription.tsx`). Plik: szablon 4
(`ledger/export_file._purchase_document`, `ksiega-nexusa-k3b-symfonia-szablon-4.md`).

## Wybory leżą w dekrecie, nie w kolumnie

- `finance_cost_entries.decree["choices"]` — bez migracji. „Przelicz” liczy
  dekret z reguły **i** z wyborów, więc ich nie gubi; ręczna korekta pozycji
  zostawia wybory i rejestry VAT (`posting.MANUAL_KEPT`). Zapis opisu liczy
  dekret od nowa (także w miejsce ręcznego, zdarzenie `decree` z `choices`).
- Ręczna korekta z innymi kwotami (koszt, VAT, VAT należny, rozrachunek) niż
  w wyliczonym dekrecie gubi rejestry VAT i flagę samochodu — plik bierze wtedy
  jeden rejestr z kwot faktury (przegląd 22.11: stare połowy szły do JPK
  i do Symfonii obok pełnego VAT na 221). Import usług bez rejestrów nie
  wychodzi do pliku („przelicz dekret”).
- Puste pole = podpowiedź z reguły (konto kosztu, VAT, typ, opis ze wzoru).
  Bez reguły dekret powstaje, gdy Finanse wybrały konto netto (inne kategorie
  niż Kontraktorzy nie muszą mieć reguły).
- Pola: opis księgowy (wymagany), typ dokumentu (FVZ, IU, DP, FVZP, WNT, FKZ,
  FZBO), rejestr (Zakup, Import usług VAT naliczony, Rejestr naliczony WNT,
  Zakup Środki Trwałe, Korekta Zakupu, Korekta Zakupu NP. VAT), konto netto,
  konto VAT (221, 223, 403-302), rejestr i konto VAT należnego (226, 222, 224),
  flagi UE i Usługa, stawka importu, konto „5”, „Paliwo i leasingi” z kontem
  902–903, procedura JPK, data, kurs i tabela NBP, data zakończenia usługi.
  Lista spoza arkusza = 422.

## Konta zespołów 4 i 7 o rodzaju „inne”

Plan z Symfonii ma konta 4 i 7 z rodzajem „inne” (K1), a reguła wymagała
„koszt”. Nie przestawiamy setek kont: konto netto pasuje, gdy ma rodzaj
„koszt” albo „inne” w zespole 4 lub 7 (`net_account_ok`, też reguły w „Plan
kont” i kontrola dekretu). Konto VAT: rodzaj „VAT” albo numer z listy
księgowej z analityką. „5”: zespół 5, „koszt” albo „inne”. Lista na karcie
pokazuje tylko konta bez analityki (księgowalne).

Wyjątek z próbki: samochód w leasingu księguje netto na 244-3 (zespół 2),
więc przy „Paliwo i leasingi” konto netto może być też z zespołu 2.

## Konto brutto z kartoteki

`posting.settlement_account`: 201-2-<nr> dostawca krajowy w PLN, 203-2-<nr>
zagraniczny (VAT UE, numer zagraniczny albo kraj ≠ PL), 205-2-<nr> krajowy
w walucie; <nr> = `symfonia_partner_id`. Konto z kartoteki spoza 201/203/205
(leasing 244-1, dostawca z formularza K5b-2 pod 202-1) wygrywa. Bez numeru
Symfonii — konto z kartoteki z prefiksem dopasowanym do waluty.

## Kwoty

- **Zwykła faktura**: jak dotąd (Wn netto, Wn VAT, Ma brutto; waluta: brutto
  i VAT × kurs, netto różnicą). Każda pozycja ma kwotę w walucie
  (`amount_cur`), rejestr VAT — netto, VAT i brutto w PLN i w walucie.
- **Samochód** („Paliwo i leasingi”): VAT dzielony na pół, pierwsza połowa
  w dół (jak eBI24: 667,81 → 333,90 do odliczenia, 333,91 w koszt). Koszt =
  netto + nieodliczona połowa, „5” tak samo. Rejestry: „Zakup” (½ netto, VAT do
  odliczenia) i „Rejestr NP VAT” (druga połowa; korekta: „Korekta Zakupu”
  i „Korekta Zakupu NP. VAT”). Opcjonalnie Wn 999 / Ma 902–903 na ½ brutto
  (druga połowa przy nieparzystych groszach) — zwykły zapis, nie równoległy.
- **Import usług / WNT** (typ IU, WNT albo zaznaczony rejestr VAT należnego):
  netto PLN = netto × kurs, VAT = netto PLN × stawka (domyślnie 23%), w walucie
  netto × stawka. Wn koszt / Ma kontrahent = netto, Wn VAT naliczony / Ma VAT
  należny (226) = VAT. Dwa rejestry (naliczony z flagami UE i Usługa, należny).
  UE domyślnie = kontrahent z VAT UE, Usługa domyślnie = tak (WNT — nie).
  Procedura JPK domyślnie BFK (arkusz: import usług zawsze BFK). Import od
  kontrahenta z Polski i faktura z VAT od sprzedawcy = wada dekretu.
- **Korekta** (brutto < 0): typ domyślnie FKZ i rejestr „Korekta Zakupu”,
  strony odwrócone, kwoty dodatnie (jak dotąd).
- **Waluta**: kurs z dnia wybranego na karcie (inaczej ostatni dzień roboczy
  przed wystawieniem) z tabeli `fx_rates`; kurs wpisany ręcznie wygrywa;
  tabela NBP to tekst `NNN/A/NBP/RRRR` (NEXUS jej nie zna z `fx_rates`).
- **Procedura JPK MK**: faktura z KSeF z `Adnotacje/P_16 = 1` (dziś tylko
  faktury kontraktorów — jedyne koszty z XML-em; `contractor_details.details`
  dostaje `cash_method` i `sale_date` przy pobraniu XML-a, starsze wiersze nie
  mają tych pól). Wybór na karcie wygrywa.
- **Data zakończenia usługi**: z karty, inaczej `P_6` z XML-a, inaczej koniec
  miesiąca usługi (rozliczenie osoby, miesiąc kontraktora), inaczej data
  wystawienia.

## „5”: jedna ścieżka na fakturę (decyzja w tej regule)

Arkusz chce „5” na dokumencie jako zapis równoległy (Wn 5xx / Ma 490),
z możliwością usunięcia linii przed eksportem. Dotąd „5” robił miesięczny PK
z MPK (`ledger/allocation.py`). Żeby nie było dwa razy:

- konto „5” wybrane na karcie = pozycje `allocation` / `allocation_offset`
  (`parallel: true`) w dekrecie, na FVZ w księdze (`meta.parallel_lines`)
  i w pliku Symfonii (`ZapisRownolegly =33`);
- PK rozliczenia kosztów **pomija** FVZ z `meta.parallel_lines` (także storno
  takiej faktury), reszta faktur idzie PK jak dotąd;
- „Usuń linię „5” z dekretu” na karcie = puste konto „5” i zapis opisu; faktura
  wraca do PK. Zostaje to, co jest w Symfonii: „5” z pliku, PK NEXUSA jest kopią.

## Korekta (FKZ) w pliku

Korekta z dekretem po opisie (ma rejestry) idzie tym samym układem zakupu co
FVZ/FVZP/IU, z blokiem faktury korygowanej, `IdDlaRozliczen =1` na zapisie
rozrachunkowym i w `Transakcja` oraz rachunkiem w grupach — jak próbka FKZ
z 17.11.2026 (render z niej równy próbce, razem z zapisami równoległymi „5”,
które stary układ FKZ gubił). Bez tego korekta samochodu szła jednym rejestrem
z pełnym VAT obok 1/2 VAT na 221 (przegląd 22.11). FKZ z dekretu sprzed opisu
zostaje w starym układzie.

## Rejestr VAT księgi (K5) z opisu

`sources._vat_meta`: import usług z kolejki kosztów dostaje `meta.jpk_group`
(K_29/K_30 od podatnika z UE, inaczej K_27/K_28), `received_date` i konto VAT
należnego z dekretu (`output_account`, np. 226 zamiast konta sprzedaży);
samochód — `register_net` = netto połowy „Zakup” (JPK K_42 bez nieodliczonej
połowy).

## Pytania do księgowej (test po 25.11, nie pisz do niej — decyzja Artura)

Lista w opisie PR-a z tym plikiem; po odpowiedziach dopisz tu rozstrzygnięcia.
