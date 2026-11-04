# Rekrutacja „wersja 3" — jedna tabela + panel osoby (21.09.2026, #1641 #1657 #1659)

Decyzje Artura z 21.09.2026 (makiety „Wersja 3"): rekrutacja to JEDNA tabela osób
(`components/v2/recruitment/`) z panelem osoby i oknami wysuwanymi; kanban zostaje
jako przełącznik widoku (`?tab=board`). **Od 22.09.2026 tabela osób jest usunięta
— patrz „Podobne rekrutacje…" wyżej; reguły poniżej dotyczą panelu osoby,
propozycji i ruchu etapu, które zostały.** Włączone dla wszystkich ról, bez flagi per
użytkownik. Pulpit, lądowanie po loginie i pasek górny — bez zmian. Raport:
`docs/recruiter-v3-completion-report.md`.

- **Żadna funkcja nie znika — pilnuje tego inwentarz**
  (`lib/recruitment-feature-inventory.json` + `recruitment-feature-parity.test.ts`):
  każdy wpis ma marker w nowym pliku, każdy stary `?tab=` ma alias w `page.tsx`,
  usunięcie wpisu wymaga `removed_reason`. Stare linki (także zapisane w bazie
  powiadomień: `?tab=similar`, `champion`, `chat`) działają.
- **Ruch etapu tylko przez `hooks/usePipelineMove.tsx`** (okna przepływu zwraca jako `dialogs` — wyrenderuj raz)
  (stawka „Zweryfikowany", stawka klienta, „Zatrudniony", odrzucenie z cofnięciem,
  „Przenieś mimo to", konflikt wersji 409, unieważnienie OBU kluczy kanbana).
  Nowy ekran wysyłający `/api/pipeline/move` własną mutacją = regresja.
- **„Kto ma ruch" liczy JEDNA reguła w dwóch lustrach**: `lib/pipeline-next-action.ts`
  i `services/pipeline_next_action.py`, oba czytają `lib/__fixtures__/next-action-cases.json`.
  Właściciele: recruiter · **review** · client · candidate · delivery · none.
  `review` = stos wejściowy (Ogłoszenia / Nowi) — decyzja Artura: „Wymaga ruchu"
  go NIE liczy, lista rekrutacji pokazuje go osobno jako „Do przejrzenia"
  (`review_count`). Bez tego licznik „wymaga ruchu" na rekrutacji z ogłoszeń
  pokazywał setki osób i nic nie znaczył.
- **Grupy tabeli domyślnie**: nigdy wszystkie zwinięte (`defaultCollapsedFor`),
  a panel otwiera się sam na pierwszej WIDOCZNEJ osobie (`firstVisibleRowKey`)
  tylko od 1280 px. Sekcja panelu zależy od grupy i etapu
  (`defaultPanelSectionFor(group, column)`).
- **Propozycje z bazy = `job_proposals` (0333) + żywy przegląd + podobne projekty
  + rekomendacje + Targ**, dedup po kandydacie, kolumna Źródło z wieloma
  plakietkami. Przegląd wspólny dla zespołu (`shared_auto_run`) jest adoptowany,
  gdy osoba nie ma własnego. Status przeglądu ZAWSZE nad tabelą (`compact`
  = jedna linia + „Szczegóły przeglądu"); awaria = „nie wiadomo" + „Ponów",
  nigdy pustka. Licznik segmentu to liczba WIDOCZNYCH propozycji
  (`jobProposalsKeys.visibleCount`), nie surowy wiersz tabeli.
- **Automaty w tle (0335) są domyślnie WŁĄCZONE** — decyzja Artura:
  `AUTO_FULL_REVIEW_ENABLED` (przegląd bazy w nocy 01–05 `BUSINESS_TZ`, maks. 20
  rekrutacji/noc, profil wag bez użytkownika, przeglądy `origin=auto` poza
  ochroną retencji), `AUTO_MATCH_MODE` (brak = `propose`: nowe CV trafia do
  propozycji, NIGDY wprost do pipeline'u; `add` tylko decyzją), 
  `CV_AUTO_GENERATE_ON_VERIFIED` (CV firmowe w trybie „Pod rekrutację" po ruchu
  na „Zweryfikowany", hak po commicie, nigdy nie zmienia wyniku ruchu; brak
  zrzutu zgody RODO nie blokuje generacji, blokuje wysyłkę). Zdarzenia widać
  w oknie „Historia i czat" → „Praca w tle". Nic zewnętrznego ani
  nieodwracalnego bez kliknięcia.
- **Menu: Dashboard · Rekrutacje · Kandydaci + „Więcej"** z jednego rejestru
  `lib/nav-registry.ts` (czytają go sidebar i ⌘K). Pozycja w „Więcej" ma
  `moreHint` (jedno zdanie), a dostępną nazwą przycisku zostaje sama etykieta
  (`aria-describedby` na podpowiedź). `SIDEBAR_VERTICAL_LAYOUT` nietknięte.
- **Linki klienta do CV są wyłączone flagą `CV_CLIENT_LINKS_UI_ENABLED`**
  (#1647 wygrywa z makietą „wariant B"): warsztat CV i wysyłka zbiorcza oznaczają
  „CV Wysłane" bez linku.
- **Znane rozbieżności z makietą (świadomie, 21.09):** przypinanie pozycji
  w „Więcej" niezrobione; stawka/dostępność w tabeli głównie „—",
  bo dane w bazie są puste.
