# Pasek bez dzwonka: ikony z jednym tematem (16.10.2026)

Pomiar na produkcji 16.10.2026: dzwonek miał „99+” u 21 z 41 kont (mediana
nieprzeczytanych: admin 863, DL 209), dostawał ~18 wpisów na osobę dziennie,
a 99,5% oznaczeń „przeczytane” w 30 dni to gaszenie hurtem. Decyzja Artura:
dzwonka nie ma; ludzie rozumieją ikony z JEDNYM tematem. Pasek: „Moi ludzie”
· „CV” (zamiast pigułki „Do wysłania”) · „Rekrutacje” (w miejscu dzwonka) ·
„Wiadomości” (dawne „Czaty” + notatki) · „Kalendarz” (dawne „Rozmowy”).
Makiety: https://claude.ai/artifact/Sg4nsek8fGLcqNxMH47pFc.

> **26.10.2026: szósta ikona „Umowy”** (temat `contracts`, decyzja Artura).
> Zdarzenia umów w podpisie (`signature_sent`, `signature_signed`,
> `signature_rejected`, `signature_failed`) i prośba o potwierdzenie podpisu
> (`b2b_signature_requested`) miały temat `other`: reprezentant firmy nie
> zauważył umowy czekającej na jego podpis. Ikona u wszystkich, między
> „Rekrutacjami” a „Wiadomościami”; okienko `GET /api/notifications/contracts`
> (14 dni, jedna pozycja na encję zdarzenia, bez encji — po linku), liczba na
> ikonie `unread_contracts` = umowy z nowymi (każde zdarzenie ją podbija);
> klik gasi `topics/read {topic: "contracts", ids: unread_ids}`. Dymek
> zostaje dla wszystkich typów tematu. Front: `ContractsNotificationsDropdown`,
> `lib/api/contractTopic.ts`. Przy 1280 px pasek się mieści (wyszukiwarka
> 220 px), okruszek skraca się o kilka liter.

- **Temat liczy się z TYPU** (`services/notification_topics.py`,
  `TOPIC_BY_TYPE`): `messages`, `interviews` (= kategoria „Rozmowy”), `cv`,
  `my_people`, `jobs`, `other`. Mapa jest wyczerpująca —
  `test_notification_topics.py` wywraca CI przy nowym typie bez tematu.
  Nowy typ = świadomy wybór ikony; `other` znaczy „bez ikony”: tylko dymek
  i mail tam, gdzie mail już jest (decyzja D6), bez listy na pulpicie.
- **Wzmianki i odpowiedzi w notatkach** należą do `messages` przez osobną
  krotkę `NOTE_NOTIFICATION_TYPES` — NIE dopisuj ich do
  `CHAT_NOTIFICATION_TYPES` (ta steruje `exclude_chat` i kasowaniem wierszy
  w `retract_chat_message_notifications`).
- **Ramka gniazda dostaje `topic` i `toast` w jednym miejscu:**
  `api/ws.py` `ConnectionManager.notify_user` → `enrich_realtime_event`
  (kopia, nie mutacja). Nie dokładaj tematu u producentów. Dymek
  (`TOAST_TYPES`): cały temat `cv`; w `jobs` tylko sprawy imienne
  (przydział, „Poprzedni rekruter”, zadanie stawki, przejęcie osoby, decyzje
  o requestach) i akceptacja klienta (`client_accepted`, 0451); `note_*`; `other` poza coachem KPI i Power Calling (mają
  własny toaster). Ruchy etapów, automat i terminy zmieniają tylko licznik.
  Typ nieznany tej wersji backendu = `other` z dymkiem.
- **`GET /api/notifications/jobs`** — okienko „Rekrutacje”: wiersze tematu
  `jobs` z 7 dni, jedna pozycja na rekrutację; klucz rekrutacji =
  `job_key_expression` (ścieżka `/jobs/{id}`, parametr `?job=` z linku
  auto-matcha, encja `job`). Wiersz bez rekrutacji („Twoje requesty na
  dziś”, propozycje przydziału) to pozycja po swoim linku. Właściciel jak
  w każdym okienku: `_notification_owner` (przypomnienia w zastępstwie)
  i `_notification_visibility`. Liczba na ikonie = `unread_jobs` (pozycje
  z nowymi, nie wiersze; na prod 14–16.10 mediana 4 na osobę dziennie).
  Regexy klucza są literałami SQL — jako parametry wiązane w SELECT
  i GROUP BY dostałyby różne numery (pułapka z okienka czatów).
- **Ruch etapu prowadzi na Tablicę:** domyślny link reguły etapu
  (`stage_notification_emitter._inapp_base`) to `/jobs/{id}?candidate={id}`,
  nie profil kandydata — inaczej wiersz nie trafiłby do swojej rekrutacji.
