# Import umów i aneksów klientów z paczki plików (30.10.2026)

<!-- indeks: OneDrive, manifest poza repo, próba na sucho, cofnięcie, co czyta się źle -->

Prośba działu: dodać umowy i aneksy klientów z OneDrive i sprawdzić, czy NEXUS
je poprawnie przeczyta. Polecenie `python -m app.cli.client_contract_docs_import`
(`services/client_contract_docs_import.py`), bez `--apply` to próba na sucho.

- **Co jest czym, wskazuje człowiek w manifeście JSON, trzymanym poza repo**
  (nazwy klientów i plików). Klasyfikacja po nazwie pliku nie działa: „Umowa
  Bosch.pdf” to umowa powierzenia, a 24 pliki „aneks/ankes” leżą w folderach
  zamówień i dotyczą zamówień, nie umowy ramowej.
- **Daty idą z manifestu, nie z treści.** Umowa e-podpisana zwykle ma „zawarta
  w dniu złożenia ostatniego podpisu”, a data wpisana długopisem daje w OCR
  znaki bez sensu (mLeasing, KIR). Podpis elektroniczny z PDF-a (`/M` w polu
  podpisu) ma 104 ze 146 PDF-ów umów i aneksów z paczki. Rekord z datami
  z arkusza nie jest przy imporcie zmieniany.
- **Import nie nadpisuje pliku.** Rekord z innym plikiem = `has_other_file`
  i nic się nie zmienia. Blokada w planie (brak pliku, obcy rekord, inna nazwa
  klienta) = zero zapisu. Ponowny bieg nic nie dubluje. `--undo <paragon>` cofa
  bieg; paragon `app_settings['client_contract_docs_import_<sha12>']` to same ID.
- **Treść czyta bieg importu, jeden dokument naraz.** Przerwany odczyt dokończy
  pierwsze pytanie o umowę (`ensure_indexed`).
- **Stare `.doc` dają 0 znaków** (`_extract_docx` to python-docx). W paczce
  były to wersje robocze obok podpisanych PDF-ów, więc import bierze PDF.
