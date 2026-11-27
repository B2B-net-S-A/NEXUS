"""Adresy API wykazu podatników VAT MF (biała lista) — jedno miejsce dla NEXUSA.

Z wykazu korzystają trzy moduły: Generator umów B2B („Pobierz z rejestru”,
``b2b_contract_generator/registry_lookup.py``), nocne sprawdzanie kart firm
Sprzedaży (``sales/registry.py``) i Rozliczenia (``hr/white_list.py``).
Wszystkie biorą host stąd, bo 15.10.2026 MF przeniosło usługę pod nowy adres,
a stary (``wl-api.mf.gov.pl``) działa tylko do 1.12.2026
(https://www.gov.pl/web/kas/api-wykazu-podatnikow-vat, specyfikacja API 1.6.2).

Stałe to sama domena: ścieżki metod (``/api/search/...``, ``/api/check/...``)
dokładają wywołujące moduły, tak jak w specyfikacji. Limity bez zmian.
"""

#: Produkcja wykazu (metody ``search`` i ``check``).
MF_WHITE_LIST_LIVE = "https://wykazpodatnikowvat.mf.gov.pl"
#: Środowisko testowe MF (dane testowe, bez prawdziwych podmiotów).
MF_WHITE_LIST_TEST = "https://wykazpodatnikowvat-test.mf.gov.pl"
