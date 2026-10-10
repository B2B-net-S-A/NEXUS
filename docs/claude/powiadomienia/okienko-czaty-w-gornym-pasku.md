# Okienko „Czaty” w górnym pasku (09.10.2026)

Powiadomienia czatów (rekrutacji i kandydata) stały w dzwonku razem ze
wszystkim innym, po jednym wierszu na wiadomość i bez nazwy rozmowy; otwarcie
czatu ich nie gasiło. Decyzje Artura 09.10.2026: czaty mają własne okienko,
jedna pozycja na rozmowę, wejście do czatu gasi jego powiadomienia, nowa
wiadomość daje dymek. Raport: `docs/chat-notifications-window-completion-report.md`.

- **Dzwonek nie pokazuje ani nie liczy czatów:** `GET /api/notifications`
  i `read-all` z `exclude_chat=true` (`notificationsApi.listForBell`,
  `markAllReadForBell`). Bez parametru trasy działają jak dotąd — „Moje
  zadania” na pulpicie i narzędzia Jarvisa nadal widzą czaty. Wzmianki
  z notatek i odpowiedzi na notatki zostają w dzwonku (to nie czat).
  Zapytanie dzwonka ma własny klucz (`[…, limit, "bell"]`): „Moje zadania”
  pytają o tę samą stronę razem z czatami i pod wspólnym kluczem podmieniały
  dzwonkowi listę i licznik (produkcja 10.10.2026).
- **Rozmowę rozpoznaje link, nie typ.** Oba czaty używają typów
  `job_chat_message` / `job_chat_mention`; `services/chat_notifications.py`
  grupuje po `split_part(link, '&msg=', 1)` (ten sam klucz co
  `chat_email_fallback`). Stałe w tym wyrażeniu są literałami SQL — jako
  parametry `SELECT` i `GROUP BY` dostałyby różne numery i Postgres odrzuciłby
  zapytanie. Nie zmieniaj formatu linku czatu (`_message_link`) bez tego modułu.
- **`GET /api/notifications/chats`**: rozmowy z ostatnich 30 dni
  (`CHAT_WINDOW_DAYS`), nieprzeczytane najpierw; liczy WIADOMOŚCI
  (`count(distinct link)` — oznaczona osoba z zespołu ma dwa wiersze o jednej
  wiadomości); `link` = pierwsza nieprzeczytana, a bez nieprzeczytanych —
  ostatnia. Widoczność jak w dzwonku (`notification_visibility_predicate`:
  sekcja, wyciszona kategoria „Czat”, wyłączenie dla roli). Licznik na ikonie
  = liczba rozmów z nowymi wiadomościami.
- **Powiadomienia rozmowy gasną w trzech miejscach**, zawsze przez
  `chat_notifications.mark_read`: `PUT …/chat/read` obu czatów (wejście do
  czatu; odpowiedź niesie `notifications_cleared`, front odświeża okienko
  tylko, gdy coś zgasło), klik w pozycję okienka (`PUT
  /api/notifications/chats/read` z rozmową — czat tylko do odczytu nie woła
  `chat/read`) i „Oznacz wszystkie” (ta sama trasa bez ciała).
- **Dymek = zdarzenie `chat:notify` / `candidate-chat:notify`** wysyłane po
  zapisie wiadomości do każdego odbiorcy powiadomienia — także do oznaczonej
  osoby spoza zespołu, do której rozgłoszenie `…:message:new` nie dociera.
  `user_can_receive_realtime_event` przepuszcza je bramką WIERSZA
  (`user_can_receive_notification`), nie samym prefiksem `chat:` — wyciszona
  kategoria nie daje dymka. Front: `useNotifications` przekazuje je jako
  zdarzenie okna `CHAT_NOTIFY_EVENT`, `ChatNotificationsDropdown` pokazuje
  `showActionToast` z „Otwórz”. Bez dymka, gdy ten czat jest na ekranie
  (`lib/active-chat.ts`), a zwykła wiadomość z tej samej rozmowy najwyżej raz
  na 20 s (`lib/chat-notify.ts`; wzmianka zawsze).
- **Link do wiadomości doczytuje starsze strony** (`useChatMessageFocus`:
  `hasMore`, `isLoadingMore`, `loadMore`; najwyżej 10 stron po 50) — pierwsza
  nieprzeczytana w ruchliwym czacie bywa dalej niż ostatnia strona.
- Klucz zapytania okienka stoi pod prefiksem `["notifications"]`
  (`chatThreadsQueryKey`), więc odświeżają go istniejące unieważnienia po
  zdarzeniach czatu. `useNotifications` nadal montuje wyłącznie dzwonek (jedno
  gniazdo) — okienko słucha zdarzeń okna, nie gniazda.
- Harness `/preview/chat-notifications` (części prezentacyjne
  `ChatTopbarButton`, `ChatThreadsPanel`; zero zapytań).
