# Rekrutacja v3: lista `/jobs` i „Więcej" w pasku bocznym

Decyzje właściciela: pulpit i topbar bez zmian, **nic nie znika** — zmienia się
miejsce, nie zbiór funkcji.

- **Klik w wiersz listy OTWIERA rekrutację** (`router.push`, Ctrl/⌘ = nowa
  karta; tytuł zostaje linkiem). Dok gotowości (`JobReadinessDock`, wariant
  `list`) otwiera ikona **„Podgląd"** w wierszu (`aria-label`
  „Podgląd: {tytuł}", `aria-pressed`), zamyka „Zamknij podgląd". Dok nie
  otwiera się sam, a wiersz `can_open === false` nie ma ani nawigacji, ani
  podglądu (dok pytałby o detal → 403). Gałąź `locked` wiersza
  (`interactive`, `onClick`, `aria-disabled`, tytuł bez linku) czyta test
  backendu `test_jobs_list_marks_unopenable_rows.py` — nie ruszaj jej.
  Dok stoi obok tabeli dopiero od 1680 px (`stickyFrom="wide"`); węziej
  wysuwa się z prawej NAD listę (pod górnym paskiem, bez przygaszania od
  `xl`) — jako kolumna przy 1280 px zabierał tabeli 360 px i akcje wiersza
  uciekały w bok. Wymaganie-zdanie stoi w Podglądzie jako punkt listy,
  krótkie (≤ 32 znaki) jako chip.
- **Lista ma jeden widok — tabelę (decyzja Artura 02.10.2026: „kafelki
  opcję wywal całkowicie”).** Przełącznik „lista / kafelki”, siatka kafelków
  i `jobsView` w `useUiStore` (migracja v10 zdejmuje pole) usunięte. Nie
  dokładaj drugiego widoku listy.
- **Zakres: „Moje | Moja kategoria | Otwarte | Wszystkie” (24.09.2026; „Moja
  kategoria” od 02.10.2026), domyślny zależy od
  ROLI** — `defaultScopeForUser` (`lib/jobs-url-filters.ts`, semantyka
  `hasRole`): recruiter, sourcer, tac, talent_community_manager, delivery_lead
  → „Moje” (także konto wielorolowe z którąkolwiek z nich); admin,
  head_of_recruitment, finance i viewer `user` → „Otwarte” (`open_only`,
  zamknięte tylko w „Wszystkie”; do 24.09 widzieli 4 286 wierszy razem
  z zamkniętymi). Adres: `mine=1` = Moje, `mycat=1` = Moja kategoria
  (niezamknięte rekrutacje z kategorii osoby — do wzięcia, niekoniecznie jej;
  opcja jest na przełączniku tylko, gdy `quick-counts.my_category` nie jest
  `null`, a lista wysyła wtedy samo `my_category=true`), `open=1` = Otwarte,
  `mine=0` =
  Wszystkie (stare linki z pulpitu działają). Do adresu trafia tylko zakres
  INNY niż domyślny roli (czyste `/jobs` znaczy co innego u rekrutera
  i u admina — link „dla kolegi” wysyłaj z jawnym zakresem). Stan to
  NADPISANIA (`null` = bez wyboru), bo rolę znamy dopiero po hydratacji;
  zapytanie listy ma `enabled: hydrated`. Szybkie filtry „Niezamknięte”
  i „Moje rekrutacje” usunięte — dublowały przełącznik. Zakres NIE liczy się
  do liczby ustawionych filtrów. Liczniki z `/api/jobs/quick-counts` (`all`,
  `open`, `mine`). „Moje” = moje NIEZAMKNIĘTE (decyzja Artura 26.09.2026):
  lista wysyła `mine` + `open_only`, a `mine`, `*_mine` i `attention_mine`
  w `quick-counts` liczą `jobs_mine_scope_clause` — archiwum tylko we „Wszystkie”.
- **Sortowanie domyślne zależy od zakresu** (`defaultSortForScope`):
  „Moje” → `sort=attention` („Wymaga uwagi”), „Otwarte”/„Wszystkie” →
  `newest`. `sort=deadline` = „Najbliższy termin” (bez terminu na końcu).