- **Gaszenie tematu ma własną trasę:** `PUT /api/notifications/topics/read`
  `{topic, job_id? | link? | ids?, include_covered}` — jedno wskazanie naraz;
  klik w pozycję gasi też przypomnienia nieobecnego kolegi (jak klik
  w dzwonku), samo wejście na ekran rekrutacji wysyła `include_covered:
  false` (tylko własne); bez wskazania — wszystkie WŁASNE wiersze tematu.
  Nie rób z tego parametru `read-all` (stary backend zignorowałby nieznany
  parametr i zgasił wszystko — lekcja z okienka „Rozmowy”).
- **„Wiadomości”:** `GET /api/notifications/chats?include_notes=true` dokłada
  wątki `kind: "note"` (jeden na link notatki — odpowiedź niesie link
  notatki nadrzędnej, więc ląduje w tym samym wątku); gaszenie wątku
  `PUT …/chats/read {kind: "note", link}`, „Oznacz wszystkie”
  z `include_notes=true`. Bez parametru trasy działają jak przed zmianą.
- `GET /api/notifications?topic=` (powtarzalny, filtr pozytywny) i `by_topic`
  w `GET /api/notifications/count` — dla pulpitu i porannego briefu Jarvisa.
- **Poranny wpis `board_tasks_digest` nie powstaje** (odpięty
  z `run_all_triggers`); ta sama kolejka jest na pulpicie i w porannym
  mailu. Typ zostaje w enumie i mapach (testy wyczerpujące).
- **Kopie „Moich ludzi” nie powstają (PR5):** `my_people_matching.run_for_job`
  wysyła po commicie samo zdarzenie `my_people:match` (bez wiersza), z bramką
  typu `my_people_match` w `user_can_receive_realtime_event` — szczegóły
  w `kandydaci-wyszukiwanie/moi-ludzie-lista-rekrutera-dzwonek-przy-nowej.md`.
- **Jednorazowe sprzątanie (D5, PR5):** faza startu
  `repair-notification-topics-backlog` → `run_topics_backlog_repair`:
  nieprzeczytane powiadomienia KAŻDEGO typu starsze niż 7 dni → przeczytane,
  marker `notification_topics_backlog_read_2026_10` w `app_settings`, paragon
  z samymi liczbami per typ. Nic nie jest kasowane; maili nie dotyka.

## Front (PR4, 16.10.2026)

- **Jedno gniazdo poza ikonami:** `NotificationsRealtime` (montowane raz
  w `AppShellV2`) woła `useNotifications`; stan połączenia i otwarte okienko
  trzyma `store/realtime` (`connected`, `openTopic`). Nowa ikona NIE otwiera
  własnego gniazda — słucha zdarzeń okna albo unieważnień kluczy.
- **Dymki** wychodzą z `NotificationsRealtime` według `toast` z ramki
  (`shouldToastFrame`); bez dymka, gdy okienko tego tematu jest otwarte
  (`openTopic`). Ramka bez tematu (backend sprzed zmiany) — dymek jak dawniej.
  Ramka tematu `cv` unieważnia `["board-tasks","cv"]`.
- **„CV”** — `CvNotificationsDropdown` (`useCvTopic`, `GET /api/board-tasks/cv`,
  tylko role rekruter i DL). U Delivery Leada z kolejką ikona ma formę pigułki
  z kolorem pilności (dawne `DlSendTopbarButton`; inwentarz `dl-send.topbar`
  wskazuje nowy plik). Wiersze rekrutera biorą teksty z `lib/cv-in-transit.ts`.
- **„Rekrutacje”** — `JobsNotificationsDropdown` (`useJobThreads`, klucz
  `["notifications", scope, "jobs"]`); klik = `topics/read` z `job_id` albo
  `link`; wejście na `/jobs/{id}` woła `useClearJobTopic` (`include_covered:
  false`, tylko gdy okienko pokazuje nowości tej rekrutacji i karta jest
  widoczna — nowość, która przyszła do karty w tle, czeka na powrót).
  Odpowiedź tras `jobs` i `board-tasks/cv` w złym kształcie to błąd zapytania
  (stan błędu, ikona schowana), nigdy wyjątek w renderze — hook stoi w ciele
  strony rekrutacji, bez granicy błędu.
- Panel „CV” u DL ma plakietkę „do Cpro” przy nazwisku (Nordea) i dopisek
  „Pokazano N z M”, gdy serwer przyciął listę (30) — jak dawne okienko.
- **„Wiadomości”** — `ChatNotificationsDropdown` z `include_notes`; ramka
  notatki idzie do okienka zdarzeniem `CHAT_NOTIFY_EVENT` (`kind: "note"`).
- Dzwonek (`NotificationsDropdown`), `listForBell`, `markAllReadForBell`
  i `lib/notifications-paging.ts` usunięte; wyciszenie kategorii „w miejscu”
  zostaje tylko w Ustawieniach. Poranny brief Jarvisa liczy „rekrutacje
  z nowościami” (`unread_jobs`), nie sumę nieprzeczytanych.
- Harness `/preview/topbar-topics`; replika paska w `/preview/kpi-topbar`
  (pigułka „CV”, teczka „Rekrutacje”) mierzona w `e2e/responsive-preview.spec.ts`.
