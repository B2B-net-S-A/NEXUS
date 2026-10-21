# QC CV: tryb doradczy, role z odczytu CV, „Potwierdzone z kandydatem” (12.10.2026)
<!-- indeks: `CV_QC_ADVISORY`, potwierdzenie jako notatka -->

Trzy zgłoszenia zespołu z 12.10.2026 kończyły się tym samym — rekruter nie mógł
przesunąć karty: QC żądało zdania o „python lub java” w roli supportu, „testing”
stało w CV, choć oryginał o nim nie mówił (kandydat potwierdził w rozmowie),
a obejście miał tylko Delivery Lead. Pomiar na produkcji (45 dni, tylko odczyt):
47 par z QC, 34 zablokowane; 17 przez „spoza oryginału” (10 wyłącznie przez to);
z 13 braków „krytyczna × rola” 12 stało na zgadywaniu z tekstu pliku; 26 z 41
kandydatów w QC nie miało opisów ról w historii profilu.

- **QC doradza, nie blokuje — na czas wdrażania zespołu (decyzja Artura).**
  Wyłącznik `CV_QC_ADVISORY` (domyślnie `True`). W trybie doradczym „Przepuść
  mimo QC” ma każdy, kto może przesuwać karty rekrutacji (ta sama bramka co
  ruch i poprawki: `ensure_job_membership`; od 23.09.2026 rekrutacje są wspólne
  dla ról wewnętrznych, więc nie ma osobnej bramki „rekruter przypisany”).
  Bramka ruchu (`_assert_cv_qc_gate`) zostaje: bez QC albo świadomego obejścia
  z powodem ruch na „CV wysłane” i do kolejki Cpro dalej daje 409 — rekruter
  ma kliknąć „Przesuń mimo uwag…”, a nie przejść niezauważenie. `False`
  przywraca obejście wyłącznie osobie z uprawnieniem `recruitment_manage`.
  Powrót do blokady = ta jedna wartość (kod albo workflow „Coolify set env”);
  podstawą decyzji ma być liczba obejść rekruterów i cofnięć Delivery Leada.
- **Obejście doradcze działa do zwrotu karty.** Wiersz obejścia rekrutera
  niesie `result.override_advisory`; każdy ruch inny niż naprzód (wstecz,
  z kolejki Cpro do „QC CV”, do „Zamkniętych”) zapisuje mu
  `override_spent_at` (`pipeline._spend_advisory_qc_override_on_return` →
  `cv_qc.spend_advisory_overrides`, w transakcji ruchu, także `/bulk-move`).
  Obejście osoby od wysyłki (Delivery Lead, admin) dotyczy pary bez końca, jak
  dotąd. Bez tego cofnięcie karty nic by nie znaczyło: rekruter przesunąłby ją
  drugi raz po cichu, na starym obejściu i bez nowego dzwonka. Naprzód
  obejście rekrutera przepuszcza wszystko — także wysyłkę przez Delivery
  Leada, który widzi baner z powodem — a kolejka Cpro pokazuje „przepuszczone
  mimo QC”. Tę samą regułę (`cv_qc._override_applies`) czyta bramka ruchu,
  plakietka na Tablicy (`pair_statuses`), okno QC i przegląd DL — nie
  rozdzielaj ich.
- **Obejście doradcze dotyczy wersji CV i trybu (14.10.2026).** Audyt 13.10
  pokazał, że obejście rekrutera przepuszczało dalej po zmianie CV i po
  `CV_QC_ADVISORY=False`, więc „powrót do blokady jedną wartością” nie
  działał. Teraz `_override_applies` liczy obejście doradcze tylko w trybie
  doradczym i tylko przy odcisku CV (`cv_fingerprint`), przy którym je
  zrobiono: bramka i okno porównują z CV liczonym teraz (`run_qc`), plakietka
  i przegląd DL — z CV najnowszego przebiegu pary. Obejście osoby od wysyłki
  bez zmian (bez końca). Zwrot karty zużywa każde niezużyte obejście doradcze
  (`has_live_advisory_override` bez warunku CV i trybu), żeby nie ożyło po
  powrocie do starego CV. Testy: `test_fix48_ws11_qc_override_rule.py`,
  `test_fix48_ws11_qc_pair_status.py`.
