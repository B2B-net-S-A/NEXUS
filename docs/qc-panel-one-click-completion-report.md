# Panel „Do poprawy” jednym kliknięciem — raport (wariant A, D1–D7)

Zgłoszenie rekrutera (17.10.2026): panel „Do poprawy” w edytorze CV zajmuje mało
miejsca i jest nieczytelny; QC ma mówić, co jest nie tak, i poprawiać jednym
przyciskiem; potrzebny przycisk „przepuść dalej mimo uwag AI”. Makiety
i decyzje: https://claude.ai/artifact/Y9XgB3H1iMS2f5WQYsHJyG. Artur: „Tak — buduj
wariant A z rekomendowanymi D1–D7, PR-y po kolei”. Reguły:
`docs/claude/generator-cv/edytor-cv-pelny-ekran.md`, sekcja „Panel »Do
poprawy« jednym kliknięciem”.

## PR 1 · układ, wiersze, odpowiedzi jednym kliknięciem

Co weszło:

- Asystent zwinięty do jednej linii pod listą (D1); rozwinięty zwija listę do
  paska z liczbami i „Pokaż listę”. Lista przy 1280 × 720: 511 px zamiast 205.
- Grupy po wadze (D2): „Blokuje wysyłkę”, „Do poprawy”, „Poprawione”, „Do
  decyzji · nie blokuje”. Wiersz = problem, podgląd zmiany, jeden przycisk;
  tytuł rozwija szczegóły i pokazuje miejsce na kartce.
- Zdanie AI w wierszu swojej uwagi (każde z „Dopisz”, „Edytuj zdanie”,
  „Odrzuć propozycję”, „Pokaż w CV”); osobnej sekcji „Propozycje AI”
  w edytorze nie ma.
- „Poprawione” z „Cofnij” (ostatnia poprawka, dopóki CV się po niej nie
  zmieniło) i „Cofnij wszystkie” po „Popraw wszystkie”.
- Treść spoza oryginału (D5): „Usuń z CV”, „Kandydat to ma” (notatka
  „Potwierdzone z kandydatem”), „Jest w oryginale” (pominięcie z fragmentem).
- „OK” / „Zostaw” przy uwagach generatora i kontroli AI — nowy powód `kept`
  (backend: `cv_finding_dismissals.REASONS`, `REASON_CHECKS` jako zbiory,
  `cv_editor_issues.dismiss` sprawdza powód względem źródła).
- „Przekaż mimo uwag…” w nagłówku blokad — ta sama akcja i ten sam warunek
  czekania co w stopce.

Przegląd (typescript-reviewer) znalazł 4 rzeczy, poprawione z testami:
pominięcie per rola przy blokadzie w kilku rolach, edycja i odrzucenie każdego
z kilku zdań AI (odrzucone wypada z „Popraw wszystkie”), `appliedActions`
z zakresem pogrubienia i terminem, przycisk w panelu czeka na asystenta.

Testy lokalne: lib `cv-editor-issues` 42, panel 42, modal (3 pliki), harness
29, inwentarz i okno QC — razem 616 zielonych; backend bez bazy:
`test_cv_finding_dismissals.py` (nowe testy powodu `kept`). Testy z bazą — CI.
