# QC CV: tryb doradczy, role z odczytu CV, „Potwierdzone z kandydatem” (12.10.2026)
<!-- indeks: QC doradza zamiast blokować (wyłącznik `CV_QC_ADVISORY`), skąd QC wie, w której roli kandydat czego używał, potwierdzenie z kandydatem jako notatka, przeliczenie przebiegów po zmianie reguł -->

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
- **Obejście doradcze działa do następnego ruchu karty**
  (`cv_qc._override_applies`: wiersz z `result.override_advisory`, po którym
  nie ma jeszcze nowszego wiersza etapu pary). Obejście osoby od wysyłki
  (Delivery Lead, admin) dotyczy pary bez końca, jak dotąd. Bez tego cofnięcie
  karty nic by nie znaczyło: rekruter przesunąłby ją drugi raz po cichu, na
  starym obejściu i bez nowego dzwonka. Tę samą regułę czyta bramka ruchu,
  plakietka na Tablicy (`pair_statuses`) i okno QC — nie rozdzielaj ich.
  Przegląd DL pokazuje powód rekrutera także po ruchu na „QC CV”
  (`_latest_override(include_spent=True)`), choć QC jest wtedy znów „do
  poprawy” i wysyłka wymaga decyzji Delivery Leada.
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
  istniejące „Wróć do poprawy” (lista pól z `cv`). U Nordei przeglądu DL nie ma
  — DL weryfikuje z dzwonka, kolejka Cpro pokazuje „przepuszczone mimo QC”.
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
  w której oryginał wymienia krytyczną” (02.10.2026) zostaje.
- **Pozycja niesie dowód:** `evidence` (zdanie z opisu roli, lista technologii
  roli albo nazwa stanowiska) i `evidence_kind`; sprawdzenie niesie `roles`
  („rola po roli”: `described` / `missing` / `not_in_original` / `unverified`).
- **Cytat poprawki AI** (`parse_fixes`) nie może być listą technologii ani
  pochodzić na pewno z innej roli (stoi w odczycie innej roli albo w pliku
  najbliższa poprzedzająca go nazwa firmy to inny pracodawca). Cytat nie do
  przypisania przechodzi. Do 12.10.2026 serwer przyjmował zdanie o Pythonie do
  roli supportu z cytatem „Python, Java, SQL” z sekcji umiejętności.
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
  `tasks/cv_qc_recompute.py`) przelicza nieudane przebiegi starszej wersji par
  sprzed wysłania i samo się wygasza. Przebieg starszej wersji dostaje nowy
  wiersz także przy identycznym wyniku.
- **Poza zakresem, świadomie:** „jedna opisana rola wystarcza” (po zmianie
  dotyczyłoby 1 pary), automatyczny ponowny odczyt CV dla kandydatów bez
  odczytu ról, luźniejsze dopasowanie zapisu w „spoza oryginału” (ryzyko
  „Java” w „JavaScript”).
