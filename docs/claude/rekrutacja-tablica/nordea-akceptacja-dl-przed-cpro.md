# Nordea: do kolejki Cpro dopiero po akceptacji Delivery Leada (13.10.2026)
<!-- indeks: „Akceptuj — do Cpro” ze stawką, bramka serwera, dzwonek od Cpro -->

Zgłoszenie Artura z 13.10.2026: osoba od Cpro dostawała „Do wrzucenia do
Cpro”, gdy rekruter kończył QC, zanim Delivery Lead Nordei zaakceptował
kandydata. Pomiar na produkcji z 12–13.10 (pierwsze dni bez Traffita): 7 z 13
wejść do kolejki bez DL-a, 11 z 12 dzwonków bez stawki do Cpro, DL sam
oznaczał „Wysłane do Cpro” (8 z 10 ruchów), bo tylko tam NEXUS pytał
o stawkę. W Traffit do kolejki wkładali DL-e (292 z 301 wejść) — ten ruch był
akceptacją, a przenosiny v4/v5 („Nordea bez zmian”) oddały go rekruterowi.
Makiety i decyzje D1–D6: https://claude.ai/artifact/Si7j1pcC3cXxUKYMNVGWa1.

- **„QC CV” u Nordei = przegląd DL, jak u innych klientów.** Rekruter po QC
  klika „Przekaż Delivery Leadowi” (`move_requirements`, `hand_to_dl`);
  dzwonek i mail „CV do przeglądu” idą do DL-a rekrutacji, bez niego do DL-i
  z portfelem Nordei (`stage_handoff_recipients._dl_reviewers`). Osoba trafia
  do pasa „Do wysłania do klienta”, okienka w pasku, „Przejrzyj po kolei”
  i „Porównaj” (`BoardTask.cpro`).
- **Wiersz Nordei mówi „Cpro” tam, gdzie się nie ucina (14.10.2026).**
  W pasie plakietka „do Cpro” stoi w drugiej linii komórki „Rekrutacja”,
  w okienku paska — przy nazwisku (`CPRO_ROW_BADGE` w `lib/api/boardTasks.ts`).
  Dopisek „· → Cpro” na końcu linii rekrutacji znikał za wielokropkiem przy
  1280 px — nie wracaj do niego. Przycisk przeglądu u Nordei to „Przejrzyj
  → Cpro” (pas i karta Tablicy, `CPRO_REVIEW_LABEL`), nie „Przejrzyj
  i wyślij”: nic nie idzie do klienta. Etykieta jest krótka z pomiaru: przy
  1280 px z przypiętym menu kolumna przycisku w pasie ma 131 px treści,
  a „Przejrzyj i zaakceptuj” ma 150 px. Bez prawa wysyłki zostaje „Przejrzyj”.
- **Akceptacja = ruch na etap „Wysłać do Cpro” z przeglądu.** Cel wiersza
  przeglądu to `stages.cpro_id` (`dl_send_queue.load_rows`), przycisk
  „Akceptuj — do Cpro za …”, pole „Stawka do Cpro” (wymagane), uwaga dla
  osoby od Cpro to zwykłe `recruiter_remark` (`stage_remarks`, dochodzi do
  dzwonka). Szablon bez etapu Cpro = cel `None`, przegląd to mówi.
- **Serwer: do kolejki Cpro i na „Wysłane do Cpro” z pominięciem kolejki
  wchodzi tylko osoba z uprawnieniem wysyłki CV** (`recruitment_manage`)
  **i ze stawką** — `pipeline_move_rules.requires_dl_client_rate` z nazwą
  etapu, `/move` i `/bulk-move`; 403 „Do kolejki Cpro przekazuje Delivery
  Lead po akceptacji…”, 422 „Wpisz stawkę do Cpro…”. Karta, która już stoi
  w kolejce, tej bramki nie przechodzi drugi raz (`arrives_from_before_client_send`),
  więc „✓ Wrzucone” osoby od Cpro działa bez zmian. Stawka zapisana wcześniej
  w tej rekrutacji wystarcza.
- **Para zamknięta z kolejki Cpro wraca przez akceptację (14.10.2026).** Wyjątek „już stoi
  w kolejce” obejmuje tylko kartę, której najnowszy wiersz jest wierszem Cpro. Audyt 13.10
  pokazał, że para odrzucona z kolejki wracała do niej („Przywróć”, ruch na „Wysłane do Cpro”)
  bez Delivery Leada, bo bramki liczą się kolumną sprzed zamknięcia. Teraz taki powrót wymaga
  uprawnienia wysyłki. Stawka zapisana wcześniej dalej wystarcza. Odmowę `/bulk-move`
  u Nordei (403 i 422) pokrywa `test_fix48_ws01_db.py`.
- **Dzwonek osoby od Cpro dopiero po akceptacji**, z nazwą od klienta
  i numerem w tytule (`_cpro_job_label`, temat maila to tytuł) — ta sama osoba
  w dwóch rekrutacjach Nordei nie daje dwóch identycznych dzwonków. Kwota
  nigdy nie idzie dzwonkiem ani mailem („Stawka do Cpro jest wpisana”).
  Prefiks `TITLE_CPRO_QUEUE` zostaje — od niego zależy rodzaj maila
  i przypomnienie po imporcie Traffita.
- **Dzwonek gaśnie, gdy karta wyjdzie z kolejki** (DL oznaczy „Wysłane do
  Cpro”, zwrot, odrzucenie): `stage_handoff_recipients.close_cpro_queue_bells`
  w transakcji ruchu, tylko dzwonki tego wiersza kolejki.
- **Zwrot z kolejki Cpro** („Nie da się wrzucić”) wraca do „QC CV”, czyli do
  przeglądu DL: dzwoni do osoby, która włożyła kartę do kolejki, i do DL-a
  rekrutacji. „Wróć do poprawy” z polami działa u Nordei jak wszędzie;
  osoba od Cpro, która zwróciła kartę, nie dostaje dzwonka o poprawkach.
- **Kolejka Cpro mówi, kto zaakceptował** (`CproQueueItem.accepted`,
  `accepted_by_name`, `accepted_at`, `dl_note`). Karta włożona przez
  rekrutera przed 13.10.2026 ma „Bez akceptacji DL” — nic nie przesuwamy na
  produkcji; osoba od Cpro może ją zwrócić i wtedy trafia do przeglądu DL.
- **Na Tablicy** jedna droga: `openDlReviewIfSending` u Nordei przyjmuje ruch
  na „Wysłane do Cpro” albo na etap Cpro i otwiera przegląd z celem Cpro;
  karta w kolejce (znacznik `cpro`) czeka na osobę od Cpro, nie na DL-a
  (`isReadyForDlSend(item, column, inCproQueue)`).
- Harnessy: `/preview/dl-review?client=cpro`, `/preview/cpro-queue`
  (wiersz zaakceptowany i „Bez akceptacji DL”), `/preview/dl-send` (wiersze
  z plakietką „do Cpro”).
