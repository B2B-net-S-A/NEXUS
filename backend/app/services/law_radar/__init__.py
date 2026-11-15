"""Radar przepisów: dwa Grok Boty (Zbieracz i Analityk) i bramka NEXUSA.

Przepływ i decyzje Artura z 15.11.2026: ``docs/claude/przepisy/radar-przepisow-dwa-boty.md``.

* ``schema`` — SQL migracji 0713 i lustra entrypointu,
* ``runs`` — bieg bota, jednorazowy token, webhook,
* ``collect`` — polecenie i raport Zbieracza, zapis surowych pozycji,
* ``gate`` — odcisk, klasa źródła i sprawdzenie numerów w API Sejmu,
* ``analyze`` — polecenie i raport Analityka, zapis zmian,
* ``probes`` — sondy „u nas” na danych NEXUSA,
* ``flow`` — kolejność kroków: Zbieracz → bramka → Analityk.

Pakiet celowo nic nie importuje: ``schema`` czyta entrypoint przy starcie.
"""
