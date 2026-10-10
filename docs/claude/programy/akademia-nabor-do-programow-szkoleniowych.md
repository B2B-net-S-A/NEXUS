# Akademia — nabór do programów szkoleniowych (0369, 24.09.2026)

`/academy` (menu „Więcej” → Codzienna praca): ogłoszenia → sortowanie Luny →
dwuminutowy telefon z zapisem na termin w biurze → spotkanie → zadanie →
dokumenty i umowa → edycja (program do 10 dni roboczych). Decyzje Artura
23–24.09.2026. Kod: `api/academy.py`, `services/academy.py` (baza),
`academy_rules.py` (sortowanie), `academy_flow.py` (przejścia),
`academy_documents.py` (komplet DOCX); front `components/academy/*`,
`lib/academy-flow.ts`, harness `/preview/academy`.

- **Stan osoby żyje w `academy_applications`, NIE w `candidate_stages`.**
  Tablica rekrutacji ma bramki (DL przy „CV wysłane”, debrief, blokada 12 h),
  których ten przepływ nie ma, a nocny import Traffita pisze etapy
  ogłoszeń-źródeł. Źródło = rekrutacja podpięta w Ustawieniach; każdy
  kandydat z wierszem etapu od `since` wpada sam (pętla `academy_intake` co
  10 min, przycisk „Pobierz zgłoszenia teraz”).
- **Jedna osoba = jeden wiersz w programie (UNIQUE), więc „nie” jest na
  zawsze** (decyzja 24.09). Odrzucony, który aplikuje znowu, dostaje tylko
  `reapplied_at` — nie wraca do telefonów, Luna nie czyta CV drugi raz.
  Zrezygnował sam (`withdrew`) = wraca na początek. „Przywróć” cofa decyzję.
- **Luna tylko sortuje; wykluczenie zawsze klika człowiek** (zbiorcze
  „Zatwierdź” odłożonych bierze powód z sortowania). Umowa uczestnictwa §5a
  ust. 8 obiecuje brak zautomatyzowanego podejmowania decyzji — nie zamieniaj
  werdyktu `skip` w automatyczne `rejected`.
- **Kryteria: polski ojczysty/biegły + doświadczenie ≤ N lat liczone OD KOŃCA
  STUDIÓW** (praca w trakcie studiów się nie liczy; bez studiów — cała praca;
  przedziały scalone). Liczbę lat i werdykt liczy KOD z profilu; Luna
  (`academy_screening`, F23) uzupełnia z CV tylko brakujące fakty, każdy
  z cytatem obecnym w CV. **Filtra po „polskim” imieniu/nazwisku, narodowości
  i wieku NIE budujemy** (dyskryminacja — odmowa 24.09.2026); model nie
  dostaje narodowości z profilu i ma zakaz wnioskowania z imienia.
- **Po audycie 24.09.2026:** cytat Luny musi zawierać rok pracy albo rok
  ukończenia studiów, a przy polskim — słowo o języku (przy „podstawowy” także
  poziom); stanowisko profilu bez daty końca dalej niż na 1. pozycji = „bez dat”.
  Zbiorcze „Zatwierdź” odrzuca tylko osoby, które nadal mają `new` + `skip`.
  Scalanie kandydatów: odrzucenie wygrywa z nowszym zgłoszeniem. Lista
  zgłoszeń: najpierw osoby w toku, najnowsi pierwsi; limit ucina najstarszych
  zamkniętych, a ekran mówi „Pokazano N z M”.
- **Runda 8 (26.09.2026):** „skip” pamięta wersję reguł i kryteria programu
  (`screening.criteria`, `SCREENING_VERSION` 3); zmiana limitu lat albo wymogu
  polskiego i zmiana reguł oddają odłożonych do ponownego sortowania
  (`reset_stale_skips`), a „Zatwierdź” odmawia starego werdyktu. Studia bez
  roku końca + staż ponad limit = „do decyzji”; „present” od Luny wymaga
  „obecnie” w cytacie albo tuż za nim. Z „W akademii” da się „Zrezygnował sam”
  (decyzja Artura 26.09.2026); odejście przed spotkaniem zwalnia termin.
- **Dokumenty** (`POST /api/academy/applications/{id}/documents`, ZIP: umowa,
  zał. 1 harmonogram, oświadczenie, regulamin, protokół Manuala) od etapu
  „zaliczył zadanie”. **PESEL i adres idą wyłącznie do pliku** — nie do bazy
  ani logu; puste = kropki do wpisania ręcznie. Daty programu domyślnie:
  1. dzień roboczy miesiąca edycji + 10 dni roboczych (polskie święta).
  Szablony `app/templates/academy/*.docx` buduje
  `scripts/build_academy_templates.py` ze wzorów działu (poza repo) —
  przykładowe osoby z wzoru protokołu są polami; nowy wzór = ponowny bieg
  skryptu, nie ręczna edycja DOCX.
- Terminy w biurze mają limit miejsc (409 `session_full` pod blokadą
  terminu); ustawienia programu i źródła zmienia admin/HoR, pracę z ludźmi
  i terminy — `RecruiterPlus` (router za sekcją Pipeline).
