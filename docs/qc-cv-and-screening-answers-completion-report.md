# QC CV blokuje tylko to, co ważne · odpowiedzi ze screeningu widać w profilu

Data: 02.10.2026. Makiety: https://claude.ai/artifact/3NxL9R2ecLCz5gXs5dTVC9.
Jeden PR, bez migracji i bez zmian zmiennych środowiskowych.

## Co zgłoszono

Uwagi z testów manualnych (02.10.2026) i odczyt z produkcji tego samego dnia:

1. **Okno QC CV nie tłumaczy, co zrobić.** Od 23.09 QC sprawdziło 8 par
   kandydat × rekrutacja: 1 przeszła, 7 nie, 3 przepuszczono ręcznie.
   Sprawdzenie „każde must-have klienta jest w CV” padało w 7 z 8 par
   (średnio 6 braków), bo wymagało każdego zdania z maila klienta.
2. **„Przepuść z powodem” wymagało 10 znaków** — jednym z zapisanych powodów
   był ciąg losowych liter.
3. **W profilu kandydata nie było odpowiedzi ze screeningu.** Karta
   „Screeningi” czytała starą tabelę notatek (ostatni wpis z 15.04), a arkusz
   Championa zapisuje się przy etapie rekrutacji. Dok na Tablicy mówił tylko
   „Odpowiedziano na N pytań”.

## Decyzje (02.10.2026)

1. QC blokuje wyłącznie: brak CV firmowego, umiejętności krytyczne, zgodność
   z oryginalnym CV i reguły klienta. Reszta to uwagi.
2. Umiejętności krytyczne = wybór Delivery Leada, a bez niego podpowiedź
   z historii (ta sama reguła co bramka wyszukiwania).
3. „Przepuść mimo QC”: cztery gotowe powody, opis wymagany tylko przy „Inny
   powód”, bez minimum znaków.
4. Jedna karta odpowiedzi z rozmów w zakładce Profil zamiast martwej karty
   „Screeningi”.
5. W arkuszu screeningu wcześniejsza odpowiedź stoi pod pytaniem z przyciskiem
   „Użyj tej odpowiedzi”; Luna rusza raz, po otwarciu arkusza.

## Co się zmieniło

### QC CV

- **Cztery sprawdzenia blokujące** (`cv_present`, `critical_skills`,
  `no_unsupported`, `client_rules`), dziewięć uwag. `blocking_failed` liczy
  rzeczy do poprawy (różne wymagania) — tę samą liczbę pokazują chip na
  Tablicy, okno QC i komunikat odmowy ruchu („CV nie przeszło QC — do
  poprawy: N.”).
- **Brak CV firmowego** ma własne sprawdzenie; po odkręceniu `must_in_cv`
  para bez CV przechodziłaby QC.
- **Wymaganie z wersją** („Spring Boot 3.4+”) szuka w CV nazwy bez wersji,
  chyba że cała nazwa jest w słowniku umiejętności. Wersja wpisana wprost
  w CV, której nie ma w oryginale ani notatkach, nadal blokuje.
- **Klauzula RODO** jest osobnym blokiem i nie należy do ostatniej roli —
  wcześniej dostawała czerwoną krawędź „brakuje opisu technologii”.
- **Okno QC**: pasek „Co sprawdza QC” z nazwami umiejętności krytycznych i ich
  źródłem, „Do poprawy przed wysłaniem” (jedna karta na wymaganie, z przyciskiem
  naprawy), „Warto poprawić — nie blokuje”, „W porządku”, a w stopce „Przesuń
  dalej” (ten sam ruch co strzałka na karcie). Na wąskim ekranie panele stoją
  jeden pod drugim (wcześniej nachodziły na siebie).
- **„Przepuść mimo QC”** to osobne okno z czterema powodami; lista powodów ma
  lustro backend ↔ frontend pilnowane testem. Stary klient wysyłający sam
  tekst powodu działa dalej.

### Odpowiedzi ze screeningu

- **Serwer zapisuje treść pytania przy odpowiedzi** (`question_text`).
  Identyfikatory pytań są pozycyjne, więc po edycji profilu Championa samo
  `question_id` wskazywało inne pytanie.
