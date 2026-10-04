# „Stawka od” i historia stawek kandydata — raport (0414, 04.10.2026)

## Po co

Kandydat podaje różne stawki na różne role. Do tej zmiany filtry, AI
i plakietki budżetu czytały jedną liczbę: `candidates.expected_rate_hourly`,
czyli stawkę zapisaną w profilu jako ostatnia. Stawki z rozmów o konkretnych
rekrutacjach (karty rekomendacji, okno „Zweryfikowany”) nie docierały do
żadnego z tych miejsc.

Pomiar na produkcji z 04.10.2026 (tylko odczyt):

- 8 759 par kandydat × rekrutacja ma w karcie rekomendacji stawkę w PLN/h (4 856 osób).
- 991 osób podało różne stawki w różnych rekrutacjach, 323 z różnicą co najmniej 20%.
- Tylko 30% z tych 991 ma w profilu swoją najniższą stawkę, 67% ma wyższą.
- Symulacja nowej reguły: obniża stawkę u 1 243 osób, uzupełnia 118 pustych
  profili i odcina 44 osobom niską stawkę starszą niż 18 miesięcy.

Makiety i decyzje: https://claude.ai/artifact/SxV3wMXBL8FhA2Q743HwEd

## Decyzje Artura (04.10.2026)

| Sprawa | Decyzja |
|---|---|
| Okno | 18 miesięcy |
| Karta rekomendacji | wpływa na „Stawkę od” jako wartość liczona, bez nadpisywania profilu |
| „Na podobne stanowisko” | nie robimy |
| Brak stawki w oknie | ostatnia znana stawka, oznaczona jako nieaktualna |
| Wartości odstające | liczą się; rekruter wyłącza je ręcznie |
| Zakres „120–140” | liczy się dolna granica |
| Ekrany rekrutacji | obok siebie „W tej rekrutacji” i „Stawka od” |
| Kto zmienia minimum | każdy z prawem edycji faktów profilu |
| Wdrożenie | od razu, z wyłącznikiem `CANDIDATE_RATE_FROM_ENABLED` |

## Co zmieniono

**Backend.**

- Migracja `0414_candidate_rate_from`. SQL ma jedno źródło
  (`services/candidate_rate_from_schema.py`), które importuje też entrypoint.
  Dodaje kolumny `rate_from_*`, `rate_latest_*`, `rate_observation_count`,
  tabele `candidate_rate_decisions` i `candidate_rate_from_queue`, wyzwalacze
  dopisujące do kolejki oraz jednorazowe zakolejkowanie wszystkich kandydatów.
- Zbieranie obserwacji: `services/candidate_rate_observations.py`.
- Reguła i przeliczanie: `services/candidate_rate_from.py`. Funkcja `compute`
  jest czysta. Wynik zapisuje się surowym `UPDATE`, więc `updated_at` się nie zmienia.
- Pętla `tasks/candidate_rate_from.py` z heartbeatem.
- Nowe trasy w `api/candidate_rates.py`:
  `GET /api/candidates/{id}/rate-overview` i
  `PUT /api/candidates/{id}/rate-observations/{key}`.
- `PATCH …/profile-rate` przyjmuje pole `is_minimum`.
- `StageMove` przyjmuje pole `expected_rate_is_minimum`.
- Na „Stawkę od” przełączeni czytelnicy:
  - filtr i ranking listy,
  - plakietka budżetu (`rate_fit`),
  - ocena dopasowania (`rate_contract` w `scoring_algorithm_version`),
  - listy praktykantów,
  - wymagania ruchu,
  - odpowiedzi listy, podglądu, wyszukiwarki, dopasowań AI, propozycji,
    „Moich ludzi”, tablicy, eksportu CSV i Jarvisa.
- Strażnik `tests/test_rate_from_readers_guard.py` pilnuje, żeby nowy moduł
  nie czytał `expected_rate_hourly` wprost.

**Frontend.**

- Kafel „Stawka od” w profilu z linią „ostatnio …” i linkiem „Historia stawek”.
- Okno `RateHistoryDialog`: wykres w czasie z oknem 18 miesięcy, linią minimum
  i umowami; tabela z powodem dla każdej stawki; przyciski „Nie licz jako
  minimum” / „Przywróć” i „Ustaw minimum ręcznie”.
