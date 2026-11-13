"""E-faktury Peppol BIS Billing 3 z faktur sprzedażowych z KSeF (plan Nordei N2).

* ``fa_reader`` — odczyt FA(2)/FA(3) w zakresie potrzebnym do e-faktury,
* ``ubl`` — budowa UBL Invoice albo CreditNote (czysta funkcja),
* ``validation`` — reguły EN16931 i Peppol (Schematron) przed wysyłką,
* ``pdf`` — wizualizacja faktury do załącznika,
* ``providers`` — dostawca Peppol z API (adapter, bez własnego punktu dostępu),
* ``settings`` — przełączniki i odbiorcy (``app_settings['peppol_einvoices']``),
* ``service`` — stan e-faktury przy fakturze do klienta, wysyłka, statusy.
"""