- **`GET /api/candidates/{id}/screening-answers`** — jedna rozmowa na
  rekrutację (najnowszy wypełniony arkusz pary), tylko rekrutacje widoczne dla
  patrzącego.
- **Karta „Odpowiedzi z rozmów screeningowych”** w zakładce Profil, pod
  „Podsumowaniem”: najnowsza rozmowa rozwinięta, starsze zwinięte, szukanie od
  dwóch rozmów, awaria odczytu jako komunikat z „Ponów”. Karta „Screeningi”
  z zakładki Rekrutacje usunięta.
- **Dok osoby na Tablicy** pokazuje pod wynikiem pytania z odpowiedziami.
  Profil, dok i panel osoby używają jednego komponentu listy odpowiedzi.
- **Podpowiedzi w arkuszu** działają dla każdej osoby z wcześniejszą rozmową
  (do trzech rozmów z innych rekrutacji), nie tylko przy przepięciu. Pod
  pytaniem stoi dosłowna wcześniejsza odpowiedź z rekrutacją, klientem i datą;
  po 30 dniach dopisek „dopytaj, czy nadal aktualne”. Odpowiedź przeniesiona
  z podpowiedzi i poprawiona ręcznie zapisuje się jako odpowiedź z tej
  rozmowy. Awaria Luny to komunikat — arkusz działa ręcznie.

### Po przeglądzie bezpieczeństwa

Przegląd nie znalazł ustaleń krytycznych ani wysokich. Wprowadzone drobne
zabezpieczenia:

- arkusz screeningu ma limit rozmiaru na wejściu (100 odpowiedzi, 10 000
  znaków na odpowiedź i notatkę; największy arkusz na produkcji: 6 odpowiedzi,
  260 znaków),
- do modelu idzie najwyżej 12 000 znaków wcześniejszych pytań i odpowiedzi,
- wzorzec maskowania kwot ma ograniczony ciąg cyfr (bez limitu cofał się
  kwadratowo na długim ciągu cyfr),
- identyfikator kandydata w nowej trasie spoza zakresu kolumny daje 422.

## Weryfikacja

- Backend: `ruff check app/`, `ruff format --check app/`, stemple przewodników
  (`scripts/check_stamps.py`), testy bez bazy lokalnie; testy z bazą w CI
  (sito na PR i pełny bieg na gałęzi).
- Frontend: `tsc --noEmit`, vitest na zmienionych plikach i strażnikach
  (dane fikcyjne w harnessach, zasiane klucze, kotwice pomocy, spis funkcji
  rekrutacji, natywne okna, `detail` z API).
- Przeglądarka, 1280×720 i 390 px, zero żądań do API:
  `/preview/cv-qc` (stany: do poprawy, przechodzi, brak CV, okno obejścia
  z walidacją), `/preview/candidate-profile` (karta, szukanie),
  `/preview/pipeline-v4` (podpowiedzi z wcześniejszych rozmów, przepięcie,
  odpowiedzi w doku).

## Poza zakresem i znane ograniczenia

- Podpowiedzi Luny sprawdzone na danych testowych — w dniu wdrożenia żaden
  kandydat nie miał dwóch rozmów w różnych rekrutacjach.
- Podpowiedź umiejętności krytycznych przelicza się co tydzień, więc werdykt
  QC rekrutacji bez wyboru Delivery Leada może się zmienić bez zmiany CV;
  okno QC nazywa źródło.
- Zapisane statusy QC istniejących par odświeżą się przy pierwszym otwarciu
  okna albo ruchu karty.
- Arkusze zapisane przed zmianą biorą tekst pytania z bieżącego profilu
  Championa po identyfikatorze; nowe zapisy mają własny tekst.
- „Usuń z rekrutacji” nadal kasuje arkusz pary; generator CV i portal klienta
  nadal łączą odpowiedzi z pytaniami po identyfikatorze.
- Podpowiedź może pochodzić z rozmowy u innego klienta (podpis pod pytaniem
  mówi, z której rekrutacji i od którego klienta). Odpowiedzi z arkusza widzi
  klient w portalu, więc przed „Użyj tej odpowiedzi” warto przeczytać, czy
  odpowiedź nie mówi o poprzednim kliencie. Notatki rekruterów z innych
  rekrutacji nie są materiałem podpowiedzi (poza przepięciem).
