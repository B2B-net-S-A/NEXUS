# Faktura kontraktora: data sprzedaży, miesiąc w nazwie i płatność z XML-a KSeF

<!-- indeks: ci.sale_date, ci.item_month, ci.payment_form, data sprzedaży, P_6, FormaPlatnosci, Zaplacono, XML faktury kontraktora, limit pobrań KSeF, contractor_details, invoice_fields, korekta faktury kontraktora -->

Decyzja z 23.11.2026, po przeglądzie korespondencji rozliczenia@ z IX–X 2026: 79 maili
z prośbą o korektę faktury dotyczyło pól, których NEXUS nie widział. Najczęściej data
sprzedaży inna niż ostatni dzień miesiąca (16), forma płatności inna niż przelew albo
„ZAPŁACONO” (13) i nazwa pozycji z innym miesiącem (5).

## Skąd dane

- Faktury kontraktorów zapisujemy z metadanych zapytania KSeF
  (`client_settlements/contractor_invoices.py`, wołane z `hr/ksef/sync.py`). Metadane mają
  numer, daty wystawienia i wpływu, NIP-y, kwoty, walutę i typ, ale nie mają `P_6`, pozycji
  ani `Platnosc`. Bez XML-a tych kontroli nie da się zrobić.
- XML pobiera `contractor_details.fetch_details` w tym samym przebiegu KSeF, po Płacach:
  najpierw korekty i faktury korygowane (łańcuch korekt), potem raz każda faktura przypięta
  do kontraktu (`nip_state` znany albo potwierdzony, `contract_id`), bez korekt.
  Treść sprzed odczytu płatności (bez klucza `paid` w `details`) pobieramy jeszcze raz.
- `hr/ksef/fa.py` czyta `Platnosc/FormaPlatnosci` (kod 1–7, `PlatnoscInna` = `other`)
  i znacznik zapłaty (`Zaplacono`, `ZnacznikZaplatyCzesciowej`). Datę sprzedaży bierze
  z `OkresFa/P_6_Do`, potem `P_6`, potem wspólnego miesiąca `P_6A` pozycji.

## Limit pobrań (stan 23.11.2026)

- KSeF na produkcji: 64 pobrania faktury na godzinę na token spółki, wspólne dla pętli zakupów
  (Płace + kontraktorzy), pętli sprzedaży i podglądu PDF.
- Pętla zakupów: najwyżej 40 na przebieg (`hr/ksef/sync.py`, `MAX_DOWNLOADS`), Płace biorą
  pierwsze. Kontraktorzy dostają resztę, najwyżej 10 (`contractor_details.MAX_DOWNLOADS`).
  Ta zmiana nie podnosi więc sufitu pętli zakupów i nie zabiera nic Płacom.
- Produkcja 23.11: Płace nie mają NIP-ów w `employee_billing_details` ani faktur z KSeF,
  pętla zakupów biegnie co godzinę (24 przebiegi na dobę). Aktywnych kontraktów ok. 510,
  więc do ok. 510 faktur kontraktorów w miesiącu. Przy 10 na godzinę to ok. 2 doby po fali
  faktur z początku miesiąca. Pętla sprzedaży bierze 20 na przebieg (+30 przy zaległych
  oknach). 20.11 dostała 429 w 7 przebiegach przy doganianiu zaległości, a pętla zakupów
  wtedy nie.
- Gdyby Płace zaczęły pobierać 40 na godzinę, kontraktorom nie zostanie nic w tym przebiegu.
  Faktury czekają wtedy jako „nie sprawdzono” do kolejnych przebiegów i nic się nie blokuje.

## Reguły (sekcja „Faktura kontraktora”, etap E6.6, domyślnie `off`)

- `ci.sale_date`: data sprzedaży = ostatni dzień rozliczanego miesiąca (`period_month`
  faktury). Bez `P_6` liczy się data wystawienia, bo FA wymaga `P_6` tylko wtedy, gdy różni się
  od `P_1`.
- `ci.item_month`: nazwy pozycji nie wskazują innego miesiąca. Rozpoznaje polskie nazwy
  miesięcy w odmianie (z ogonkami i bez), rok tuż po nazwie oraz zapisy `10.2026` i `2026-10`
  z miesiącem dwucyfrowym („3/2026” to zwykle numer zamówienia). Nazwa bez miesiąca przechodzi.
- `ci.payment_form`: błąd przy znaczniku zapłaty, formie innej niż przelew (`6`) albo braku
  formy płatności i numeru rachunku. Sam rachunek bez formy płatności przechodzi.
- Korekt nie sprawdzamy: ich treść ocenia `invoice_chain`.
- Faktura bez treści z KSeF dostaje uwagę „Pola faktury: nie sprawdzono”, nigdy błąd.
- Kontrola to wpis na karcie osoby (`invoice_fields.field_checks`), jak `ci.buyer_nip`;
  `block` pokazuje ją jako błąd.

## Czego nie robić

- Nie pobierać XML-a każdej faktury kosztowej spółki (`approvals/cost_invoices.py` zostaje
  na metadanych), bo pętla zakupów widzi do kilkudziesięciu faktur dziennie, a limit jest
  wspólny.
- Nie podnosić `contractor_details.MAX_DOWNLOADS` ponad resztę budżetu Płac. Większy sufit
  pętli zakupów wymaga sprawdzenia sumy z pętlą sprzedaży i podglądem (64 na godzinę).
