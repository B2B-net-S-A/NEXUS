"""Rozliczenia zespołu — płatności (etap 4, R5 i R9).

* ``accounts`` — rachunek PL (IBAN/NRB): walidacja, ostatnie cyfry, numer banku,
* ``settings`` — ustawienia płatności i słowniki Symfonii (``app_settings``),
* ``ports`` — wywołania modułów R-A (rozliczenia) i R-B (biała lista),
* ``titles`` — tytuły przelewów (numer KSeF dla faktur),
* ``finance`` — ekran „Dla Finansów”: zatwierdzone do zapłaty, CSV, lista NIP-ów,
* ``elixir`` / ``batches`` — paczka przelewów (opcja, domyślnie wyłączona),
* ``mt940`` / ``camt053`` / ``statements`` — import wyciągu i „opłacono”.

Rachunki osób nie trafiają do logów, śladu HR ani komunikatów błędów — tylko
ostatnie 4 cyfry. Przelewy robią Finanse jak dziś (eBI24 albo bank); NEXUS
pokazuje, co jest do zapłaty, i rozpoznaje zapłatę z wyciągu.
"""
