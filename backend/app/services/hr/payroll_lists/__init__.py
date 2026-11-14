"""Płace liczone w NEXUSIE (plan „Księgowość w NEXUSIE”, etap K7a).

* ``params`` — parametry płac (stawki ZUS, limity, skala PIT, KUP, ulgi, PPK)
  jako wersje pełnego zestawu od daty,
* ``engine`` — silnik brutto → netto: czyste funkcje bez bazy,
* ``pesel`` — PESEL: suma kontrolna, data urodzenia, płeć, maska,
* ``person_data`` — dane kadrowo-płacowe osoby (zaszyfrowane),
* ``builder`` / ``lists`` — lista płac miesiąca, zatwierdzenie drugą osobą,
* ``payslip_pdf``, ``kedu``, ``pit_forms``, ``transfers`` — pliki do wysyłki
  ręcznej i przelewy.

Moduł stoi za przełącznikiem „Płace” Księgowości (``ledger.settings``,
klucz ``payroll``): wyłączony widzi tylko administrator.
"""
