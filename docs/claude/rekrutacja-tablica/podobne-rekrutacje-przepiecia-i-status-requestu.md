# Podobne rekrutacje, przepięcia i status requestu (0341, 22.09.2026)

Decyzje Artura z 22.09.2026 (makiety: https://claude.ai/artifact/PGkKkGFSug8KUpB7n5T9Wn).
Serwis `services/job_similarity.py`, trasy `api/job_similar.py`.

- **Status requestu jest LICZONY, jedną regułą** (`request_status_expr`):
  `closed` → `filled` (zatrudnionych ≥ headcount) → `contract` (bieżący etap
  acceptance/negotiation/onboarding albo etap szablonu „Umowa…") → `champion`
  → `incomplete` (szkic) → `searching`. Filtr listy (`?request_status=`, front
  `rs=`) i pole wiersza/szczegółów czytają TO SAMO wyrażenie.
- **„Szukamy" trwa, dopóki Delivery Lead nie oznaczy „Mamy championa"**
  (`POST /api/jobs/{id}/champion-found`, admin/DL/HoR + członkostwo;
  `jobs.champion_found_at/by`). Liczby „w bazie" świadomie NIE pokazujemy —
  rekruterzy oceniają sami; „Wymaga ruchu" zdjęte z wiersza listy (sortowanie
  „Wymaga uwagi" zostaje).
- **Przepięcie = osoba wysłana do klienta (cv_sent…negotiation, nie
  zatrudniona w źródle) w rekrutacji wskazanej jako podobna.** Trafia do
  „Do przejrzenia" jako propozycja `source='reassign'` (nigdy wprost do
  pipeline'u), na górze kolejki, z `reassign_from` (rekrutacja, etap, data).
- **Połączenie jest symetryczne i trwałe** (`job_similar_links`, oba kierunki
  naraz): `link_jobs` przepina od razu w obie strony, a hak
  `on_candidate_sent` w `/move` i `/bulk-move` przepina każdą kolejną osobę
  wysłaną do klienta (savepoint, nigdy nie rzuca). Zamknięta rekrutacja nie
  przyjmuje przepięć, ale jest źródłem.
- **Panel „Podobne rekrutacje” na stronie rekrutacji = przepięcie jednym
  kliknięciem** (`SimilarJobsPanel`, `?win=similar`, 25.09.2026; od 02.10.2026
  zakładka okna „Kandydaci do dodania”, `?win=add&wintab=similar`; okno
  `SimilarJobsDialog` zostało wyłącznie na liście rekrutacji). Rekrutacja
  NIGDY nie jest zaznaczona sama (incydent 23.09: zapis szkicu przepiął 41
  osób); kliknięcie rekrutacji (podpowiedź albo `GET …/similar/search`, także
  zamknięte) zaznacza wszystkich wysłanych w niej do klienta
  (`GET …/similar/people`, `sim.sent_people`: reguła `REASSIGN_STAGES`, także
  odrzuceni przez klienta), zatrudnionych i obecnych w rekrutacji nie da się
  wybrać. `POST …/similar/reassign` w jednej transakcji: sprawdza, że każda
  osoba jest `selectable` (inaczej 422 i zero zapisu), łączy rekrutacje,
  zapisuje propozycję `reassign` w statusie `proposed` (`propose_selected`,
  wskrzesza pominiętą i `added` po „Cofnij” — wejście dostaje
  `entry_source=reassign`)
  i dodaje do „Nowych” ścieżką „Biorę” (blokada 12 h, weto HM = pominięcie).
  „Cofnij” w komunikacie zdejmuje dodanych i rozłącza nowe połączenia
  (propozycje zostają `added` — świadomie). **Podgląd osoby (02.10.2026):**
  klik w nazwisko otwiera kartę obok panelu (`SimilarPersonPreview`:
  dopasowanie do TEJ rekrutacji z `/scores`, fakty z `proposal-facts`,
  notatki z `quick-view`, CV, profil), Ctrl/⌘-klik — profil w nowej karcie;
  zaznaczenie zmienia tylko pole wyboru. Karta jest `sidePane` w
  `RecruitmentSheet` (wewnątrz okna — poza nim Radix wyłącza kliknięcia),
  a Esc zamyka najpierw ją, bo zamknięcie panelu kasuje zaznaczenia.
  W dopasowaniu karta pokazuje tylko technologie: `/scores` oddaje
  `non_technology_must` (must spoza reguły `must_gate_terms.gate_requirement`
  — zdania, branża, język, rola), a karta je pomija. Sam kraj w polu miasta
  („PL”) to brak miasta (`proposal_facts._display_city`).
  `?tab=similar` z powiadomień
  o propozycjach AI zostaje przy „Do przejrzenia”, nie przy panelu. Pasek
  w „Nowych”, odznaka „N do przepięcia” i reguła „Najbliższego kroku”
  `similar` tylko otwierają panel i liczą `reassignable_people` z GET
  `/similar` (`sim.reassignable_counts` — ta sama reguła co `selectable`;
  suma `sent_count` liczyła zatrudnionych i obecnych, więc krok wisiał bez
  nikogo do przepięcia). Jedno przepięcie: najwyżej 100 osób.
  Karta niesie `reassign_from_reference` („↻ z ZOB-1725”).
- **Sugestie liczy WEKTOR rekrutacji (decyzja Artura 30.09.2026)**:
  kosinus wektorów z kolekcji `nexus_jobs` (zapytanie po id punktu, bez
  przesyłania wektora), pula = rekrutacje z kimkolwiek od „CV wysłane” wzwyż
  (`_sent_job_ids`, bez samej rekrutacji i już połączonych), porządek =
  kosinus + **0,08 za tego samego klienta** (`VECTOR_CLIENT_BONUS`), top 5,
  BEZ progu. `similarity` = kosinus × 100, `similarity_kind: "vector"` (UI:
  „≈ N%”). Zmierzone na historii (1620 rekrutacji): prawdziwe źródło
  przepięcia w top 5 dla 60,6% rekrutacji zamiast 39,7% przy dawnym wzorze
  z progiem 55 (86% prawdziwych źródeł miało poniżej 55). **Zapas
  leksykalny** (`similarity_kind: "lexical"`) — rekrutacja bez wektora albo
  Qdrant nie odpowiada w ~2 s: must-have (Jaccard) 0,55 + tytuł 0,30 +
  ta sama kategoria 0,15, próg 55; **ten sam klient liczy się jak ta sama
  kategoria** (lepsze z dwóch, nie suma — od 25.09.2026; ZOB-3006 i ZOB-1725
  PKO BP w różnych kategoriach miały 30 pkt, teraz 60), pula = CAŁA historia (także zamknięte i archiwum z Traffita; do 24.09.2026 18 miesięcy) w pamięci
  procesu 5 min z indeksem odwróconym. Lista rekrutacji liczy stronę jednym
  wywołaniem Qdranta (`query_batch_points`, pamięć rankingu z kluczem
  `vector-v1`; awarii nie pamięta) i pokazuje „≈" tylko przy sugestiach
  z osobami u klienta — wektorowych wyłącznie z (kosinus + premia) ≥
  `SIMILAR_JOBS_BADGE_MIN_COSINE` = 0,65 (mediana wyniku prawdziwych źródeł
  przepięć; kalibracja na produkcji 30.09.2026, liczby przy stałej). DL wskazuje podobne już przy tworzeniu
  (`POST /api/job-similarity/preview` — szkic tytuł + must-have embedowany
  `full_search_measurement.request_vector`, premia za klienta szkicu;
  po zapisie `POST …/similar`).
  **Must-have = kolumna ∪ stack MUST Championa, jako KANONICZNE nazwy
  technologii z taksonomii** (`skill_set`, od 22.09.2026): surowe napisy
  z samej kolumny dawały podpowiedź 92 z 326 otwartym rekrutacjom, ten zbiór —
  195. Bez wczytanej taksonomii działa stara reguła (surowe napisy kolumny).
  Profile Championa z plików Traffita wypełnia `scripts/champion_backfill.py`
  (paczka z `scripts/champion_bundle_collector.js`, GPT Luna).
- **Tryb „Tabela" USUNIĘTY — rekrutacja to Tablica** (decyzja Artura
  22.09.2026). Nagłówek nie ma przełącznika; z ekranów pobocznych (Champion,
  „Do przejrzenia") wraca „← Tablica". `tab=people` żyje WYŁĄCZNIE dla ekranu
  „Do przejrzenia" (`seg=proposals|shortlist`: pełne propozycje z bazy
  i shortlista — makieta 4); każdy inny dawny adres Tabeli otwiera Tablicę,
  a `?candidate=&panel=` otwiera panel osoby od razu rozwinięty na zakładce.
  Warsztaty z dawnej Tabeli (CV do klienta ze stawką/linkiem, rozmowy
  i werdykt HM, umowa) żyją w rozwiniętym panelu osoby („Rozwiń”,
  `person/PersonWorkbenchTabs`, od 04.10.2026); zbiorcza wysyłka CV — pasek
  zaznaczenia Tablicy. *(Blok „Do
  przejrzenia” w kolumnie „Nowi” usunięty 02.10.2026 — kafle nad Tablicą.)*
  Pierwsza kolumna
  „Do przejrzenia" = `BoardReviewSection` na TEJ SAMEJ scalonej liście co
  ekran propozycji (`useJobProposals`), wpięta w kolumnę etapu „Ogłoszenia"
  i nigdy nie chowana przez „Ukryj puste kolumny"; ✓ dodaje
  z `initial_stage_legacy: "screening"`.
- **Dok osoby: sekcje zamiast zakładek** — „Teraz" wg etapu
  (`nowSectionForStage`: posting/new/verified → CV, screening → Screening,
  reszta → W procesie), główna akcja pod nazwiskiem, notatka zawsze na dole.
  **Okno Zlecenie** to od 29.09.2026 skrót (braki, fakty, wymagania), a
  zespół, ogłoszenie i priorytet są w panelu obok Profilu Championa;
  „Baza pytań" w menu „⋯".
- *(Od 24.09.2026 Tablica ma 8 kolumn, a DZ zastąpiło QC CV — sekcja „Rekrutacja v5”. Opis niżej do „Pipeline v4” włącznie mówi, jak składa się szablon; reguły DZ są historyczne.)*
- **Tablica: jeden etap = jedna kolumna, reszta to odznaki** (decyzja Artura
  22.09.2026, `lib/board-stages.ts` → `foldBoardColumns`; od 23.09.2026
  6 kolumn — sekcja „Pipeline v4"). Szablony w bazie
  ZOSTAJĄ — nocny import z Traffita zapisuje ruch na dokładny stan swojego
  procesu, więc składa się wyłącznie RENDER: etapy-odznaki rozpoznane po nazwie
  dołączają do kolumny swojego znaczenia („Przepuszczony przez DZ" → „DZ ✓"
  i „Wysłać do Cpro" → „Gotowy do Cpro" w „Zweryfikowany"; Prep/„Po
  Interview" → „Rozmowa u klienta"; „Umowa wysłana/podpisana" → „Umowa";
  „Onboarding" → „Zatrudniony"), duplikaty z importu („Zaakceptowany (#41)")
  łączą się, a odrzuceni/wycofani/rezerwa są paskiem nad tablicą (chip = cel
  upuszczenia, klik rozwija kolumny). Nazwę kolumny Tablicy dostaje TYLKO etap
  o kanonicznym kodzie; własne etapy (kod zastępczy `new` poza pierwszym,
  `interview` itd.) zostają osobnymi kolumnami z własną nazwą — inaczej
  szablon z samych własnych etapów złożyłby się w „Nowi". Karta upuszczona na
  kolumnę trafia na etap-gospodarza; odznakę włącza/wyłącza przełącznik w doku
  (ruch na etap-odznakę / z powrotem). Serwer (`services/board_stage_badges.py`,
  `/move` i `/bulk-move`): „DZ ✓" tylko admin/DL/Head of Recruitment (Dominik
  = HoR), „Gotowy do Cpro" tylko u klienta z `NORDEA_ORDER_NUMBER_CLIENT_IDS`
  (`job.cpro_enabled`). Reguła nazw DZ/Cpro ma lustro front↔back na wspólnym
  `__fixtures__/board-stage-cases.json` (prawdziwe nazwy z 3 szablonów).
- **Etap z INNEGO szablonu trafia do kolumny po NAZWIE, dopiero potem po
  kodzie** (`board_stage_badges.foreign_stage_target`, 23.09.2026): 310 z 326
  opublikowanych rekrutacji nie ma własnego szablonu (tablica = „Default
  B2B”), a import zapisuje etapy szablonu Traffita. Samo dopasowanie po kodzie
  wrzucało pięć etapów Traffita z kodem `interview` („Interview - Prep”,
  „Po Interview”…) na „Przepuszczony przez DZ” — z odznaką „DZ ✓” — a
  „NORDEA: Wysłać do Cpro” (kod `screening`) do Screeningu. Kolejność: ta sama
  nazwa → ten sam rodzaj odznaki (`stage_badge_kind`, lustro `placeStage`) →
  kod, ale nigdy na etap-odznakę DZ/Cpro; obcy etap bez odpowiednika idzie do
  „Poza szablonem”. Wiersz BEZ etapu zostaje przy samym kodzie. Tę samą regułę
  czytają tablica, kolumny listy rekrutacji, „wymaga ruchu” i kolejka.
- **„Czeka na Ciebie” zna cały przepływ (04.10.2026)** — `services/board_flow.py`,
  pola `flow` i `finance` w `GET /api/board-tasks` (każda sekcja w savepoincie,
  ≤ 20 wierszy + suma): rekruter/TCM/DL — Ogłoszenia per rekrutacja, blokady
  12 h, Screening bez arkusza albo stawki, Zweryfikowani bez QC CV (zakres =
  rekrutacje, w których osoba jest Rekruterem; TCM + jego kategoria); DL —
  „Czeka na klienta” (CV wysłane > 7 dni, w „U innych”), umowy B2B
  niepodpisane > 2 dni, zamówienia z maila do weryfikacji; Finanse (moduł
  Finanse) — braki, nowe PDF-y, nieudane maile, zatrudnieni bez zamówienia.
  Rola z przepływem przy pustej kolejce widzi „Nic na Ciebie teraz nie czeka.”
  zamiast znikającego panelu; Finanse nie dostają „CV w drodze”. Poranny
  dzwonek bez zmian (Ogłoszeń w nim nie ma). Front: `BoardFlowSections.tsx`.
- **Kolejka „Czeka na Ciebie” (0348, decyzje Artura 22.09.2026)** —
  `services/board_tasks.py`, `GET /api/board-tasks`, panel `BoardTasksPanel`
  nad układem pulpitu (nie kafelek: ma dotrzeć do osoby, która pulpitu nie
  układała). Liczona z NAJNOWSZEGO wiersza pary w opublikowanych rekrutacjach,
  ruchy z ostatnich 14 dni: „Czeka na DZ” (etap `verified`-gospodarz w szablonie
  z etapem DZ; Delivery Lead widzi swój portfel + rekrutacje, w których jest
  DL-em, HoR i admin — wszystko), „Do wysłania do Cpro” i „Wysłane do Cpro”
  (Nordea: „CV wysłane” TO JEST wysłanie do Cpro — kolumna nazywa się tak
  u Nordei, `foldBoardColumns(…, { cproEnabled })`). **Do Cpro wysyła JEDNA
  osoba na całą rekrutację** (0353, decyzja Artura 23.09.2026 — koryguje
  „typujemy za każdym razem” z 22.09): `jobs.cpro_sender_id`, ustawiane
  `PUT /api/board-tasks/cpro/jobs/{job_id}/sender` z paska „Do Cpro wysyła”
  nad Tablicą (`CproSenderBar`) albo z grupy rekrutacji w kolejce (lista
  „Do wysłania do Cpro” jest pogrupowana po rekrutacji, „Wysyłaj z
  rekrutacji” prowadzi na Tablicę). Przełącznik „Gotowy do Cpro” w doku nie
  pyta już o osobę. `candidate_stages.task_assignee_id` (0348) zostaje
  zapasem, gdy rekrutacja nie ma osoby; `StageMove.task_assignee_id` ustawia
  osobę dla rekrutacji (zgodność wstecz; inny etap niż Cpro = 422). Osoba
  spoza zespołu zostaje dopisana jako collaborator (tylko przez role DZ).
  „✓ DZ” z pulpitu to zwykły `/move` z wersją procesu — kolejka nie ma
  własnej ścieżki zapisu etapu. Rano (8–17, pierwszy tick) JEDEN dzwonek
  `board_tasks_digest` na osobę; ustawienie osoby = dzwonek
  `cpro_send_assigned` (encja: rekrutacja).
- **Przegląd przed DZ (0353)** — „Sprawdź” przy osobie z kolejki DZ otwiera
  `DzReviewDialog`: CV dla klienta (CV firmowe pary, sfinalizowane > szkic,
  bez niego najnowsze gotowe CV z generatora), oryginał (snapshot etapu,
  bez niego `raw_cv_text`) i zapytanie klienta (must/nice z
  `requirements_for_job` w pisowni DL-a, opis, „O projekcie”). Trzy
  sprawdzenia Dominika liczy KOD (`services/dz_review.py`): must-have w CV,
  pogrubiony (bez pogrubień szablonu: nagłówek roli, etykiety „…:”), obecny
  w każdej roli, w której jest w oryginale (role generatora po
  `data-cv-section`, bez znaczników — po nazwach firm z `candidate.experience`).
  Podpowiedzi GPT-6 Luny (`AIFeatureKey.dz_review`, F21) są doradcze:
  awaria = `status: unavailable`, nigdy 5xx; wynik pamiętany w
  `dz_review_hints` per (wiersz etapu, skrót wejścia z wersją promptu
  i modelem), cytat spoza obu tekstów jest usuwany. Treść CV idzie do
  przeglądarki jako bloki tekstu z flagą pogrubienia, nigdy HTML. Trasy
  `GET …/dz/{stage_id}/review` i `POST …/dz/{stage_id}/hints` tylko dla ról DZ
  z dostępem do rekrutacji. Harness `/preview/dz-review`.
- *(Pasek filtrów usunięty 02.10.2026 — sekcja „Prostszy ekran rekrutacji”.)*
- **Filtry Tablicy = jeden pasek nad tablicą** (`PipelineFilterBar`) zamiast
  lewej kolumny: na wierzchu nazwisko i „Mój ruch" (owner następnego kroku =
  rekruter, ta sama `nextActionFor` co karta), reszta w „Filtry ▾" z licznikiem
  aktywnych (utknęli, bez akcji, ostrzeżenia, poza szablonem, rekruter, puste
  kolumny); po prawej „N w procesie · M utknęło" i SLA. Filtry PRZYGASZAJĄ karty, nigdy
  ich nie usuwają (indeksy `@hello-pangea/dnd`).