- Edycja stawki profilu ma checkbox „To jego minimum”.
- Lista kandydatów: „od 125 zł/h”, pod spodem „ostatnio 160 zł/h”.
- Podgląd kandydata, propozycje, podgląd osoby („Stawka od”, „W tej rekrutacji”).
- Przegląd DL i dok osoby: „W tej rekrutacji” obok „Stawki od”.
- Okno „Zweryfikowany”:
  - podpowiedź: karta tej rekrutacji, potem „Stawka od”, potem profil;
  - linia „Stawka od”;
  - checkbox „To jego nowe minimum”.
- Usunięty `RateHistoryWidget` (2 wiersze, edycja tylko dla admina). Jego
  trasy `phase5` zostają, a wpisy widać w nowej historii jako „stary wpis”.

**Zmiana wcześniejszej reguły.** Do tej pory (#2005, 03.10) w oknie
„Zweryfikowany” profil wygrywał z kartą rekomendacji. Teraz wygrywa karta tej
rekrutacji, bo okno pyta o oczekiwania w tej konkretnej rekrutacji. Test
zaktualizowano, CLAUDE.md też.

## Przegląd kodu i poprawki

Przegląd (subagent) znalazł cztery błędy blokujące. Wszystkie są poprawione
i mają testy:

1. **Okno 18 miesięcy przesuwało się tylko przy zmianie danych.** Stara
   minimalna stawka zostawała na zawsze.
   Poprawka: pętla raz dziennie kolejkuje kandydatów, których minimum wypadło z okna.
2. **Wyścig pętli z równoległym zapisem.** Zmiana zapisana w trakcie
   przeliczenia mogła zostać zgubiona, a stary wynik nadpisać nowy.
   Poprawka:
   - wyzwalacz podbija datę wpisu w kolejce;
   - `recompute` najpierw blokuje kandydatów i kasuje tylko wpisy z datą, którą sam przeczytał;
   - pętla pomija zablokowanych kandydatów i nigdy na nic nie czeka.
3. **Lista telefonów praktykanta liczyła świeżość od daty najniższej stawki.**
   Poprawka: liczy od daty ostatnio podanej stawki.
4. **„Nie licz jako minimum” wyłączało każdą przyszłą wartość pod tym samym kluczem karty.**
   Poprawka: decyzja zapamiętuje kwotę i datę stawki.

Dodatkowo:

- Poprawka stawki profilu przez tę samą osobę w ciągu 10 minut zastępuje
  poprzedni wpis, więc literówka nie zostaje minimum na 18 miesięcy.
- Stawka w obcej walucie znów jest widoczna w kolumnie listy.

Świadomie bez zmian: dodawania starych wpisów stawek z umów (trasy `phase5`,
2 wiersze, tylko admin) nie ma już w interfejsie. Ich treść jest widoczna
w historii stawek.

## Weryfikacja

- Backend lokalnie (Python 3.12, bez bazy):
  - `ruff check` i `ruff format --check` na `app/` przechodzą;
  - `tests/test_candidate_rate_from.py`: reguła, jednostki, waluta, wyłącznik, lustro entrypointu;
  - `tests/test_rate_from_readers_guard.py`;
  - testy dealbreakerów, predykatów wyszukiwania, heartbeatu, przewodników ekranów;
  - wzorzec uprawnień (nowy plik `tests/data/authz_golden/candidate_rates.json`).
- Testy z bazą są w `tests/test_candidate_rate_from_db.py` i biegną w CI:
  - wyzwalacze;
  - `updated_at` się nie zmienia;
  - filtr `max_rate` znajduje kandydata po „Stawce od”;
  - historia stawek, wykluczenie stawki i jawne minimum.
- Front:
  - `vitest --changed`: 456 plików, 4 966 testów zielonych;
  - `tsc` bez błędów;
  - ESLint bez uwag.
- Harnessy `/preview/candidate-profile` (kafel i okno historii, 1280×720
  i 390 px), `/preview/candidates-list` (1536×864) i `/preview/dl-review`:
  obejrzane na zrzutach z wbudowanej przeglądarki.

## Co sprawdzić po wdrożeniu

1. `/api/health` zwraca SHA commita z maina.
2. Zapytania tylko do odczytu:
   - `SELECT count(*) FROM candidate_rate_from_queue` — kolejka powinna spaść do 0;
   - `count(*) WHERE rate_from_computed_at IS NOT NULL`;
   - liczba kandydatów z `rate_from_hourly < expected_rate_hourly` — spodziewane ok. 1 243.
3. Kandydat z przykładu (80 i 135–140 zł/h): `GET /rate-overview`.
4. Liczba powiadomień `saved_search_match` z dnia wdrożenia — nie powinno być lawiny alertów.
