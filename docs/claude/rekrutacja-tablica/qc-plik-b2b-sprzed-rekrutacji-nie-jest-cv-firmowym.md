# QC CV: plik „…B2B…” sprzed rekrutacji nie jest jej CV firmowym (07.11.2026)

Zgłoszenie z analizy QC z 07.11.2026: 5 uwag Delivery Leada „CV się nie wygenerowało”
(rekrutacja 789177, 28–29.10) przy parach, które QC zdało. Przyczyna: bez CV firmowego
pary (`candidate_stage_cvs.branded_status` draft/finalized) ani gotowego dokumentu
generatora QC spada do pliku „…B2B…” z profilu kandydata (`dz_review._document_cv`)
i zalicza `cv_present`. W tych parach był to plik z 21.08, dwa miesiące przed utworzeniem
rekrutacji (27.10), czyli CV z innego zlecenia. Para wchodziła do kolejki DL jako „QC zdane”,
a CV tej rekrutacji nie istniało. Automat auto-CV nie pominął niczego: od 21.10
(`CV_AUTO_GENERATE_WITHOUT_CONFIRMATION=False`) ruch na „Zweryfikowany” nie generuje CV
i nie zapisuje pominięcia.

Decyzja Artura 07.11.2026 (wariant 1 z trzech):
- **Plik „…B2B…” liczy się jako CV pary tylko wtedy, gdy powstał po utworzeniu rekrutacji**
  (`coalesce(uploaded_at, created_at) >= jobs.created_at`, `dz_review.rows_from_job`). Dotyczy
  QC (`_document_cv`) i wymagań ruchu / kolejek DL i Cpro (`move_requirements.company_cv_refs`),
  które muszą się zgadzać, inaczej karta mówi „CV jest”, a QC „brak” albo odwrotnie.
- Starszy plik daje `cv_present = fail` („Brak CV firmowego”) i na karcie szarą strzałkę
  „Brak CV firmowego”. Rekruter może go użyć jawnie („Wybierz” w screeningu,
  `select-document`): wtedy to szkic etapu (`branded_draft`), a nie wynik zgadywania po nazwie.
- Plik bez żadnej daty zostaje w grze (nie ma czym porównać).
- Pomiar (staging z 06.11, 30 dni): 86 par z ostatnim zdanym QC na pliku, 26 z nich nigdy nie
  dostało CV firmowego pary, a w 22 wszystkie pliki „…B2B…” były starsze niż rekrutacja.

Nie cofaj do „każdy plik B2B kandydata jest CV firmowym” bez nowej decyzji. Pole `ambiguous`
(kilka plików B2B klienta) nadal nie jest pokazywane na froncie; osobna sprawa.

Testy: `test_b2b_file_older_than_the_recruitment_is_not_its_cv` i
`test_b2b_file_from_before_the_recruitment_does_not_count_as_company_cv` (`tests/test_dz_review.py`).
