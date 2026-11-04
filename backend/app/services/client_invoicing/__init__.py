"""Faktury do klientów (etap 5, E8 cz. 1): „do faktury” z zamówień, faktury z KSeF, zapłata.

Faktury wystawia się tam, gdzie dziś (eBI24 albo Symfonia). NEXUS:

* ``billing`` — liczy pozycje „do faktury” za miesiąc z tego, co już ma:
  zamówienia MD (zużycie MD × stawka linii), kosztowe (zużycie MD × stawka;
  kwota z arkusza Finansów jako zapas), okresowe (stawka × godziny / dni /
  miesiąc z zamówienia, częściowy miesiąc po dniach roboczych),
* ``sync`` — czyta z KSeF faktury, w których spółka jest sprzedawcą
  (``Subject1``; ten sam klient i konfiguracja ``KSEF_*`` co faktury od osób,
  osobny znacznik HWM), ``fa_sales`` — pola faktury sprzedażowej ponad
  parser z etapu 4,
* ``matching`` — łączy fakturę z zamówieniem: NIP nabywcy → klient, okres,
  numer zamówienia w fakturze, kwota; niepewne zostaje Finansom,
* ``payments`` — zapłata z uznań na wyciągu (wołane z importu wyciągu
  ``services/hr/bank/statements.py`` i z ekranu Finansów),
* ``views`` — zakładka „Faktury” klienta, lista Finansów, zaległości,
* ``export`` — pozycje „do faktury” w CSV/XLSX do systemu, w którym się wystawia,
* ``settings`` — przełącznik modułu (``app_settings['client_invoicing']``,
  domyślnie wyłączony), ``access`` — kto widzi kwoty którego klienta.

Kwoty widzą Finanse (moduł Finanse) i Delivery Lead u klientów ze swojego
portfela; rekruter nie. Logi niosą identyfikatory i liczby — bez NIP-ów,
numerów KSeF, kwot i tokenów.
"""
