# Archiwum eBI24 w Finansach (E5, 16.11.2026)

Decyzja Artura z 16.11.2026: archiwum eBI24 (49 728 dokumentów 2021–2026: faktury sprzedaży i kosztowe)
przenosimy do NEXUSA eksportem przez przeglądarkę (tylko odczyt, nic w eBI24 się nie zmienia), zanim wygaśnie
umowa z eBI24. Kod: `services/finance_ledger/archive.py`, trasy `api/finance_archive.py`
(`/api/finance/archive-ebi24`), migracja `0720_finance_archive` (`services/finance_archive_schema.py`),
pakowanie `scripts/pack_ebi24_archive.py`.

- **Dane:** metadane w `finance_archive_documents` (numer, daty, kontrahent, kwoty, numer KSeF, folder, `meta` —
  pola z `archive.KEEP_META`, bez stanu obiegu eBI24). Plik na dysku `UPLOADS_DIR/ebi24_archive/<rok>/<id eBI24>.<rozszerzenie>`:
  PDF/HTML dokumentu wgranego do eBI24 albo JSON faktury wystawionej w eBI24. **Kwoty eBI24 są w groszach** — import
  dzieli przez 100.
- **Rodzaj:** `INCOME*`, `EUROPEAN_INCOME*`, `VAT_EXPORT*`, `CORRECTION_NOTE` = sprzedaż; `COST*`, `OTHER_EXPENSE` = koszt.
- **Import:** `POST /import` (tylko admin — jednorazowe przeniesienie) przyjmuje paczkę ZIP (`metadane.json` +
  `pliki/<id>.<rozszerzenie>`, do 120 MB i 5 000 plików). Idempotentny po id eBI24 — paczkę można wgrać ponownie.
  Nazwy plików z paczki nie trafiają na dysk (tylko id eBI24 zgodne z wzorem 24 znaków hex).
- **Podgląd:** faktura z eBI24 (JSON) otwiera się jako HTML złożony przez NEXUS (wszystko escapowane, CSP bez skryptów);
  PDF jako oryginał; HTML z obcego systemu wyłącznie do pobrania (nie otwieramy go w domenie NEXUSA).
- **Dostęp:** „Moduł Finanse” + sekcja Finanse; moduł „Księgowość” wyłączony = 404 (admin widzi), jak Koszty i Kontrahenci.
- **Eksport źródłowy** leży na laptopie Artura (`~/NEXUS-ebi24-export/`), poza repo — repo jest publiczne.
