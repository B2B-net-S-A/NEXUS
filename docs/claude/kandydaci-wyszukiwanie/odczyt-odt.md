# Odczyt ODT: tekst z `content.xml` w procesie odczytu (05.11.2026)

`extract_text` nie znał ODT, więc CV w tym formacie nie miało tekstu i nie trafiało
do wyszukiwania ani do odczytu modelem. Pomiar na kopii produkcji z 05.11.2026:
35 aktywnych plików u 34 profili, z tego 16 profili bez tekstu. Odczyt daje tekst
ze wszystkich 35, a znaki bez odstępów zgadzają się z węzłami `content.xml`.

- **Format z bajtów:** `sniff_extension` daje `.odt`, gdy wpis `mimetype` to dokładnie
  dokument tekstowy ODF. Arkusz ODS i prezentacja mają inny `mimetype`, więc zostają
  bez tekstu. Plik bez tego wpisu czytamy tylko po nazwie `.odt`.
- **Izolacja i limit:** operacja `odt` w `_run_pdf_worker` (limit pamięci i czasu),
  a przed parsowaniem `assert_safe_ooxml`, bo ODT to też ZIP. Parser bez DTD, encji
  i sieci, jak `hr/bank/camt053.py`.
- **Co jest treścią:** tylko `text:p` i `text:h` z `office:body`, także w tabelach,
  listach i ramkach. Pominięte: usunięty tekst ze śledzenia zmian, komentarze, opisy
  obrazków i wzorce spisu treści, bo w dokumencie ich nie widać.
- **ODT bez tekstu dostaje końcowe `empty`,** nie `error` jak Word: odczyt nie zależy
  od zajętego LibreOffice'a, więc ponowienie nic nie zmieni.
- **Sam kod niczego nie uzupełnia.** Stare wiersze mają końcowy `unsupported_format`,
  a sync Traffita z nocną fazą stoi od 14.10.2026. Uzupełnienie to osobna decyzja.
  `backfill_cv_text --retry-outcomes unsupported_format` bierze wszystkie zaległe
  wiersze, nie tylko ODT (pomiar: 101 wierszy, w tym 16 ODT).