- **D6 (decyzja Artura, 17.10.2026): obejście idzie za CV, dopóki nie ma nowej
  blokady.** Przepuszczenie ginęło przy każdej zmianie treści, więc poprawka
  literówki po „Przekaż mimo uwag…” wymagała przepuszczenia od nowa. Teraz
  `run_qc` (bramka ruchu, okno QC, panel w edytorze, zapis przebiegu) woła
  `follow_advisory_override`: gdy bieżące blokady (`blocking_keys` — stałe
  klucze pozycji) są podzbiorem blokad zapisanych w wierszu obejścia, wiersz
  dostaje odcisk bieżącego CV. Reguła `_override_applies` (bramka, plakietka,
  przegląd DL) się nie zmienia. Nowa blokada — np. dopisana treść spoza
  oryginału — to nowy klucz, więc obejście nie idzie dalej. Tylko w trybie
  doradczym i tylko dla niezużytego obejścia; odcisk zmienia się w sesji
  wołającego (bez osobnego commitu). Test na bazie:
  `test_advisory_override_follows_the_cv_until_a_new_blocker_appears`.
- **Integracje nie decydują w QC.** Token klienta OAuth (scraper, n8n) działa
  jako konto z rolą operacyjną i przechodzi `ensure_job_membership`, więc
  obejście w trybie doradczym i `…/qc/confirm` odmawiają mu jawnie
  (`api/cv_qc._ensure_person`, 403) — dzwonek do Delivery Leada i notatka
  „potwierdzone z kandydatem” mają sens tylko z prawdziwym autorem.
- **Delivery Lead wie o obejściu.** Gdy przepuszcza osoba bez
  `recruitment_manage`, `cv_qc.record_override(notify_reviewers=True)` dzwoni
  do Delivery Leada rekrutacji (`stage_handoff_recipients._dl_reviewers`, typ
  `stage_changed`, tylko dzwonek, nigdy do autora). Przegląd DL pokazuje ryzyko
  `qc_overridden` i `qc_override` (kto, powód, kiedy). Cofnięcie do poprawy to
  istniejące „Wróć do poprawy” (lista pól z `cv`). U Nordei od 13.10.2026
  też jest przegląd DL (akceptacja do kolejki Cpro,
  `rekrutacja-tablica/nordea-akceptacja-dl-przed-cpro.md`); kolejka Cpro
  pokazuje „przepuszczone mimo QC”.
- **`can_override` i `advisory` liczy serwer** (`QcResponse`); front nie
  sprawdza uprawnienia lokalnie — inaczej przycisk i trasa rozjadą się przy
  przełączeniu trybu.
- **Tekst roli z oryginału = stanowisko + opis + technologie z odczytu TEJ
  roli** (`dz_review.original_roles`). Do 12.10.2026 doklejany był wycinek
  pliku od nazwy firmy do następnej firmy albo do końca dokumentu: ostatnia rola
  wchłaniała „Umiejętności / Kursy”, a firma wspomniana w podsumowaniu — to, co
  stało po nim. Nie wracaj do czytania ról z surowego tekstu pliku.
- **Skąd wpisy ról: `dz_review.role_entries(candidate, original_text)`.**
  Pełny odczyt CV v7 zostaje w `cv_extracted_data["experience"]` (klucz
  `description`) także wtedy, gdy `candidate.experience` pochodzi z importu
  Traffita i opisów nie ma. Odczyt wygrywa, gdy `has_rich_profile`, wpisy mają
  opis albo technologie i co najmniej połowa firm z odczytu stoi w tekście
  oryginału pary (odczyt opisuje najnowszy plik, a QC porównuje z migawką
  etapu). Inaczej historia profilu. Każdy, kto potrzebuje ról oryginału
  (`_qc_input`, `fixes_material`, `apply_action`, `build_review`), bierze je
  stąd; lata doświadczenia dalej liczą się z `candidate.experience`.
