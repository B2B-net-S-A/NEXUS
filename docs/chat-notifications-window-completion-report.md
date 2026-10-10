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
| Testy backendu (`test_chat_notification_threads.py`, kontrakty tras) | przechodzą w CI | sito na PR-ze i bieg kolejki merge'ów B2B-net-S-A/NEXUS#2111 (scalony 09.10.2026); lokalnie nieuruchamiane (Python 3.9, bez Postgresa) |
| Wygląd okienka przy 1280 px i 375 px | sprawdzone na harnessie | zrzut ekranu i pomiar szerokości w Chrome |
| Wdrożenie | na produkcji | `/api/health` i `version.json` → `080c01e`, potomek commita `fd988abc8` (10.10.2026) |
| Ikona w pasku przy 1280 px (produkcja) | mieści się | pomiar w Chrome: powłoka zwężona do 1280 × 720, pasek bez przelewu, ikona 1091–1127 px, okienko 743–1127 px; okna automatyzacji nie dało się zmniejszyć, więc to zwężenie powłoki, nie okna |
| Klik w rozmowę (produkcja) | działa | otwiera czat rekrutacji, licznik rozmów 1 → 0, `unread_count` 337 → 336 |
| Dzwonek bez czatów (produkcja) | błąd znaleziony 10.10.2026, poprawka w osobnym PR | API z `exclude_chat=true` zwraca 336, ale na pulpicie dzwonek pokazywał 337 i wiersz czatu — „Moje zadania” pytały pod tym samym kluczem zapytania razem z czatami; dzwonek ma teraz własny klucz (`"bell"`) i test |
| Dymek (produkcja) | częściowo | pokazuje się po zdarzeniu wywołanym lokalnie w karcie (bez wysyłania wiadomości do zespołu); wyciszenia przy otwartym czacie nie dało się sprawdzić, bo karta automatyzacji ma `visibilityState = hidden` — pilnuje go test komponentu |
| Dymek po prawdziwej wiadomości od innej osoby | niepotwierdzone | wymaga wysłania wiadomości do zespołu na produkcji |

## Poza zakresem

- „Moje zadania” na pulpicie nadal pokazują powiadomienia czatów.
- Wzmianki z notatek i odpowiedzi na notatki zostają w dzwonku.
- Mail zastępczy czatu bez zmian (gaszenie przy wejściu do czatu samo
  ograniczy te maile).
- Fragment wiadomości w okienku (i w dzwonku) pokazuje wzmiankę jako
  `@adres`, nie jako imię i nazwisko — tak jak zapisuje ją czat. Zamiana na
  nazwisko wymaga zmiany po stronie serwera.
