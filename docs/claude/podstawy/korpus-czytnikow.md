# Korpus czytników — każda poprawka czytnika to przypadek, PR mierzy eval przed i po

Decyzja Artura z 26.11.2026 („korpus z bramką”). W 30 dniach przed nią było 46
poprawek czytnika poczty rozliczeń i 27 poprawek odczytu CV, a 71% poprawek
poprawiało pliki zmienione w ostatnich 3 dniach. Test każdej poprawki sprawdzał
przykład napisany razem z nią, więc kolejna poprawka psuła poprzednią (łańcuch
Cpro #3992 → #4020 → #4026). Korpus trzyma prawdziwe przypadki i liczy je na
dwóch rewizjach.

- **Czytniki i ich pliki:** `backend/tests/corpus/czytniki.json` — `rozliczenia`
  (rodzaj, osoba, okres pliku z poczty; `mailbox.run_once` na czystej bazie)
  i `cv` (daty stanowisk, Edukacja, nazwa, języki; `cv_parser` i treść Nowego CV).
  Format przypadków: `backend/tests/corpus/README.md`.
- **Eval:** z `backend/`: `python scripts/eval_reader.py <czytnik> --przed origin/main --po HEAD`.
  Pokazuje trafienia per pole przed i po, listę spadków i naprawionych. Kod
  wyjścia 1 = spadek, 2 = błąd środowiska (brak pakietu w venv). Rewizje to
  commity, nie katalog roboczy.
- **Bramka:** hook `~/.claude/hooks/eval-czytnikow-gate.js` (PreToolUse na
  `gh pr create` / `gh pr ready`): PR zmieniający pliki czytnika potrzebuje
  świeżego wyniku (`po` = HEAD, `przed` z `origin/main`) bez spadku, z korpusem
  z produkcji, gdy jest na laptopie. Gałąź z commitem `fix(…)` w czytniku musi też
  zmienić `backend/tests/corpus/<czytnik>/`: nowy przypadek z tym błędem albo
  wpis w `_poprawki.json` z powodem, dlaczego to nie pole odczytu. Draft przechodzi.
- **Spadek, który jest poprawą:** gdy oczekiwanie w przypadku było błędne, popraw
  przypadek w tym samym PR-ze i napisz w opisie dlaczego.
- **Korpus z produkcji:** `python scripts/eval_reader_export.py cv|rozliczenia` zapisuje
  pełne przypadki w `~/.nexus-staging/corpus/<czytnik>/` (prawdziwe CV z kopii stagingu,
  maile z archiwum skrzynki rozliczeń; przypadki rozliczeń biegną na kopii produkcji
  w transakcji cofanej). Oczekiwania to stan HEAD z dnia eksportu, więc każda zmiana
  odczytu prawdziwego pliku wychodzi do obejrzenia. Do repo te pliki nie trafiają.
- **CI:** `tests/test_reader_corpus_guard.py` (strażnik bez bazy: anonimizacja
  korpusu w repo, przypadki CV na HEAD) i `tests/test_reader_corpus_settlements_db.py`
  (przypadki rozliczeń na Postgresie, osobna baza `<baza>_korpus`).
