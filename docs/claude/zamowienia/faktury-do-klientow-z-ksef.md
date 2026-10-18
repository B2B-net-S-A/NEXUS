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
  różnicę kwoty sprawdzają Finanse. Bez numeru wiąże tylko kwota równa co do grosza jednemu
  zamówieniu albo jednej osobie; reszta czeka na Finanse z powodem. Korekta idzie za fakturą
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
