# Pod rekrutacją tylko pytania zadane na rozmowie, wszystkie pytania klienta w zakładce (02.11.2026)
<!-- indeks: `client-questions?job_id`, `scope=client`, debrief + przypięcie importu, pin człowieka nie liczy się, `AllClientQuestions` -->

Zgłoszenie z 02.11.2026: pod każdą rekrutacją klienta stała ta sama lista, bo
`GET /api/interview-cycle/client-questions?job_id=` brał z rekrutacji tylko
klienta i oddawał jego najnowsze pytania. Na kopii produkcji Nordea miała 166
pytań, panel pokazywał 50 najnowszych, a przy Project Managerze wisiały pytania
z Javy.

- **`?job_id=` = zadane w tej rekrutacji** (`services/client_questions_asked.py`):
  linia debriefu tej rekrutacji (`InterviewFeedback.client_questions`) albo
  przypięcie importu Excela (`JobQuestion.added_by_user_id IS NULL`).
- **Samo `JobQuestion` tego nie dowodzi.** Pin z Bazy pytań i kopia rekrutacji
  z szablonu zakładają ten sam wiersz, a znaczą „warto zapytać”. Stąd treść
  debriefu jako źródło: jego poprawa zdejmuje też pytanie z listy rekrutacji.
- **`?job_id=&scope=client` = wszystkie pytania klienta** (`client_debrief`),
  z rekrutacjami, w których padły (`jobs`). Bez archiwum: ma własną sekcję po
  technologiach roli (`archiwum-pytan-z-rozmow-u-klienta.md`). `?client_id=`
  zostaje dla `/jobs/new`, gdzie rekrutacji jeszcze nie ma.
- **Ekrany:** `ChampionClientQuestionsPanel` ma zakładki „Z tej rekrutacji”
  (domyślna) i „Wszystkie pytania klienta” (`AllClientQuestions`: grupy po
  rekrutacji, wyszukiwarka, pobranie dopiero po otwarciu, a pod nimi archiwum).
  `ClientQuestions` w panelu osoby i kalendarzu czyta tę samą listę rekrutacji,
  a pełna lista jest pod przyciskiem.
- **Pusta lista jest normalna.** Na kopii z 02.11 80 z 97 otwartych rekrutacji
  Nordei nie ma żadnego przypięcia, więc pusty stan odsyła do drugiej zakładki.
  Nie dokładaj fallbacku do pytań całego klienta: to dokładnie ten błąd.
- **Bez zmian, celowo:** prep-kit i ocena prepu dalej biorą najnowsze pytania
  klienta przez `_tier_client_debrief`, z własnym filtrem `_fits_job`.
