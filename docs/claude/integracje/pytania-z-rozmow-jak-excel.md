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

## Strona stanowiska i proponowana odpowiedź pod pytaniem (25.11.2026)

Decyzja Artura z 25.11.2026, wariant A z makiet: ekran zaczyna się listą
stanowisk, a pytania czyta się na stronie stanowiska, bo rekruter przygotowuje
kandydata pod jedną rolę, nie pod cały bank klienta. Pod każdym pytaniem stoi
proponowana odpowiedź.

- **Źródło odpowiedzi** to `interview_questions.ideal_answer_source` (0777),
  w API `answer` i `answer_source` przy `QuestionBankItemOut`:
  `excel` — odpowiedź z archiwum Excela (67 pytań), `manual` — wpisana
  w Bazie pytań, `ai` — nocny bieg F55, `none` — nagłówek działu, `null` —
  jeszcze nie przeliczone. Wiersz z odpowiedzią bez źródła (sprzed 0777)
  dostaje je jak w backfillu: `excel` przy archiwum, `manual` przy reszcie.
- **Odpowiedź AI jest zawsze oznaczona „do sprawdzenia”**, bo model pisze ją
  bez wiedzy o projekcie klienta, a rekruter przekazuje ją kandydatowi dalej.
- **Nocny bieg F55** (`services/interview_answer_proposals.py`, pętla
  `interview_answer_proposals`, okno 02:40–05:00 Warszawa, raz na dobę):
  pytania `client_debrief` i `legacy_import` bez odpowiedzi i bez źródła,
  najstarsze pierwsze, do `INTERVIEW_ANSWER_PROPOSALS_PER_NIGHT` (1000) na noc,
  bo zaległe ok. 3 400 pytań mają zejść w kilka nocy bez jednego dużego
  rachunku. Partie po 20 w obrębie klienta; przy pytaniu idzie stanowisko
  (tytuł i do 5 must-have rekrutacji, w której padło), bez nazwy klienta,
  kandydatów, managerów i stawek. Zapis warunkowy: odpowiedź, która już stoi,
  zostaje. Nieudana partia wraca następnej nocy, trzy z rzędu kończą noc.
  Ręcznie: `python -m scripts.interview_answer_proposals_run [--limit N]`.
  Na stagingu pętla stoi (`STAGING_BLOCKED_TASKS`), bo to drugi koszt modelu.
- **Nagłówki rozstrzyga model, nie kod.** Debrief zapisuje etykiety działów
  („Kolejki i komunikacja asynchroniczna”) jako osobne linie, ale na kopii
  produkcji z 25.11 z 32 krótkich wierszy bez „?” nagłówkami były tylko 4,
  a reszta to krótkie pytania („Playwright”, „Czy zna RLS”). Dlatego nie ma
  reguły po liczbie słów ani po znaku zapytania. Model zwraca `null` tylko dla
  etykiety, pod którą stoją kolejne pytania tej samej notatki, albo dla tekstu,
  który nie jest pytaniem; taki wiersz dostaje `none`, ekran rysuje go jako
  nagłówek i nie wraca on do modelu co noc.
- **Poprawka w Bazie pytań** zmienia źródło na `manual`; wyczyszczona
  odpowiedź wraca do `null` (nie `none`), bo pusta odpowiedź nie robi
  z pytania nagłówka.
