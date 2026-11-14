"""Płace liczone w NEXUSIE (plan „Księgowość w NEXUSIE”, etap K7a).

* ``params`` / ``parameters`` — parametry płac (stawki ZUS, limity, skala PIT,
  KUP, ulgi, PPK) jako wersje pełnego zestawu od daty, dane płatnika,
* ``engine`` — silnik brutto → netto: czyste funkcje bez bazy,
* ``pesel`` — PESEL: suma kontrolna, data urodzenia, płeć, maska, skrót,
* ``person_data`` — dane kadrowo-płacowe osoby (zaszyfrowane),
* ``sources`` / ``lists`` — lista płac miesiąca, zatwierdzenie drugą osobą,
* ``payslip_pdf`` — paski, ``transfers`` — przelewy wypłat, ZUS i PIT,
* ``aggregates`` / ``registrations`` / ``documents`` — dane do plików
  urzędowych, ``kedu`` (ZUS KEDU), ``pit_forms`` i ``forms_pdf`` (PIT-11,
  PIT-4R, PIT-8AR) — czyste generatory formatów.

Moduł stoi za przełącznikiem „Płace” Księgowości (``ledger.settings``,
klucz ``payroll``): wyłączony widzi tylko administrator.
"""
