# Faktury do klientów z KSeF (E8 cz. 1, 18.10.2026)

- Faktury wystawia się tam, gdzie dziś (decyzja E8: wystawianie z NEXUSA do KSeF to osobny krok).
  NEXUS liczy „do faktury” przy odczycie z zamówień: zużycie MD × `md_rate_revenue`, okresowe jako
  stawka × `billing_hours_per_month` / dni / miesiąc; część miesiąca po dniach roboczych. **Nic
  z tego nie zapisuje.** Osoba bez zużycia MD daje kwotę nieznaną, nie zaniżoną.
- Wspólna pula MD tylko według `shared_md_orders.uses_shared_md_pool`, nie według surowej
  flagi `is_md_budget_based` (0246 ustawiła ją też zwykłym zamówieniom MD z `md_budget_mode IS
  NULL`; ich zużycie leży na liniach, więc liczymy je per osoba).
- **Zamówienie kosztowe rozlicza fakturę, nie MD** — linie nie mają `md_total`, import MD ich nie
  dotyka, więc „do faktury” NEXUS dla nich nie liczy („zamówienie kosztowe — kwotę faktury
  ustalają Finanse”). Wiersz pokazuje budżet i resztę przed fakturami za ten miesiąc: kwota +
  korekta − faktury z wcześniejszych miesięcy rozliczone przez `cost_orders.settle_group`
  (arkusz Finansów). Faktura z KSeF wiąże się z kosztowym tylko numerem (kwota nie ma z czym się
  równać); jest zgodna, gdy mieści się w tej reszcie, nadwyżka to różnica do sprawdzenia przez
  Finanse (`check_basis: "budget"`). Przy wierszu liczy się suma faktur — dwie faktury mogą
  zmieścić się osobno, a razem nie.
- Faktury sprzedażowe z KSeF jako `Subject1` (migracja `0471_client_sales_invoices`). Klient
  i `KSEF_*` wspólne z rozliczeniami ludzi (etap 4), znacznik HWM osobny
  (`app_settings['client_sales_ksef_sync']`), pętla `sales_ksef_fetch`. Budżet przebiegu: 6 zapytań
  o metadane i 20 pobrań; blokada 429 z którejkolwiek ścieżki wstrzymuje obie (limit tokenu spółki).
- Dopasowanie: NIP nabywcy → klient kanoniczny. Numer zamówienia w fakturze wiąże z zamówieniem,
  różnicę kwoty sprawdzają Finanse. Bez numeru wiąże kwota równa co do grosza jednemu
  zamówieniu albo jednej osobie, a potem osoba i stawka z pozycji faktury (decyzja Artura z 02.11.2026,
  niżej); reszta czeka na Finanse z powodem. Korekta idzie za fakturą
  pierwotną. Ręcznego przypisania automat nie nadpisuje. Brak `P_6` = okres z daty wystawienia.
- Faktura z KSeF NIE schodzi z budżetów zamówień kosztowych (`client_order_invoice_consumptions`
  — import z arkusza Finansów zostaje jako zapas „wg arkusza Finansów”). Zmiana = decyzja Artura.
- Uznania z wyciągu (import wyciągów Płac) idą osobną ścieżką od obciążeń (SAVEPOINT); uznanie bez
  numeru faktury w tytule to tylko podpowiedź. Wyciąg wgrany przez Płace dopasowuje uznania do
  faktur klientów tylko, gdy importujący ma moduł Finanse (`match_credits`, sprawdzane na trasie);
  bez niego uznania są tylko policzone (`restricted: true`, bez liczników dopasowań — nie zdradzają,
  czy numer faktury istnieje) i czekają na ten sam plik wgrany przez Finanse.
- Kwoty widzą Finanse i Delivery Lead u swojego klienta (`can_read_client_finance`); rekruter nie.
  Moduł `app_settings['client_invoicing']` domyślnie wyłączony; zakładka „Faktury” u klienta
  i „Faktury do klientów” w Finansach.

## Po pierwszej próbie na prawdziwych danych KSeF (02.11.2026)

- Token spółki działa tylko na produkcji MF (`test` i `demo` odrzucają go kodem 450), ma wyłącznie
  `InvoiceRead`. Wystawianie faktur z NEXUSA wymaga osobnego tokenu z `InvoiceWrite`.
- Parser FA przeszedł 40 z 40 prawdziwych faktur FA(3), kwoty XML zgadzają się z metadanymi.
- **Kolejka nie wygasa z powodu budżetu.** Sprzedaż ma ok. 600 faktur miesięcznie, pierwszy przebieg
  od 3 miesięcy wstecz to ok. 1800 faktur przy 20 pobraniach na godzinę, czyli ok. 4 dni. `_defer`
  z powodem `budget` nie nalicza próby: inaczej po 24 przebiegach faktury wypadały z kolejki
  (`pending_expired`), a znacznik był już za nimi. Budżet przekazujemy do `_Run` jawnie, bo domyślna
  wartość pola dataclass zapisuje się przy definicji i `monkeypatch` stałej jej nie zmienia.
- **Nabywca z UE ma VAT UE zamiast NIP-u** (`KodUE` + `NrVatUE`, kolumna `buyer_foreign_id`, 0630):
  to ok. 48% faktur sprzedażowych. Klucz rejestru `clients.nip_registry` to 10 cyfr albo prefiks
  kraju z cyframi, porównanie w postaci `normalize_registry_id`.
- **Osoba i stawka wiążą bez numeru zamówienia** (metoda `person`, decyzja Artura z 02.11.2026, uzupełnia
  regułę kwoty z E8). Faktura godzinowa ma rzeczywiste godziny, a NEXUS szacunkowe, więc kwota nie będzie
  równa: w próbie 20 faktur Nordei nazwisko wskazywało jedną osobę 20/20, cena była równa 20/20, godziny
  różne 18/20. Warunek: pełne imię i nazwisko prowadzi do jednej pozycji zamówień miesiąca i cena równa
  co do grosza; inaczej faktura czeka na Finanse. Numer zamówienia i równa kwota mają pierwszeństwo.
