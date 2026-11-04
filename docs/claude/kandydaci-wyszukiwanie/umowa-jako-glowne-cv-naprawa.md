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
  („Ustaw jako główne CV”). Gdy `cv_filename` wskazywał umowę, `raw_cv_text`
  jest zerowany, bo to treść umowy; da się ją odczytać ponownie z pliku.
- Kopie umowy w etapach rekrutacji osób z następcą dostają jego plik
  (`original_snapshot_source = contract_repair`).
- Wskaźnik CV na kandydacie odpina reguła z `usun-plik-z-profilu-kandydata.md`.

## Czego to nie robi

- Nie czyści umiejętności ani wektora odczytanych z umowy u osób bez następcy.
- Nie zmienia CV firmowego ani kopii w etapach: bez SHA, osób bez następcy
  i osób spoza wyboru. Raport próby liczy kopie osób z wyboru w `stage_copies`.

## Pozostałe kopie w etapach (decyzja Artura 30.10.2026)

Pomiar 30.10: 30 kopii umów. 7 podmienia skrypt wyżej. Zostaje 23: 18 u 4 osób
spoza wyboru (7 bez SHA) i 5 u 3 osób bez następcy. Panel pokazuje kopię
z najnowszego etapu, więc 13 z 23 było widać jako „Oryginał CV”.

Po naprawie profili: `python -m app.cli.contract_stage_copies_repair`, potem
`--apply --expected N`. Bez paragonu naprawy profili bieg się nie zacznie.

- Osoba ma główne CV bez umowy w nazwie: kopia dostaje to CV.
- Osoba nie ma głównego CV: kopia zostaje pusta. Panel pokazuje plik z profilu
  albo „brak pliku”.
- Główne CV to wciąż umowa: kopia zostaje, raport liczy ją w `left_for_a_person`.
- Bajty 7 kopii bez SHA leżały tylko w wierszu i znikają; umowy zostają w profilach.

CV firmowego nie zmieniamy, bo nie powstało z umowy. Z 30 kopii 3 mają CV
firmowe (1 gotowe, 2 robocze): bez treści umowy i bez linków do udostępnienia.

Testy: `backend/tests/test_contract_as_cv_repair.py`,
`backend/tests/test_contract_stage_copies_repair.py`.
