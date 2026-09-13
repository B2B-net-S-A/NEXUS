# M02 — Wyszukiwanie i dopasowanie (Talent Radar, przegląd bazy, AI-matches)

| Pole | Wartość |
|---|---|
| Tryb | **R** — ale uruchomienie przeglądu bazy i Radaru TWORZY wiersze `candidate_search_runs` (to zapis techniczny, dozwolony: limit 3 przeglądy na całe UAT) |
| Persony | recruiter, tac, delivery_lead (podgląd); admin |
| Zależności | Fala 0 (D3 z Championem D10, D4 bez widełek), M01 zakończony |
| Czas | ~2,5 h (+ 3 × ~3 min oczekiwania na przegląd) |
| Głębokość | pełna |
| Akcje AI | **TAK** — Radar (embedding zapytania), pełny przegląd (Qdrant + scoring), opisy dopasowań. Zapisz zużycie przed/po. **Nie uruchamiaj równolegle z M04/M05.** |

## Zakres

- `/talent-radar` — wklejony request → ranking bazy (bez zakładania rekrutacji).
- `/candidates/search` — wyszukiwarka ręczna (tokeny must/nice/wyklucz, kolumna dopasowania).
- `/jobs/[id]` → zakładki C2: „Wyszukiwania” (dock gotowości), pełny przegląd bazy, dopasowania AI, rekomendacje.
- Rekrutacja → kandydat → „Dopasowanie” (pierścień + opis).

## Przed startem

- `GET /api/settings/ai` → zapisz `used` dla `talent_radar`/`candidate_search`/`match_justification` (nazwy sprawdź w odpowiedzi).
- Sprawdź, że `RUBRIC_DEALBREAKERS_ENABLED` i polityka must-have nie zostały zmienione w
  trakcie UAT (`GET /api/health` → `checks.qdrant = healthy`; brak `degraded` w `meta` odpowiedzi Radaru).

## NIE KLIKAJ

„Dodaj do pipeline'u” (to P1), „Wyślij CV”, „Zapisz jako rekrutację”, `POST /api/admin/index-cleanup`,
`index-coverage` POST, żadnego „Napraw indeks”. Nie uruchamiaj więcej niż 3 pełnych przeglądów łącznie.

## Scenariusze — Talent Radar

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | recruiter | `/talent-radar` bez klienta → „Szukaj” | przycisk nieaktywny albo walidacja „wybierz klienta” (klient WYMAGANY — filtr blacklist/NDA/weto liczy się względem niego) | P1 |
| S02 | recruiter | picker klienta: wpisz „QA-E2E” | znajduje D1 i D2; **nie ma** opcji „Wszyscy klienci” | P1 |
| S03 | recruiter | wybierz D1, wklej treść: „Senior Python developer, PostgreSQL, Docker, 5 lat, zdalnie, do 160 zł/h” → Szukaj | postęp przeglądu (pasek/licznik), po ~2–4 min lista rankingowa; D5 (Anna Testowa) w top 20 | P1 |
| S04 | recruiter | wynik: kolumny | tożsamość WĘŻSZA niż profil: brak e-maila, telefonu, stawki; warstwa wynagrodzenia „nie dotyczy” (nie 0) | P0 |
| S05 | recruiter | klik „Otwórz profil” na wyniku | otwiera `/candidates/{id}`; przycisk widoczny dla ról z `nav.candidates` | P2 |
| S06 | recruiter | odśwież stronę (F5) w trakcie i po przeglądzie | stan przeglądu odtworzony (ten sam `run_id`), NIE startuje nowy przegląd | P1 |
| S07 | recruiter | otwórz drugą kartę na `/talent-radar` z tym samym klientem | druga karta pokazuje TEN SAM przegląd (ref w localStorage), nie inny ani nowy | P1 |
| S08 | recruiter | podczas trwającego przeglądu kliknij „Szukaj” ponownie | przycisk zablokowany do końca (limit 1 przegląd naraz per autor) | P2 |
| S09 | delivery_lead / tac / finance / sourcer / head_of_recruitment | `/talent-radar` | dostępny dla KAŻDEJ roli (decyzja 19.08); brak `RequireRole` na stronie; **bez nowego przeglądu** — tylko odczyt zapisanego | P1 |
| S10 | recruiter | `meta.degraded` (jeśli Qdrant/Voyage niedostępny) | ekran pokazuje AWARIĘ („wyszukiwanie chwilowo niedostępne”), NIE „Brak dopasowań”; porównaj z `/preview/talent-radar` (harness z mockami obu stanów) | P1 |

