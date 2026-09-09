# Pomiar kontroli faktów w CV

Ten pakiet udostępnia bibliotekę weryfikatora i pomiar na **syntetycznych**
źródłach. Nie włącza kontroli w generatorze używanym przez rekruterów.
Włączenie bramki wymaga oddzielnej zmiany, po sprawdzeniu wyników pomiaru.

Zbiór `backend/app/data/cv_quality/factual_gate_v1.json` ma 40 przykładów:
20 poprawnych i 20 zawierających błąd, w językach PL/EN. Sprawdza kwalifikacje,
negacje, jednostki, staż w roli wobec całej kariery, wyniki liczbowe, zakres
odpowiedzialności, precyzję dat, prywatne notatki, aliasy i instrukcje w źródle.
Nie jest pełnym benchmarkiem generowania CV od pliku do DOCX ani zbiorem
odbiorczym ocenionym przez Delivery Leadów.

## Uruchomienie

Po wdrożeniu właściwego SHA uruchom `Coolify Ops` z `action=eval-cv-quality`,
`cv_eval_models=primary|all` i `cv_eval_cases=1..40`. Wybierz ref odpowiadający
wdrożonej wersji. Workflow i proces backendu niezależnie sprawdzają SHA;
zmiana wdrożenia między tymi krokami blokuje wywołania modelu.

`all` mierzy osobno każdy skonfigurowany model generatora. Na czas procesu
wyłączony jest fallback; ustawienia działającego serwera nie są zmieniane.
Wywołania przechodzą przez zwykły limit i licznik AI dla generatora CV.
Brak tokenów, kosztu albo oczekiwanego modelu wyklucza pełny wynik pozytywny.
Nie są czytane ani zmieniane rekordy kandydatów, CV, klientów lub rekrutacji.

Artefakt `cv-quality-<run_id>-<attempt>` zawiera wynik per przypadek/model,
czas, tokeny, koszt, fingerprint zbioru i promptu oraz SHA procesu. Nie zawiera
źródeł, odpowiedzi modelu, notatek rekrutera ani danych dostępowych.
`transport.json` zawiera identyfikator zadania i potwierdzenie jego usunięcia.

## Przerwane i niejednoznaczne wykonania

Identyfikator `<run_id>-<attempt>` jest trwale zarezerwowany w
`app_settings` pod prefiksem `cv_quality_eval:` przed pierwszym wywołaniem AI.
Kolejne uruchomienie z tym samym identyfikatorem wyłącznie odczytuje paragon,
nawet jeżeli poprzednie wykonanie pozostało niekompletne. Każdy przypadek
aktualizuje paragon. Ręczne ponowienie workflow tworzy nową próbę i może
ponownie ponieść koszt — nie należy ponawiać w odpowiedzi na sam timeout.

Kanał tworzy zadanie wyłącznie o własnej nazwie i stałej komendzie. Nie usuwa
zastanych zadań. Nie ponawia POST po niejednoznacznej odpowiedzi. Stan
`creation_unknown_requires_inspection` lub `unknown_requires_inspection`
wymaga odczytu wskazanego zadania w Coolify i sprawdzenia paragonu przed
kolejnym biegiem. Następny pomiar blokuje się, gdy istnieje poprzednie zadanie
z prefiksem tego narzędzia.

Proces ma limit 32 minut, wewnętrzny budżet 30 minut między przypadkami,
a transport czeka maksymalnie 35 minut. Usunięcie zadania harmonogramu nie
jest potwierdzeniem zatrzymania procesu. Trwały paragon zapobiega ponownemu
naliczaniu po restarcie aplikacji; niekompletny pomiar pozostaje niekompletny.

## Interpretacja

Poprawny przykład powinien być zaakceptowany, błędny — odrzucony z przyczyn
semantycznych. Błąd protokołu, nieistniejący cytat i awaria dostawcy nie są
liczone jako poprawne wykrycie halucynacji. Osobno analizuj fałszywe odrzucenia,
przepuszczone błędy, awarie protokołu, czas i koszt. Nawet 40/40 nie dowodzi
poprawności pełnych dokumentów ani stabilnej jakości podsumowań.

Lokalna walidacja bez dostawcy i bazy:

```sh
cd backend
python -m scripts.eval_cv_factual_gate --validate-only
pytest tests/test_cv_quality_runtime.py tests/test_cv_quality_ops.py -q
```

Test współbieżnego zapisu paragonu w `test_cv_quality_runtime_postgres.py`
działa w hostowanym CI na PostgreSQL. Nie wymaga lokalnych kontenerów.
