# Porcja: test oceny roli przez model (role_fit) na historii decyzji (16.11.2026)

Decyzja Artura z 16.11.2026: ocena roli wchodzi do porcji tylko wtedy, gdy na
historii karty z oceną „nie” mają wyraźnie niższe „Pasuje”. **Wynik: nie mają.
Rekomendacja: nie włączać** w formie „pomiń `nie`, `pokrewna` na koniec”.

## Co sprawdzono

- **Funkcja:** `role_fit` (F51) w rejestrze `services/ai_models.py`, model
  **GPT-6 Luna** (`gpt-6-luna`), zapas Sonnet 5. To ten sam rodzaj zadania co
  przegląd zgłoszeń F27 i „Oceń z AI” F39 (związek doświadczenia z rolą), więc
  wzięty jest ich model: najtańszy i szybki. Test szedł na tym modelu; 0 wywołań
  zeszło na zapas.
- **Wejście:** ostatnie ok. 3 lata z `candidates.experience` (stanowisko, daty,
  opis skrócony do 300 znaków, do 10 technologii; praca zaczęta po dniu decyzji
  jest pomijana) i `cv_extracted_data.current_position`. Z rekrutacji: tytuł,
  `job_plain_briefs.one_liner` (gdy go nie ma, „O projekcie” z Championa)
  i umiejętności krytyczne (`critical_labels`). Bez nazwisk, firm i stawek.
- **Wyjście:** JSON `{"verdict": "tak|pokrewna|nie", "why": "…"}`, prompt
  w `services/role_fit.py`.
- **Decyzje:** wyjście karty od systemu (`entry_source='system'`) z „Nowych”
  ruchem człowieka, poprzedni etap z `lag()` po całej historii pary. Pasuje =
  wyjście nie do `rejected`; powód z `autofill_feedback.reason`, „Inna rola” to
  `other_level_or_role`.
- **Dane:** staging, kopia `nexus_staging_nightly_20261116`, decyzje od 20.08
  do 13.11.2026: **1617 decyzji, 952 Pasuje (58,9%), 665 odrzuceń, w tym 90
  „Inna rola”** (13,5% odrzuceń).
- **Próba warstwowa** (ziarno 20261116): 150 Pasuje, wszystkie 90 „Inna rola”,
  60 pozostałych odrzuceń, razem 300. Odsetki „ważone” przenoszą próbę na całą
  historię wagami warstw (952/150, 90/90, 575/60).
- **Koszt:** 300 wywołań `gpt-6-luna` (2 próbne i 298 w biegu), 174 750 tokenów
  wejścia, 18 478 wyjścia, **0,027 USD**, mediana 1,5 s na wywołanie.

## Wynik

Werdykt w warstwach (n i odsetek warstwy):

| warstwa | tak | pokrewna | nie |
|---|---|---|---|
| Pasuje (150) | 74 (49,3%) | 67 (44,7%) | 9 (6,0%) |
| Inna rola (90) | 6 (6,7%) | 65 (72,2%) | 19 (21,1%) |
| Inne odrzucenie (60) | 26 (43,3%) | 29 (48,3%) | 5 (8,3%) |

Werdykt × Pasuje (ważone = przeniesione na 1617 decyzji, przedział z bootstrapu
po warstwach):

| werdykt | n w próbie | udział w historii | % Pasuje (ważone, 95%) | % Pasuje w próbie | % „Inna rola” wśród odrzuceń (ważone) |
|---|---|---|---|---|---|
| tak | 106 | 44,8% | **64,8%** (57,5–72,2) | 69,8% | 2,4% |
| pokrewna | 161 | 47,5% | **55,4%** (48,3–62,0) | 41,6% | 19,0% |
| nie | 33 | 7,7% | **46,1%** (24,2–69,4) | 27,3% | 28,4% |
| wszystkie | 300 | 100% | 58,9% | 50,0% | 13,5% |

Symulacja w obrębie rekrutacji-dnia (63 grupy z co najmniej 2 kartami w próbie,
górne 50% kart):

| kolejność | kart | % Pasuje (ważone) | % Pasuje w próbie |
|---|---|---|---|
| dzisiejszy wynik (`entry_meta.score`) | 129 | 65,4% | 55,0% |
| `tak` → `pokrewna` → `nie`, w środku wynik | 129 | 65,8% | 55,8% |
| bez `nie`, `pokrewna` na koniec | 127 | 66,8% | 56,7% |

Pominięcie `nie` zdjęłoby ok. 10% odrzuceń (67 z 665), ale też ok. 6% osób,
które rekruter przyjął (57 z 952).

## Wniosek

- Model widzi „Inną rolę”: osoba odrzucona z tym powodem dostaje `tak` w 6,7%
  przypadków, osoba przyjęta w 49,3%. Ale prawie trzy czwarte „Innej roli”
  ląduje w `pokrewna`, a `nie` dostaje tylko 7,7% kart.
- Karty `nie` mają Pasuje 46%, czyli 13 punktów mniej niż średnio, przy
  przedziale 24–69%. To nie jest „wyraźnie niżej”, a próba `nie` (33 karty)
  jest za mała, żeby to potwierdzić.
