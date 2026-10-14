# „Do wysłania do klienta” — kolejka Delivery Leada widoczna wszędzie (13.10.2026)

Pytanie Artura z 13.10.2026: skąd Delivery Lead wie, że ma kogoś wysłać do
klienta. Makiety: https://claude.ai/artifact/BxX2afNFMkzxJK2pvWHJte, raport
`docs/dl-send-queue-completion-report.md`. Pomiar na produkcji tego dnia:
15 par w „QC CV” poza Nordeą u 4 Delivery Leadów, z czego 8 z QC do poprawy
(ruch rekrutera); dzwonek „CV do przeglądu” — 34 wpisy w 30 dni, przeczytane 2;
stare przypomnienie o etapie „CV wysłane” — 4 695 wpisów do 8 osób.

- **Jedna reguła na serwerze: `services/dl_send_queue.py`.** Wiersz = najnowszy
  wiersz pary na etapie QC opublikowanej rekrutacji (od 13.10.2026 także
  Nordei: `cpro=True`, celem jest etap „Wysłać do Cpro”, dopisek „→ Cpro” —
  `rekrutacja-tablica/nordea-akceptacja-dl-przed-cpro.md`),
  BEZ okna czasu (do tej daty 30 dni — karta znikała z pulpitu, choć stała na
  Tablicy). Czytają go pulpit (`board_tasks.load_snapshot`), górny pasek i menu
  (`GET /api/board-tasks/dl-send`), poranny dzwonek i mail, lista rekrutacji,
  przypomnienie rekrutera i sygnał dla Head of Recruitment. Nie dokładaj
  drugiej definicji w SQL — warunek obejścia QC (`cv_qc._override_applies`)
  ma mieć jednego czytelnika.
- **„Gotowe” (`ready`) = QC zdane albo przepuszczone** — ta sama reguła, którą
  karta Tablicy stosuje od v5. Reszta kolumny „QC CV” jest „jeszcze u
  rekrutera”: stoi w pasie jako zwinięta linia i NIE liczy się do licznika,
  dzwonka ani przypomnień Delivery Leada (`counts_for_reviewer`).
- **„Czeka” liczy się od gotowości, nie od wejścia do kolumny:**
  `ready_since` = wejście do „QC CV” albo zaliczenie QC (`pair_statuses` →
  `ok_at`), co później. Czas poprawek rekrutera nie obciąża Delivery Leada
  w kolorach, przypomnieniach ani sygnale. Pilność w DNIACH ROBOCZYCH
  (`workdays_between`, święta polskie): 1 = bursztyn (`due`), 2 = czerwień
  (`late`) i „Przypomnij” u rekrutera, 3 = sygnał dla Head of Recruitment
  (`STALE_WORKDAYS`). Na ekranie czas stoi jak wszędzie („od 3 dni”,
  kalendarzowo) — dni robocze sterują tylko tonem i progami.
- **Etap z importu Traffita nie budzi** (`imported`, decyzja z 11.10.2026 —
  `notification_triggers._set_in_nexus`): wiersz jest w pasie jako osobna
  zwinięta linia, poza licznikami, dzwonkiem, przypomnieniem i sygnałem, aż
  ktoś ruszy kartę w NEXUSIE. Wiersz zrobiony w NEXUSIE ma
  `external_source='manual'`, nie NULL.
- **Czyj przegląd: `board_tasks.reviews_as_dl`** (lustro w SQL:
  `dl_send_queue.reviewer_scope_clause`) — aktywny Delivery Lead rekrutacji,
  bez niego Delivery Leadzi z portfelem klienta; admin i Head of Recruitment
  bez roli DL — nie. To co innego niż prawo wysyłki (`recruitment_manage`):
  przycisk „Przejrzyj i wyślij” widzi każdy, kto może wysyłać, a „Twój ruch”
  i „Czeka na Ciebie” tylko właściciel przeglądu (`viewer_owns_dl_review`
  z widoku Tablicy).
- **Pulpit:** pas „Do wysłania do klienta” (`dashboard/DlSendQueueBand.tsx`)
  stoi nad „Czeka na Ciebie”, tylko u Delivery Leada. Czyta pełne wiersze
  z `GET /api/board-tasks` (ten sam klucz co panel — bez drugiego zapytania).
  Sekcji „Czeka na Twój przegląd (DL)” w panelu już nie ma; pusty stan dla DL-a
  mówi pas („Nikt nie czeka teraz na wysyłkę do klienta.”), nie panel.
