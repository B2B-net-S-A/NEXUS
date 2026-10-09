# Okienko „Czaty” w górnym pasku — raport (09.10.2026)

## Skąd zmiana

Powiadomienia z czatów (czat rekrutacji i czat kandydata) stały w dzwonku razem
ze wszystkim innym: jeden wiersz na wiadomość („Anna: nowa wiadomość”), bez
nazwy rekrutacji ani kandydata. Admin jest członkiem każdego czatu, więc jego
dzwonek stał na 99+. Otwarcie czatu nie gasiło powiadomień — trzeba je było
odklikiwać osobno.

## Decyzje Artura (09.10.2026)

1. Czaty znikają z dzwonka i z jego licznika — mają własne okienko.
2. W okienku jedna pozycja na rozmowę (rekrutacja albo kandydat).
3. Klik otwiera czat na pierwszej nieprzeczytanej wiadomości, wejście do czatu
   samo gasi jego powiadomienia, nowa wiadomość daje dymek z „Otwórz”.

## Co się zmieniło

- **Ikona „Czaty”** między „Moi ludzie” a dzwonkiem. Licznik = liczba rozmów
  z nowymi wiadomościami; czerwony, gdy w którejś jest wzmianka.
- **Okienko**: nazwa rekrutacji albo kandydata, klient, autor i fragment
  ostatniej wiadomości, liczba nowych, znaczek wzmianki. Rozmowy z ostatnich
  30 dni, nieprzeczytane najpierw. „Oznacz wszystkie jako przeczytane”
  i skrót do „Moich powiadomień”.
- **Klik** prowadzi do pierwszej nieprzeczytanej wiadomości i ją podświetla —
  także gdy jest starsza niż ostatnie 50 (czat doczytuje do 10 starszych stron).
- **Wejście do czatu** (z okienka albo zwykłą drogą) gasi jego powiadomienia.
- **Dymek** przy nowej wiadomości z nazwą rozmowy i „Otwórz”. Nie pojawia się,
  gdy ten czat jest na ekranie; zwykła wiadomość z tej samej rozmowy najwyżej
  raz na 20 s, wzmianka zawsze. Dostaje go także oznaczona osoba spoza zespołu.
- **Dzwonek** nie pokazuje i nie liczy czatów; „Oznacz wszystko” w dzwonku ich
  nie gasi.

Bez migracji i bez nowych typów powiadomień.

## Kod

| Część | Pliki |
|---|---|
| Grupowanie w rozmowy, gaszenie, zdarzenie na żywo | `backend/app/services/chat_notifications.py` |
| Trasy `GET /api/notifications/chats`, `PUT /api/notifications/chats/read`, `exclude_chat` | `backend/app/api/notifications.py` |
| Gaszenie przy `PUT …/chat/read`, wysyłka `chat:notify` | `backend/app/api/job_chat.py`, `candidate_chat.py` |
| Bramka zdarzenia (sekcja i wyciszenie) | `backend/app/services/notification_access.py` |
| Okienko, ikona, dymek | `frontend/src/components/v2/shell/ChatNotificationsDropdown.tsx`, `lib/chat-notify.ts`, `lib/active-chat.ts`, `lib/api/chatNotifications.ts` |
| Doczytywanie starszych stron przy linku do wiadomości | `frontend/src/hooks/useChatMessageFocus.ts` |
| Harness | `/preview/chat-notifications` |

## Weryfikacja

| Co | Stan | Dowód |
|---|---|---|
| Testy frontendu (okienko, dymek, gniazdo, przewijanie, dzwonek, harnessy) | przechodzą | `npx vitest run` na zmienionych plikach, 09.10.2026 |
| Typy i lint frontendu | przechodzą | `npm run type-check`, `npx eslint` |
| Lint i format backendu | przechodzą | `ruff check`, `ruff format` na zmienionych plikach |
| Testy backendu (`test_chat_notification_threads.py`, kontrakty tras) | niepotwierdzone lokalnie | lokalny Python to 3.9, bez Postgresa — sprawdza CI |
| Wygląd okienka przy 1280 px i 375 px | sprawdzone na harnessie | zrzut ekranu i pomiar szerokości w Chrome |
| Pasek, licznik dzwonka, klik, gaszenie i dymek na produkcji | do sprawdzenia po wdrożeniu | — |

## Poza zakresem

- „Moje zadania” na pulpicie nadal pokazują powiadomienia czatów.
- Wzmianki z notatek i odpowiedzi na notatki zostają w dzwonku.
- Mail zastępczy czatu bez zmian (gaszenie przy wejściu do czatu samo
  ograniczy te maile).
