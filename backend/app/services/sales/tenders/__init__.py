"""Przetargi z BZP i TED w Sprzedaży (decyzja Artura 24.11.2026, wariant B).

NEXUS sam czyta otwarte rejestry (bez Groka): ``sources`` pobiera ogłoszenia
i zmiany ogłoszeń BZP z nowym terminem, ``rules`` to bramka z instrukcji Kingi
(frazy i kody CPV, odrzucany przedmiot i zamawiający, tylko usługi), ``flow``
zakłada szansę w lejku Przetargi dla ogłoszenia, które przeszło, zapisuje odsiane
z regułą, przesuwa termin szansy po zmianie ogłoszenia i zamyka szanse od bramki,
którym minął termin składania ofert. Pętla: ``tasks/sales_tenders.py``.
→ docs/claude/sprzedaz/przetargi-z-rejestrow.md
"""
