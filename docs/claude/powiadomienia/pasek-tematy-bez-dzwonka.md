# Pasek bez dzwonka: ikony z jednym tematem (16.10.2026)

Pomiar na produkcji 16.10.2026: dzwonek miał „99+” u 21 z 41 kont (mediana
nieprzeczytanych: admin 863, DL 209), dostawał ~18 wpisów na osobę dziennie,
a 99,5% oznaczeń „przeczytane” w 30 dni to gaszenie hurtem. Decyzja Artura:
dzwonka nie ma; ludzie rozumieją ikony z JEDNYM tematem. Pasek: „Moi ludzie”
· „CV” (zamiast pigułki „Do wysłania”) · „Rekrutacje” (w miejscu dzwonka) ·
„Wiadomości” (dawne „Czaty” + notatki) · „Kalendarz” (dawne „Rozmowy”).
Makiety: https://claude.ai/artifact/Sg4nsek8fGLcqNxMH47pFc.

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
  o requestach); `note_*`; `other` poza coachem KPI i Power Calling (mają
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
