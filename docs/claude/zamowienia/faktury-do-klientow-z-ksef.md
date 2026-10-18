# Faktury do klientów z KSeF (E8 cz. 1, 18.10.2026)

- Faktury wystawia się tam, gdzie dziś (decyzja E8: wystawianie z NEXUSA do KSeF to osobny krok).
  NEXUS liczy „do faktury” przy odczycie z zamówień: zużycie MD × `md_rate_revenue`, okresowe jako
  stawka × `billing_hours_per_month` / dni / miesiąc; część miesiąca po dniach roboczych. **Nic
  z tego nie zapisuje.** Osoba bez zużycia MD daje kwotę nieznaną, nie zaniżoną.
- Faktury sprzedażowe z KSeF jako `Subject1` (migracja `0470_client_sales_invoices`). Klient
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
  numeru faktury w tytule to tylko podpowiedź.
- Kwoty widzą Finanse i Delivery Lead u swojego klienta (`can_read_client_finance`); rekruter nie.
  Moduł `app_settings['client_invoicing']` domyślnie wyłączony; zakładka „Faktury” u klienta
  i „Faktury do klientów” w Finansach.
