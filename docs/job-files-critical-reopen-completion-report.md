# Krytyczne bez blokady fraz, wpisywanie wymagań, pliki rekrutacji, ponowne otwarcie bez wyboru rekrutera

Data: 09.10.2026. Cztery zgłoszenia Artura do zakładania i prowadzenia rekrutacji, jeden PR, trzy commity.

## Co się zmieniło

### 1. Krytyczną może być każda fraza — decyduje Delivery Lead

- Limit trzech krytycznych zostaje. System nie odrzuca już branży, języka, umiejętności miękkiej, kategorii, roli ani zdania.
- Fraza spoza technologii ukrywa w propozycjach AI tak jak technologia: zostają osoby, które mają którekolwiek ze słów jej wiersza w profilu, CV albo notatkach (decyzja Artura z tej sesji).
- Te same słowa czytają QC CV i wiersze obowiązkowe w „Szukaj ręcznie”. Pula SQL nie jest zawężana po takiej frazie, żeby nie zgubić osób, które bramka by przepuściła.
- Wersja reguły bramki: `critical-v11`. Nocny przegląd bazy przeliczy rekrutacje w najbliższym oknie 01–05.
- Podpowiedź z historii (gdy Delivery Lead nie zdecydował) działa jak dotąd — tylko technologie ze słownika.

### 2. Wpisywanie must-have i krytycznych na `/jobs/new`

Zgłoszenie: „wpisuję jedno must-have i nie mogę kolejnego”, „słowo znika albo się podmienia”. Cztery przyczyny, wszystkie w edytorze wierszy:

| Objaw | Przyczyna | Poprawka |
|---|---|---|
| Drugie wymaganie stawało się wariantem „lub” pierwszego | Po Enterze kursor zostawał w tym samym wierszu | Enter przechodzi do następnego wiersza (tworzy go, gdy trzeba); przecinek dodaje wariant |
| Kliknięcie w wiersz niżej podmieniało słowo | Lista podpowiedzi otwierała się na pustym polu i zasłaniała wiersz niżej | W wierszach wymagań lista nie otwiera się na pustym polu |
| Enter wstawiał inne słowo niż wpisane | Kursor myszy nad listą ustawiał podświetlenie klawiatury | Najechanie myszą nie zmienia podświetlenia; Enter wstawia podpowiedź tylko wybraną strzałkami |
| „Krytyczne” było nieaktywne | Przycisk czekał na odpowiedź serwera i odrzucał frazy | Wyłącza go wyłącznie limit trzech |

Cztery nowe testy edytora padały na starym kodzie i przechodzą na nowym.

### 3. Pliki rekrutacji (migracja 0427)

- `/jobs/new`: karta „Pliki” pod requestem klienta. Plik requestu z kroku 1 zapisuje się sam, Delivery Lead dokłada kolejne.
- Strona rekrutacji: menu „⋯” → „Pliki (N)”. Widzi każda rola wewnętrzna, dodaje i usuwa osoba, która redaguje rekrutację.
- Do „Utwórz i przekaż” pliki wiszą na niedokończonym formularzu; utworzenie rekrutacji przepina je w tej samej transakcji. Odmowa utworzenia zostawia pliki przy formularzu.
- Limity: 20 MB na plik, 20 plików na rekrutację; PDF, Word, Excel, PowerPoint, TXT, CSV, PNG, JPG, EML, MSG.
- Podgląd w oknie dla PDF, DOCX i obrazów; reszta do pobrania.

### 4. Ponowne otwarcie bez wyboru rekrutera

- „Otwórz ponownie” nie pyta o rekrutera ani kanał pracy. Dotychczasowy prowadzący zostaje i dostaje dzwonek.
- Rekrutacja bez aktywnego prowadzącego trafia do automatu przydziału albo do kolejki Head of Recruitment.
- „Dokończ i opublikuj” (stare szkice, opublikowane bez przekazania) nadal pyta o rekrutera.

## Założenia przyjęte bez pytania

- Słowa wiersza liczą się w bramce także dla wierszy-technologii (wiersz „Kafka, kolejki” przepuszcza osobę ze słowem „kolejki”).
- Pliki można dodawać i usuwać także na zamkniętej rekrutacji.
- Pole z treścią requestu na `/jobs/new` ma na szerokim ekranie 45% wysokości okna zamiast 70%, żeby karta „Pliki” była widoczna bez przewijania przy 1280 × 720.

## Weryfikacja

| Co | Jak | Wynik |
|---|---|---|
| Frontend — testy zmienionych ekranów | `npx vitest run --no-file-parallelism` (panel plików, okno, nagłówek, routing, `/jobs/new`, edytor wierszy, okno ponownego otwarcia, harnessy, strażniki) | zielone |
| Frontend — typy i lint | `npm run type-check`, `npm run lint` | zielone |
| Backend — lint | `ruff check app/`, `ruff format --check app/` | zielone |
| Backend — testy bez bazy | bramka krytycznych, wzorzec uprawnień tras, lustro migracji, limity żądań, przewodniki | zielone |
| Backend — testy z bazą | pliki (8), ponowne otwarcie, bramka krytycznych z danymi | tylko w CI (na tym komputerze nie stawiamy Postgresa) |
| Ekran przy 1280 × 720 | `/preview/new-job?state=manual` i `review`, `/preview/job-detail` (menu „⋯”, `?files=1`, `?closed=1&reopen=1`) | przeklikane lokalnie |
| Przegląd bezpieczeństwa plików | osobny agent, tylko odczyt | brak blokerów; wzięte dwie uwagi: limit żądań na trasach plików, znaki sterujące w nazwie |

## Poza zakresem

- Słowo jednoliterowe spoza słownika nadal znika przy zapisie po stronie serwera, bez komunikatu na `/jobs/new`.
- Przegląd Delivery Leada pokazuje krytyczną frazę jako „do oceny”, nie „ma / nie ma”.
- Plik na dysku bez wiersza w bazie (commit padł po zapisie pliku albo rekrutacja usunięta kaskadą przy usunięciu klienta) nie jest sprzątany — sprzątanie widzi tylko wiersze.
- Typ pliku sprawdzamy po rozszerzeniu, nie po treści; chroni przed tym pobieranie jako załącznik i `nosniff`.