- W obrębie rekrutacji-dnia górna połowa porcji zyskuje 0,4–1,4 punktu, czyli
  w granicach szumu. Tam, gdzie wynik silnika jest słaby, ocena roli też niewiele
  zmienia, bo karty w jednej rekrutacji dostają zwykle podobne werdykty.
- Fałszywe `nie` powtarzają jeden wzór: rekrutacja na lidera albo rolę
  mieszaną (np. DevOps Lead), a rekruter przyjmuje programistów, którzy
  wcześniej tej roli nie pełnili (4 z 9 fałszywych `nie` to jedna rekrutacja).
- Słabszy sygnał daje `tak` jako pierwszeństwo: 64,8% Pasuje wobec 54,1% przy
  pozostałych. Symulacja nie pokazuje jednak zysku z samej kolejności.

**Rekomendacja: nie włączać** oceny roli w porcji w tej formie. Gdyby wracać do
tematu, trzeba najpierw rozdzielić powód „Inny poziom lub inna rola”, bo na
kopii pole `detail.role_kind` jest puste we wszystkich 113 wpisach. Bez tego nie
wiadomo, ile z tych odrzuceń to poziom, a ile rola.

## Przykłady `nie` (id rekrutacji / id kandydata, uzasadnienie modelu)

1. 789173 / 13162, Inna rola: ostatnio analityk systemowy i architekt rozwiązań, nie rozwijał CI/CD ani automatyzacji wdrożeń DevSecOps.
2. 789187 / 31048, Inna rola: ostatnie role to aplikacje iOS, nie projektowanie systemów i integracji jako analityk systemowy.
3. 789186 / 292834, Inna rola: ostatnio CI/CD i wsparcie techniczne, nie procesy ETL jako Data Engineer.
4. 789198 / 35234, Inna rola: zarządzanie portfelami delivery i transformacją, nie architektura Dynamics 365 / Power Platform.
5. 789200 / 142498, Inna rola: strategiczne role kierownicze w IT, nie praca analityka biznesowego.
6. 789208 / 171759, Inna rola: projekty budowlane i energetyczne, nie komunikacja i zarządzanie zmianą w programie DORA.
7. 789199 / 38236, Brak umiejętności: asystent zespołu i zarządzanie zasobami, nie administracja Power Platform.
8. 789176 / 67511, **Pasuje**: specjalista ds. zarządzania aplikacjami, nie fullstack developer Java/Angular.
9. 789206 / 66465, **Pasuje**: Senior Java Developer, nie lider zespołu DevOps (jedna z 4 takich kart w tej rekrutacji).
10. 723823 / 35350, **Pasuje**: ostatnia praca w DevOps/CI/CD kończy się w 2017, w CV brak ostatnich 3 lat.

## Ograniczenia

- Umiejętności krytyczne, `one_liner` i `experience` są w stanie z kopii z 16.11,
  a nie z dnia decyzji. Praca zaczęta po dniu decyzji jest pomijana, ale opisy
  mogły się zmienić.
- Odsetek Pasuje na kopii (58,9%) jest inny niż 41,4% z pomiaru na produkcji
  z 16.11. Tu Pasuje to każde wyjście nie do `rejected` (screening 844, CV
  wysłane 56, zweryfikowany 31, wycofany 18, rozmowa 3). Porównania wyżej są
  wewnątrz tej samej próby, więc różnica definicji ich nie zmienia.
- Na stagingu dopisano wartość `role_fit` do enumu `aifeaturekey` (`ALTER TYPE`
  tylko na kopii), żeby `ai_feature()` mógł zapisać telemetrię. W repo nie ma
  migracji: klucz istnieje w kodzie tylko na potrzeby testu.

## Jak powtórzyć

Na stagingu z laptopa, bez nowego kontenera (`docker run` zabroniony,
współdzielony staging); kod gałęzi kopiowany do `/tmp` w kontenerze:

```bash
docker exec nexus-staging-postgres-1 psql -U nexus -d nexus_staging_nightly_20261116 \
  -c "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'role_fit'"
cd backend
docker exec nexus-staging-backend-1 sh -c 'rm -rf /tmp/rolefit && mkdir -p /tmp/rolefit/scripts'
tar --exclude=__pycache__ -cf - app | docker exec -i nexus-staging-backend-1 tar -xf - -C /tmp/rolefit
docker cp scripts/eval_role_fit.py nexus-staging-backend-1:/tmp/rolefit/scripts/eval_role_fit.py
docker exec nexus-staging-backend-1 sh -c 'touch /tmp/rolefit/scripts/__init__.py; cd /tmp/rolefit && \
  python -m scripts.eval_role_fit --max-calls 300 --concurrency 6 --out /tmp/role_fit_eval.json'
# same liczby z zapisanego wyniku, bez modelu:
docker exec nexus-staging-backend-1 sh -c 'cd /tmp/rolefit && python -m scripts.eval_role_fit --analyze /tmp/role_fit_eval.json'
```
