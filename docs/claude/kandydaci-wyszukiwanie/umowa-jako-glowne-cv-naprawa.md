# Umowa jako główne CV: naprawa profili z importu Traffita (30.10.2026)
<!-- indeks: dlaczego umowa była głównym CV, co robi app.cli.contract_as_cv_repair, czego nie czyści -->

Zgłoszenie z 30.10.2026: w profilu kandydata główne CV to podpisana umowa B2B.
Nikt jej tak nie oznaczył. Import z Traffita wybierał główne CV po rozszerzeniu
(`select_all_files_with_priority`: pierwszy PDF), a `_traffit_document_kind`
każdy główny plik zapisywał jako CV. Importera nie poprawiamy, bo Traffit jest
wyłączony od 14.10.2026 (`services/traffit_retired.py`). Zostają dane.

## Reguła (decyzja Artura)

`python -m app.cli.contract_as_cv_repair` (na sucho), potem
`--apply --expected N`. Pomiar 30.10: 137 osób, 59 z plikiem z CV w nazwie.

- Umowa zostaje w profilu z rodzajem „other” i oznaczeniem „nieaktualne”. Sam
  rodzaj nie wystarczy, bo `get_current_cv` bierze też pliki „other”.
- Głównym CV zostaje tylko plik z CV w nazwie, po nim AI czyta profil od nowa.
  Nieopisanego pliku nie wybieramy, bo to może być kolejny dokument.
- Bez takiego pliku profil zostaje bez głównego CV, a wskazuje je człowiek
  („Ustaw jako główne CV”).
- Wskaźnik CV na kandydacie odpina reguła z `usun-plik-z-profilu-kandydata.md`.

## Czego to nie robi

- Nie czyści danych odczytanych wcześniej z umowy (`raw_cv_text`, umiejętności,
  wektor) u osób bez następcy.
- Nie zmienia kopii CV w rekrutacjach. Raport próby liczy je w `stage_copies`.

Testy: `backend/tests/test_contract_as_cv_repair.py`.
