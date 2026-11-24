# Rekrutacje → „Pytania z rozmów” — dawny Excel pytań, uzupełniany debriefami (24.11.2026)
<!-- indeks: `/jobs/pytania`, `GET /api/interview-cycle/question-bank`, `question_bank` w `client_questions_asked.py`, archiwum Excela w tej samej tabeli, manager = hiring manager rekrutacji, panel Kalendarza pokazuje zapisany debrief zawsze -->

Prośba Delivery Leadki z 24.11.2026: debriefy czyta na bieżąco z maila, więc listy
debriefów nie potrzebuje. Potrzebuje miejsca jak dawny Excel „Pytania z interview”:
stanowisko, klient, imię i nazwisko managera i pytania bez duplikatów, z filtrami,
bez ręcznego uzupełniania. Artur wybrał z makiet wariant D z naprawą panelu (B);
lista debriefów w Kalendarzu (A) i fakt w nagłówku rekrutacji (C) odpadły.

- **Wiersz = pytanie z banku klienta** (`interview_questions`, unikalne po kliencie
  i treści), źródła `client_debrief` i `legacy_import`. Pytania `manual` z Bazy
  pytań tu nie wchodzą: to nie są pytania z rozmów.
- **Stanowisko liczy się jak „zadane w tej rekrutacji”** (`questions_asked_in_job`):
  linia debriefu tej rekrutacji albo przypięcie importu Excela
  (`added_by_user_id IS NULL`). Pin człowieka nie daje stanowiska.
- **Manager = hiring manager rekrutacji** (`jobs.hiring_manager_contact_id`).
  Na kopii produkcji z 24.11 był przy 256 z 3 441 pytań (wpisany w 46 ze 136
  rekrutacji z debriefem). Wiersz bez managera linkuje do rekrutacji, żeby go
  uzupełnić; jedno uzupełnienie obejmuje wszystkie pytania tej rekrutacji wstecz.
- **Zakres** jak `client-questions?client_id=`: klienci, których choć jedną
  rekrutację wołający czyta (`job_read_scope_clause`); stanowiska tylko z rekrutacji
  w zakresie.
- **To lista do przeglądania, nie „najnowsze N”.** Reguła z
  `archiwum-pytan-z-rozmow-u-klienta.md` (listy „ostatnie 15/20” czytają wyłącznie
  `client_debrief`) dalej obowiązuje prep-kit, ocenę prepu i Lunę.
- **Panel osoby w Kalendarzu pokazuje zapisany debrief pod krokiem „Debrief”**
  (`SavedDebrief`). Skrót stał tylko przy wierszu telefonu, a ten znika z panelu
  następnego dnia (`upcomingAgenda`), więc link z okienka „Kalendarz” pokazywał
  samo „zrobione”. Komunikat „nie ma w Twoim zakresie” stoi nad Tablicą (pod nią był
  poza ekranem 1280 × 720) i prowadzi do profilu osoby (Notatki → Rozmowy).