- **Filtry = pasek nad tabelą, nie kolumna (25.09.2026, wariant A z makiet
  https://claude.ai/artifact/4nGFAJ6N3NpjVWvLH9yjBH).** Z kolumny zniknęły
  filtry bez danych albo dublujące: Typ, „Potrzebny search” (flaga nigdzie nie
  ustawiona), „Aktywni w searchu” (liczył zamknięte), „Deadline ≤ 7 dni”
  (= Termin), Status (= zakres), Priority Work (0 planów w historii), „Osoba
  odpowiedzialna” (TAC nieużywany). Stare klucze adresu (`type`, `status`,
  `responsible`, `sourcing`, `active_search`, `no_owner`, `priority`) NIE są
  filtrem — zostają w `MANAGED_KEYS`, więc pierwszy zapis zdejmuje je z adresu;
  `rs`/`ws` mapują się na pigułki stanu (`initialStagesFromUrl`). Parametry
  API zostają (kompatybilność).
  - **Jeden rząd „Stan requestu”**: Do uzupełnienia · Do przejrzenia · Szukamy
    · Mamy championa · Umowa · Klient milczy (`lib/request-stage.ts`). Serwer
    liczy JEDNĄ wartość na rekrutację — `job_similarity.request_stage_expr`
    (closed → filled → contract → champion → szkic → work_state finished →
    client_silent → searching → to_review) — parametr `request_stage`
    (powtarzalny, LUB), pole wiersza `request_stage`, liczby `request_stage`
    / `request_stage_mine`. Nie składaj tego z `request_status` + `work_state`
    — te łączą się przez AND.
  - **Pasek** (`components/v2/jobs/JobsFilterBar.tsx`, przycisk z okienkiem
    `components/v2/filters/FilterBarPill.tsx` wspólny z listą kandydatów),
    od 02.10.2026 w kolejności jak w Traffit: Delivery Lead (`lead`), Klient,
    **Rekruter** (`who` → `worked_by`, „Ja” = własne id, „Bez rekrutera” =
    `nobody=1` → `nobody_working`), Kategoria, **Priorytet** (`prio` →
    `priority_level`), Termin (preset + zakres `dl_from`–`dl_to`), **Data
    otwarcia** (`op_from`/`op_to` → `opened_from`/`opened_to`), „Więcej
    filtrów” z „Wysłanych do klienta” (`sent` → `min_sent`/`max_sent`, OSOBY
    z `analytics_first_milestones`). Przełączniki „Po terminie” (= Termin
    `overdue`), „Bez rekrutera”, „Nikogo nie wysłano” (= `sent=none`)
    z liczbami `attention` („Otwarte”) / `attention_mine` („Moje”);
    „Wszystkie” i „Moja kategoria” bez liczb. Datę „Po terminie” liczy
    przeglądarka i wysyła jako `overdue_to`. Układ paska zależy od JEGO
    szerokości, nie okna (`jobsFilterBarLayout`: poniżej 1220 px krótkie
    etykiety i „Data otwarcia” w „Więcej filtrów”, do 1600 px pełne etykiety)
    — na laptopie pasek ma zostać jednym rzędem.
  - **„Rekruter” (do 02.10.2026 „Kto pracuje”) = reguła z `services/job_team.py`**
    — ta sama co pulpit „Requesty i obłożenie” i panel „Zespół” (sekcja „Role
    przy rekrutacji…”): prowadzący (`jobs.recruiter_id`, aktywne konto,
    niezdjęty ręcznie w bieżącym stanie requestu), AKTYWNE przypisanie
    (`job_work_assignments.state = 'active'`) albo współpracownik dopisany
    RĘCZNIE (`job_collaborators.source='manual'`). Propozycja automatu
    i `auto_cc` (cała kategoria) się nie liczą. `jobs_worked_by_clause` /
    `jobs_nobody_working_clause`; `worked_by` razem z `nobody_working=true` to
    LUB („ja albo bez rekrutera”). Ręcznego współpracownika dopisuje każdy, kto
    redaguje rekrutację (`ensure_job_editor` w `POST/DELETE …/collaborators`)
    — w oknie edycji, na `/jobs/new` i w zakładce „Zespół”; komórka „Rekruter”
    pokazuje wszystkie osoby (`RecruiterChips`, pole wiersza `recruiters`).
- **Kolumny:** „Etapy” = te same 8 kolumn co Tablica (Nowi … Zatrudniony),
  rozstrzygane `placeStage` z `lib/board-stages.ts` na `stage_columns` wiersza
  — tą samą regułą co Tablica (QC ma kod `interview`, a mimo to trafia do QC
  CV); skróty raz w nagłówku, w wierszach same liczby. „Termin” = data + „za
  N dni / po terminie N dni” (`lib/job-deadline.ts`), w dymku data otwarcia.
  Komórki: `v2/jobs/JobListCells.tsx`. Ostatnia kolumna to „Rekruter”
  (`JobRecruiterCell`: pierwsza osoba i „+N”, „Bez rekrutera”, propozycja
  automatu w przerywanej ramce, pod spodem „DL: …”).
- **Wiersz = nazwa stanowiska + jedna linia (decyzja Artura 02.10.2026,
  makieta https://claude.ai/artifact/6o8S6SDErWyrBYqafTFCkY).** Linia 1:
  plakietka priorytetu (`RequestPriorityChip`; P2 bez plakietki) i sama rola —
  `jobRowTitle` z `lib/job-row-summary.ts` (pierwszy człon tytułu roboczego
  z automatu; tytuł wpisany ręcznie w całości). Linia 2: krótka plakietka
  kategorii (`competenceShortLabel`), klient, tryb pracy z pierwszym miastem
  (`jobWorkModeParts`; gdy ciasno, najpierw znika miasto). Wymagania, nazwa od
  klienta, numer u klienta, nasz numer, wszystkie miasta, data otwarcia
  i plakietka „Podobne rekrutacje” stoją w Podglądzie (ikona oka →
  `JobPreviewDetails` na górze zakładki „Gotowość” doku, prop `listDetails`),
  a przepinanie ma w wierszu ikonę (`SimilarJobsIconButton`). Nie dokładaj tych
  rzeczy z powrotem do wiersza ani drugiej linii pod tytułem. `title` z pełnym
  tytułem stoi na opakowaniu linku, nie na samym `<a>` (nazwa dostępna).
- **Szyna „Otwarte karty” stoi też na liście `/jobs` i u kandydatów
  (02.10.2026, `components/v2/shell/OpenTabsRail.tsx`).** Od 1536 px w układzie
  strony (na listach rozwinięta bez zapisanego wyboru od 1920 px rekrutacje /
  1600 px kandydaci). Poniżej 1536 px na LISTACH wyzwalaczem jest zakładka
  w lewym marginesie strony (`narrow="gutter"`, zero szerokości w układzie),
  a lista kart wysuwa się nad treść: pasek 40 px z odstępem zabierał tabeli
  56 px, a lista kandydatów przy 1280 px i tak przewija się w poziomie
  (pomiar 02.10.2026). Strona rekrutacji zostaje przy pasku 40 px.
- **Słownik tego ekranu:** „Moje rekrutacje", „Brak opiekuna TAC"
  (`tac_id IS NULL`; celowo NIE „Brak właściciela" — kolumna „Właściciel"
  pokazuje `primary_owner`, więc wiersz mówiłby „Marta K." i „brak
  właściciela" naraz). „Potrzebny search", „Priority Work"
  i nazwy techniczne zostają.
- **Funkcja TAC jest WYŁĄCZONA w UI** (decyzja Artura 22.09.2026: „każdy
  jest rekruterem lub sourcerem"): `lib/tac-ui.ts` → `TAC_UI_ENABLED = false`
  chowa plakietkę i szybki filtr „Brak opiekuna TAC" (świeciły na ~4 250
  z 4 265 rekrutacji), a `?no_owner=1` ze starego linku nie zawęża listy
  ukrytym filtrem. Rola `tac`, kolumna `tac_id` i pole w ustawieniach
  rekrutacji zostają — powrót = zmiana stałej (filtr; plakietka żyła tylko
  na kafelku, którego od 02.10.2026 nie ma — trzeba by ją dopisać do wiersza).
- **Klucze react-query listy buduje `jobsListQueryKey` /
  `jobsQuickCountsQueryKey`** — harness `/preview/jobs-list-v3` zasiewa cache
  tymi samymi funkcjami, a zapytania doku odcina interceptorem (zero sieci).
- **Pasek boczny = szyna w GRUPACH z nagłówkami + „Więcej" (21.09.2026).**
  `placement` w `lib/nav-registry.ts` jest PER WPIS, niezależne od roli (kto
  co widzi, rozstrzyga wyłącznie bramka widoczności). Szyna to
  `NAV_PRIMARY_GROUPS`: **„Praca"** (Dashboard, Rekrutacje, Kandydaci,
  Kalendarz) · **„Klienci i umowy"** (Klienci, Kontrakty, Finanse)
  · **„Firma"** (Insights); `NAV_PRIMARY_ORDER` jest ich
  spłaszczeniem, `visiblePrimaryGroups` zwraca grupy danej roli i odrzuca
  PUSTE (rekruter nie widzi nagłówka „Klienci i umowy"). Reszta w grupach
  `NAV_MORE_GROUPS`. Nowy wpis `more` MUSI mieć `moreGroup`, nowy `primary` —
  miejsce w dokładnie jednej grupie szyny (pilnuje `nav-registry.test.ts`).
  **Panel klientów, Moje relacje i Zamówienia z maila NIE stoją w menu
  (22.09.2026)** — to tryby ekranów (`lib/clients-workspace.ts`): „Moi
  klienci" = przełącznik „Moi / Wszyscy" na liście `/clients` (`?mine=0/1`,
  domyślnie „Moi" dla DL — `CLIENTS_MINE_ROLES`; backend `GET /api/clients/directory?mine=true`
  zawęża do przypisań DL ∪ TAC — to filtr widoku, nie granica dostępu),
  „Kluczowe relacje" = `/clients?view=contacts`, „Skrzynka zamówień" =
  `/contracts?view=order-mail` z licznikiem „Do weryfikacji" przy trybie
  i przy „Kontraktach" w menu (`useOrderMailPendingCount`, `badgeKey:
  "orderMail"`). Stare adresy (`/my-clients`, `/my-relationships`,
  `/order-mail`) przekierowują serwerowo z zachowaniem parametrów —
  powiadomienia w bazie niosą `link="/order-mail?doc=…"`, nie kasuj tych
  stron. Wpisy zostają w palecie ⌘K (`inSidebar: false`).
  **Wyszukiwarka i Talent Radar NIE stoją w menu** — to tryby ekranu
  „Kandydaci" (`/candidates?mode=search`, `?mode=request`); oba wpisy mają
  `inSidebar: false` i żyją w palecie ⌘K („Wyszukiwarka kandydatów",
  „Szukaj z treści requestu (Talent Radar)", słowa kluczowe „radar",
  „wyszukiwarka"). Radar jest dla KAŻDEJ roli (19.08), a /candidates tylko dla
  `nav.candidates`, więc `resolveHref` radaru daje `/talent-radar` (strona
  samodzielna) roli bez `nav.candidates` (np. viewer `user`). Nagłówek grupy
  (`SidebarNavGroup`/`SidebarGroupHeading` w `SidebarMore.tsx`) siedzi
  w stałym slocie `SIDEBAR_VERTICAL_LAYOUT.sectionSlot` w OBU stanach:
  rozwinięta szyna — tekst, zwinięta — kreska `aria-hidden` tej samej
  wysokości, a tekst zostaje jako `sr-only`, bo `role="group"` jest nazwane
  przez `aria-labelledby`. Stałe B57 żyją w `SidebarMore.tsx` (czyta je też
  szuflada), `SidebarV2` je re-eksportuje. „Kto co widzi" testuj przez
  `visibleNavHrefs` (szyna + „Więcej"); `visibleNavSections` zostaje widokiem
  sekcjami całego menu. Paleta ⌘K nadal listuje wszystko.
- **„Więcej"** (`v2/shell/SidebarMore.tsx`): Radix Popover w trybie modalnym
  (pułapka fokusu, Esc, fokus wraca na przycisk, strzałki chodzą po linkach),
  licznik = SUMA liczników w środku, bieżąca strona spod „Więcej" zapala
  przycisk. Przycisk używa `navItemClassName` (ta sama wysokość co linki) i
  stoi za stałym slotem z kreską — inwariant `SIDEBAR_VERTICAL_LAYOUT` (B57)
  zmierzony: pozycje Y identyczne przy 60 i 240 px. Przy otwartym panelu
  `mouseleave` szyny jest ignorowany, a zamknięcie zdejmuje hover. Szuflada
  mobilna renderuje grupy w linii (`SidebarMoreInline`), bez nakładki.