- **Bez opisów ról nie zgadujemy.** Gdy żaden wpis nie ma opisu ani
  technologii, pary wymaganie × rola mają stan `unverified`, sprawdzenie —
  status `manual` („Odczyt CV nie ma opisów ról — sprawdź role ręcznie”).
  Brak krytycznej w całym CV blokuje jak dotąd. Reguła „zdanie w każdej roli,
  w której oryginał wymienia krytyczną” (02.10.2026) zmieniona 13.10.2026:
  zdanie jest wymagane tylko tam, gdzie oryginał OPISUJE umiejętność w opisie
  roli; sama lista technologii albo nazwa stanowiska to informacja
  (`listed_only`) — patrz „QC CV mówi prawdę”.
- **Pozycja niesie dowód:** `evidence` (zdanie z opisu roli, lista technologii
  roli albo nazwa stanowiska) i `evidence_kind`; sprawdzenie niesie `roles`
  („rola po roli”: `described` / `missing` / `listed_only` / `not_in_original`
  / `unverified`).
- **Cytat poprawki AI** (`parse_fixes`) nie może być listą technologii ani
  pochodzić na pewno z innej roli (stoi w odczycie innej roli albo w pliku
  najbliższa poprzedzająca go nazwa firmy to inny pracodawca). Do 12.10.2026
  serwer przyjmował zdanie o Pythonie do roli supportu z cytatem „Python, Java,
  SQL” z sekcji umiejętności. Od 13.10.2026 cytat musi stać w tej roli albo
  w części pliku tej firmy, a cytat z rozmowy — w zdaniu, które nazywa firmę
  (szczegóły w „QC CV mówi prawdę”).
- **„Potwierdzone z kandydatem” to notatka pary**
  (`cv_qc.confirm_with_candidate`, `POST …/qc/confirm`): QC czyta notatki jako
  źródło obok oryginału, więc pozycja „spoza oryginału” znika bez zmiany
  reguły. Pochodzenie `note_kinds.QC_CONFIRM_SOURCE` rozstrzyga rodzaj `HUMAN`
  także po edycji (kwota w treści nie robi z niej zakrytego wpisu o stawce;
  wyjątek jak wszędzie: krótka para „X/Y” wpisana przez Delivery Leada albo
  admina to `dl_rate` — taki wpis nie jest źródłem dla QC i okno go nie cytuje).
  W treści nie ma tytułu rekrutacji — wymieniałby cudze wymagania i
  „potwierdzałby” je wszystkie. Notatka jest o kandydacie: liczy się też
  w innych rekrutacjach i w wyszukiwaniu. Okno pokazuje potwierdzenia
  (`QcResponse.confirmations`), żeby Delivery Lead widział, kto co potwierdził.
- **Zmiana reguł liczenia = podbij `cv_qc.QC_VERSION`.** Plakietka na Tablicy
  czyta zapisany przebieg; `cv_qc.recompute_outdated` (zadanie startowe
  `tasks/cv_qc_recompute.py`) przelicza nieudane przebiegi starszej wersji
  par sprzed wysłania i samo się wygasza (zaliczonych nie — nowy wiersz
  zerowałby czas oczekiwania w kolejce DL). Przed podbiciem
  zmierz stary i nowy kod skryptem `backend/scripts/qc_truth_audit.py`. Przebieg starszej wersji dostaje nowy
  wiersz także przy identycznym wyniku.
- **Poza zakresem, świadomie:** „jedna opisana rola wystarcza” (po zmianie
  dotyczyłoby 1 pary), automatyczny ponowny odczyt CV dla kandydatów bez
  odczytu ról. Luźniejsze dopasowanie zapisu zrobione 13.10.2026 z wyjątkami
  (`dz_review.found_in`: blokada „spoza oryginału” tylko ostrym trybem,
  „Java” ≠ „JavaScript”) — patrz „QC CV mówi prawdę”.