## Scenariusze — wyszukiwarka ręczna `/candidates/search`

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S11 | recruiter | must: `Python`, `PostgreSQL`; nice: `Kubernetes`; wyklucz: `PHP` | D5 w wynikach; kandydat z PHP w skillach nieobecny; tokeny jako chipy z kolorem must/nice/wyklucz | P1 |
| S12 | recruiter | wybierz rekrutację D3 dla kolumny „Dopasowanie” | kolumna dla widocznych wierszy: liczba / „Ocena niepełna” / „nie policzono — ponów”; nigdy 0 ani puste; żądanie `/api/search/candidates/scores` ≤ 20 ID naraz | P1 |
| S13 | recruiter | przewiń o 3 strony szybko | brak lawiny żądań scores (anulowanie AbortController); 429 → automatyczne ponowienie, nie błąd | P2 |
| S14 | sourcer / tac spoza zespołu D3 | S12 | ta sama kolumna (ta sama bramka co pełny przegląd) — nie „brak dostępu” | P1 |
| S15 | recruiter | filtr „lokalizacja” `Krakow` (bez ó) | znajduje D6 (Kraków) | P2 |

## Scenariusze — w rekrutacji (C2)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S16 | recruiter | `/jobs/{{D3}}` → dock „Gotowość” | gotowość ✓ (must-have z D3 + Champion D10); brak 422 przy „Przekaż do searchu” | P1 |
| S17 | recruiter | `/jobs/{{D4}}` (bez widełek, must prozą) → gotowość | must-have podane prozą liczą się jako podane; brak widełek to ostrzeżenie, nie blokada | P1 |
| S18 | recruiter | D3 → zakładka „Wyszukiwania” → „Cała baza” → uruchom (przegląd nr 2 z 3) | postęp; wynik po ~3 min; D5 wysoko; kandydaci JUŻ w pipeline D3 ukryci (po P1) | P1 |
| S19 | recruiter | ten sam przegląd otwórz w `/talent-radar` (ten sam klient/rekrutacja) | identyczne liczby: populacja, kompletne/niekompletne oceny, kolejność (akceptacja z 09.09) | P1 |
| S20 | recruiter | wynik przeglądu: kandydat bez danych o skillach | widoczny (polityka `review` ukrywa tylko ZNANE skille nieobejmujące must-have) | P1 |
| S21 | recruiter | wynik przeglądu, kandydat z must-have brakującym w znanych skillach | ukryty (bramka must-have) — sprawdź na 1 przykładzie przez porównanie z `/candidates/search` | P2 |
| S22 | recruiter | kliknij kandydata w wyniku → „Dopasowanie” | pierścień z liczbą; opis AI tłumaczy mocne strony i luki, BEZ liczby punktów w tekście | P2 |
| S23 | recruiter | „Dopasowania AI” / rekomendacje w D3 | lista lub czytelny pusty stan; wiersze „warn” widoczne (nadpisanie produktowe); brak 500 | P2 |
| S24 | recruiter | przegląd `failed` (jeśli wystąpi) | ekran „Uruchom ponownie”, nie wieczny spinner; odpytywanie zatrzymane po błędzie ostatecznym | P1 |
| S25 | admin | `GET /api/admin/index-coverage` | blok `candidate_search` z rozmiarem tabeli; liczby > 0; **nie wołaj POST** | P3 |

## Kontrole API

```js
const tok = localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const ai = await fetch('https://api.nexus.dynaminds.pl/api/settings/ai',{headers:h}).then(r=>r.json());
console.table(ai.features.map(f=>({f:f.feature, used:f.usage_this_month, limit:f.monthly_limit})));
```
Wykonaj przed i po karcie. Różnica → raport.

## Znane pułapki

- Przegląd trwa ~3 min i żyje w procesie web: **deploy w trakcie = przegląd `failed`**.
  Jeśli SHA się zmienił między startem a końcem — powtórz, nie zgłaszaj.
- Ranking NIE ma cache'u między różnymi treściami requestu — dwa różne teksty dają dwa przeglądy.
- `must_skills` w kolumnie rekrutacji to PROZA; bramka czyta rozpoznane technologie — brak
  bramkowania po prozie jest poprawny.
- Radar nie niesie kontaktów — brak e-maila na liście to cecha, nie błąd.

## Do raportu

`run_id` każdego uruchomionego przeglądu (3), czasy trwania, liczby z S19 obok siebie,
zużycie AI przed/po.