- **Górny pasek i menu:** pigułka `shell/DlSendTopbarButton.tsx` i licznik przy
  „Rekrutacjach” liczą STAN kolejki z lekkiej trasy `/dl-send` (wąski wiersz
  `DlSendRow`, zakres patrzącego w SQL). To nie drugi dzwonek: nie da się go
  „przeczytać”, maleje po wysłaniu, odrzuceniu albo cofnięciu karty. Przy
  zerze i bez roli DL go nie ma. Okienko nie importuje przeglądu (pdf.js) —
  wiersz prowadzi na Tablicę (`?candidate=&review=1`). Zapis z 22.09.2026
  „Rekrutacje nie mają licznika” dotyczył liczenia wszystkich rekrutacji;
  licznik w menu ma znaczyć „masz coś do zrobienia” i ten to spełnia.
- **Przegląd „po kolei”:** `hooks/useReviewSequence.ts` (migawka kolejności +
  zbiór załatwionych, wzorzec kolejki Cpro) i `DlReviewBody` z `onDecided`
  (wołane ZAMIAST zamknięcia) oraz `sequence` w linii nagłówka. Wejścia: pas na
  pulpicie, okienko w pasku (`/dashboard?wysylka=po-kolei`) i druga linia
  nagłówka kolumny „QC CV” na Tablicy.
- **Tablica:** nad tablicą NIC nie dochodzi (decyzja z 02.10.2026 i test
  1280×720) — karta właściciela ma „Twój ruch”, plakietkę „Czeka na Ciebie ·
  N dni” i przycisk „Przejrzyj i wyślij”; „Przejrzyj po kolei (N)” zastępuje
  opis kolumny od 2 gotowych osób. `onAdvance` otwiera „Przesuń dalej”, nie
  przegląd — przycisk idzie przez `onReviewSend`. Strzałka karty bez braków ma
  od 14.10.2026 własną obsługę (ruch odroczony z „Cofnij”, `droga-rekrutera-do-dl.md`, D7).
- **Tablica liczy jak pas (14.10.2026).** Karta niesie `dl_send_counts`: rekrutacja opublikowana
  i bieżący etap nie z importu Traffita, czyli ten sam zakres co `dl_send_queue`. Przy `false`
  karta nie ma „Czeka na Ciebie” ani „Czeka na DL”, nie ma „Twój ruch” i nie wchodzi do
  „Przejrzyj po kolei” (`countsForDlReview`). Przycisk „Przejrzyj i wyślij” zostaje
  (`isReadyForDlSend`). Powód: audyt 13.10 pokazał, że Tablica wliczała karty z importu i karty
  zamkniętych rekrutacji, których pas nie liczy. „Moje następne kroki” pytają o „czyj przegląd”
  raz na żądanie (`_viewer_owns_dl_review(memo=…)`), a nie raz na każdą tablicę.
- **Lista rekrutacji:** bez nowej kolumny (tabela ledwo mieści się przy
  1280 px). Komórka „QC” w „Etapach” świeci u Delivery Leada, gdy ktoś czeka
  na jego wysyłkę (`dl_send_ready_count` pod `include_stage_counts`), a filtr
  „Do wysłania do klienta” stoi w „Więcej filtrów” (`dl_send=mine|stale`,
  w adresie `tosend=`). Czwarty przełącznik w pasku się nie mieści.
- **Przypomnienia:** poranny dzwonek wymienia dwie najdłużej czekające osoby
  („Do wysłania do klienta: Marta Z. (6 dni), … i 3 inne osoby”) i liczy
  tylko gotowe; poranny mail ma sekcję „Do wysłania do klienta” z „czeka
  N dni”. Rekruter w „Twoje CV w drodze” widzi stan QC i od 2 dni roboczych
  „Przypomnij” (`POST /api/board-tasks/dl-send/{stage_id}/nudge`: właściciel
  wiersza, karta gotowa i nie z importu, dzwonek `board_task_waiting` z tytułem
  `TITLE_DL_NUDGE`, raz dziennie przez indeks dedup, ślad w `Activity`; bez
  nowego typu i bez migracji). Head of Recruitment dostaje w „Gdzie stoi”
  sygnał `dl_send_stale` (3+ dni robocze).
- **Stary trigger `check_dl_stage_stale_6h` usunięty** — przypominał o etapie
  „CV wysłane”, czyli o osobach już wysłanych (zostało po przepływie sprzed
  v5). Typ powiadomienia, kategoria i grupa zostają dla historii.
- **Dzwonek i mail przy przekazaniu karty bez zmian** — wychodzą przy wejściu
  do „QC CV”, zanim QC policzy wynik. Osobny dzwonek „gotowe” to świadomie
  odłożona decyzja; o gotowości mówi stan (pas, pigułka, poranny wpis).
- Harnessy: `/preview/dl-send`, `/preview/custom-dashboard?as=dl`,
  `/preview/pipeline-v4?as=dl`, `/preview/jobs-list-v3`.
