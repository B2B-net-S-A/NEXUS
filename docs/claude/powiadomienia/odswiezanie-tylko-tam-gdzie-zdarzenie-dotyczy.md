# Odświeżanie po zdarzeniach gniazda tylko tam, gdzie zdarzenie dotyczy (27.10.2026)
<!-- indeks: bez refetchOnWindowFocus globalnie, ramka odświeża listę swojego tematu, pipeline_changed → „CV”/dl-send tylko DL-owi rekrutacji, admin bez cudzych ruchów kart, jeden klucz ["job", "<id>"] -->

27.10.2026 NEXUS lagował: jeden proces uvicorna, p50 wszystkich żądań 571 ms,
pętla zdarzeń spóźniona o ponad sekundę w 64 z 81 minut. Ruch z przeglądarek
w godzinę na prod: `/api/board-tasks/cv` 1 941, każda z czterech list
okienek paska ok. 920, `/api/jobs/{id}` 876. Większość z tego to odświeżenia,
których nikt nie oglądał.

- **Bez odświeżania przy powrocie do karty** (`QueryProvider`,
  `refetchOnWindowFocus: false`). Każdy powrót do karty dawał 20–25 GET-ów
  z paska i menu naraz; ikony paska odświeża gniazdo na zdarzeniach i raz po
  jego powrocie, a bez gniazda — odpytywanie i jedno odświeżenie list przy
  powrocie do karty (`useNotifications`, `visibilitychange`). Ekran, który
  naprawdę potrzebuje świeżości po powrocie, ustawia `refetchOnWindowFocus:
  true` przy swoim zapytaniu (licznik czatu rekrutacji, Finanse, kalendarz
  pulpitu). Nie przywracaj tego globalnie.
- **Ramka `notification` odświeża listę SWOJEGO tematu**
  (`invalidateNotificationLists` w `lib/notification-topics.ts`): listy
  okienek mają klucz `["notifications", scope, "chats" | "interviews" |
  "jobs" | "contracts"]`, a ramka tematu `jobs` odświeża tylko `jobs` i listy
  spoza okienek (pulpit). Temat bez okienka (`cv`, `my_people`, `other`)
  nie odświeża żadnego okienka. Ramka bez tematu, powrót gniazda
  i odpytywanie bez gniazda odświeżają wszystko. Wiadomość czatu = temat
  `messages`. Nowe okienko z listą = wpis w `TOPIC_LIST_LEAF`.
- **`pipeline_changed` nie unieważnia całego `["board-tasks"]`.** Pulpit
  „Czeka na Ciebie” (`exact`) i okno Cpro zostają (pobierają się tylko na
  ekranie), a ikona „CV” i `dl-send` z paska — według
  `lib/pipeline-changed-refresh.ts`: Delivery Lead TEJ rekrutacji
  (`delivery_lead_id` w ramce; ramka bez pola = każdy DL) albo ktoś, kto ma
  już w tych kolejkach wiersz tej rekrutacji. Nowy wiersz u rekrutera
  przychodzi ramką tematu `cv`, a własny ruch odświeża ikonę w
  `usePipelineMove`.
- **Admin nie dostaje ruchów kart całej firmy** (backend,
  `pipeline_realtime.broadcast_pipeline_changed`): odbiorcy to zespół
  rekrutacji bez adminów spoza niego (`list_job_member_ids(...,
  include_admins=False)`) plus każdy, kto ma tę Tablicę otwartą (kanał
  obecności `job:{id}`, `ConnectionManager.viewer_ids`). Czat, wzmianki,
  prepy i dostęp liczą adminów dalej (domyślne `include_admins=True`).
- **Rekrutacja ma jeden klucz: `["job", "<id z adresu>"]`** (napis, jak
  w `useParams`). Okruszek (`BreadcrumbV2`), `PairOwnerLine`, dok gotowości,
  `useCachedJob` i Tablica (`useJobPipelineTemplate` przez `fetchQuery`)
  czytają odpowiedź strony zamiast własnego `GET /api/jobs/{id}`. Na
  stagingu wejście na rekrutację: 3 → 1 takie żądanie.
- **Profil Championa w pasku źródeł** (`useJobSearchSeed`) ma `staleTime`
  5 min — pobierał się przy każdym wejściu na rekrutację.
- **pdf.js ładuje się przy otwarciu okna podglądu** (`preloadPdfJs()`
  w `FilePreviewModal`, `CVOriginalPreviewModal`, `CvPagesPreview`),
  równolegle z pobieraniem pliku, nie po nim.

Pomiar na stagingu (DL rekrutacji, 1280 × 720, backend i front z gałęzi):
ruch karty kolegi w jego rekrutacji = Tablica, wyniki, „CV”, `dl-send`;
w cudzej rekrutacji oglądanej na ekranie = tylko Tablica i wyniki;
w cudzej rekrutacji poza ekranem = zero żądań; powrót do karty = zero żądań;
wzmianka w czacie = tylko `/api/notifications/chats`, a liczba na ikonie
„Wiadomości” rośnie od razu.
