# Zakładka „Podobni” na profilu kandydata — podobny ≠ pasujący (22.10.2026)

Decyzje Artura 22.10.2026 (makiety https://claude.ai/artifact/VufQ5HYPcK59YZ5ZjgdCKs,
wariant C — osobna zakładka; warianty A, B i D odrzucone).

- **Podobieństwo nie zależy od żadnej rekrutacji.** Kolejność = kosinus wektorów CV
  w Qdrancie (`embedding_service.nearest_candidates`: Qdrant czyta wektor osoby po id
  punktu, bez Voyage'a), pula 200 najbliższych, filtry zakładki działają w tej puli.
  Obok stoi dowód do sprawdzenia przez rekrutera: wspólne umiejętności
  (`candidate_known_skill_names`, bez tagów) i porównanie dwóch kolumn.
  Stopień „Bardzo podobny / Podobny / Częściowo podobny” to progi kosinusa
  (`VERY_SIMILAR_MIN` 0,78, `SIMILAR_MIN` 0,73 w `services/similar_candidates.py`,
  pomiar 22.10.2026: 68 924 wektory, 80 osób × 20 najbliższych — mediana 0,73, p90 0,79,
  0,78 ≈ górne 13%). Zmiana progu zmienia podpis, nie kolejność; przed zmianą zmierz
  ponownie. O parach ≥ 0,90 — niżej „Możliwy duplikat” i „Profil bez CV”.
  Podpis mówi o profilu („Bardzo podobny profil”), żeby nie zgadywać rodzaju z imienia.
- **„Możliwy duplikat · Scal…” (decyzja Artura 22.10.2026, wariant (a)).** Pomiar na
  produkcji (200 losowych osób × 20 najbliższych, 171 par z kosinusem ≥ 0,90): 136 par
  to dwa profile bez CV, 22 wskazywały na kandydata usuniętego z bazy, 13 to obie osoby
  z CV — i te 13/13 były tą samą osobą (imię i nazwisko 9, telefon 6, LinkedIn 2, ten sam
  plik CV 1). Ten sam e-mail: 0, w 9 parach oba e-maile wypełnione i różne — dlatego
  reguła „ta sama osoba = ten sam e-mail” (`ta-sama-osoba-ten-sam-e-mail.md`) ich nie
  łapie. W paśmie 0,85–0,90 tożsamość miały już tylko 4 z 15 par z CV.
  Reguła (`similar_candidates.duplicate_signals`): kosinus ≥ `DUPLICATE_MIN` (0,90)
  **i** co najmniej jeden sygnał — to samo imię i nazwisko (bez wielkości liter,
  znaków diakrytycznych i kolejności, `normalize_person_name_part`), wspólny numer
  telefonu (`dedup_service._phone_keys`, bez zaślepek „000 000 000”), ten sam
  `linkedin_slug` albo ten sam plik (`candidate_documents.content_sha256`, aktywny).
  Sam kosinus bez sygnału to tylko „Bardzo podobny”. Możliwy duplikat zostaje na liście
  mimo filtrów zakładki (filtry dotyczą przydatności do rekrutacji, duplikat — porządku
  w bazie). Przy wierszu: „Możliwy duplikat” + powód („to samo imię i nazwisko · ten sam
  telefon”) i „Scal…” — tylko dla tych, którzy mogą scalać (`canMergeCandidates`:
  admin, Head of Recruitment). „Scal…” otwiera zwykłe `CandidateMergeDialog` od razu na
  porównaniu z tą osobą (`initialDuplicateId`); profil, na którym stoimy, zostaje.
  Nic nie scala się samo i nie ma osobnej listy duplikatów (wariant (b) odrzucony).
- **Profil bez CV nie ma podobnych i nie jest niczyim podobnym.** Osoba z tekstem CV
  krótszym niż `THIN_CV_CHARS` (200 znaków) **i** bez umiejętności
  (`is_thin_profile`) ma wektor z samych pól formalnych, a wszystkie takie wektory są
  sobie „bardzo podobne” (0,90–0,95). Na produkcji 22.10.2026: 3 306 takich profili,
  3 298 z wektorem; 13 z 200 losowych osób dostawało ~20 przypadkowych pustych profili
  z podpisem „Bardzo podobny”. Teraz taka osoba dostaje `status` = `no_cv` („nie ma
  w profilu CV ani umiejętności, więc nie ma z czym porównać”) bez pytania Qdranta,
  a puste profile wypadają z list innych osób. Krótkie CV z umiejętnościami w profilu
  zostaje — jest z czym porównać.
- **„Sprawdź pod rekrutację” to nakładka, nie sortowanie.** Wynik przy wierszu
  (spełnia krytyczne X/Y, brak krytycznej, już w tej rekrutacji) + dopasowanie z
  `POST /api/search/candidates/scores`; kolejność zostaje. Przykład z rozmowy z Arturem:
  osoba prawie identyczna jak ta w rekrutacji, ale bez jednej umiejętności krytycznej,
  zostaje wysoko na liście i ma przy sobie „Brak krytycznej: …”.
- **Sprawdzenie = ta sama bramka co wyszukiwanie** (`similar_candidates.critical_check`):
  krytyczne z `effective_critical(job)`, słowa ich wierszy z `critical_gate_options`,
  dowód w profilu, CV albo notatkach (`must_text_evidence.mention_sources`,
  `load_evidence_note_texts`). Krytyczna, której nie da się sprawdzić słowem, jest
  „do rozmowy” — nigdy brakiem. Karta w rekrutacji z `proposals_bulk.in_job_cards`.
- **Brak krytycznej = ostrzeżenie z obowiązkowym zdaniem, nie blokada.** W oknie
  „Przypisz” osoba bez krytycznej jest domyślnie odznaczona; zaznaczona wymaga zdania
  „dlaczego mimo to”, które trafia na kartę jako notatka „Do sprawdzenia: … — zdanie”.
  Serwer pilnuje tego samego: `POST /api/jobs/{id}/proposals/bulk` ze źródłem
  `similar_candidates` liczy sprawdzenie jeszcze raz i bez zdania w `reasons` odpowiada
  422 `critical_reason_required` z imionami. Inne źródła tej trasy działają jak dotąd.
- **Które rekrutacje w oknie „Przypisz”** (decyzja Artura „Rekrutacje Adama + moje”):
  na górze rekrutacje w toku osoby z profilu (`/history`, `splitRecruitments`), potem
  „Moje otwarte” (`jobs?mine&open_only`, ten sam klucz cache co `JobPicker`), niżej
  wyszukiwarka wszystkich opublikowanych. Kilka zaznaczonych osób = jedna rekrutacja
  i wynik przy każdej osobie; najwyżej 20 naraz (tyle ocenia jedno zapytanie o dopasowanie).
- **Globalna czarna lista nie pokazuje się wcale** (i tak nie przejdzie bramki dodania).
  „Nie szuka” ukryte domyślnie przełącznikiem „Bez „Nie szuka””; stawka „do” nie
  wycina osób bez stawki; miasto szuka w `city` i `location`.
- **Bez licznika na zakładce i bez zapytania przy otwarciu profilu** — zakładka
  montuje się dopiero po kliknięciu (jak „Pasujące rekrutacje”). Osoba bez wektora CV
  dostaje „nie ma jeszcze przeczytanego CV”, awaria Qdranta — „wyszukiwarka chwilowo
  nie odpowiada” (`status` = `no_vector` / `no_cv` / `unavailable`), nigdy pustą listę.
- **Gdzie co leży:** trasy `app/api/candidate_similar.py`
  (`GET /api/candidates/{id}/similar`, `POST /api/candidates/{id}/similar/check`,
  sekcja sourcingu + `CandidateSearchAccess`, sprawdzenie dodatkowo
  `ensure_job_read_access` dla każdej rekrutacji), front
  `components/v2/similar-candidates/` (osobny folder: porównanie celowo pokazuje fakty
  osoby z profilu obok faktów drugiej osoby, więc nie podlega regule „każdy fakt raz”
  z `candidate-profile/`), reguły widoku `lib/similar-candidates-view.ts`.
  `?tab=similar` w adresie profilu.
- **Nie zrobione świadomie:** przycisk „Nie jest podobny” z makiety (wymagałby tabeli
  na oceny) i ostrzeżenie o konflikcie z klientem przed dodaniem — konflikt wraca jak
  dotąd w `warnings` odpowiedzi dodania i trafia do komunikatu.
