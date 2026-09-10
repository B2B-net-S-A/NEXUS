# Ocena pełnych generacji CV

Ten przebieg sprawdza zwykły pipeline uploadu na syntetycznych źródłach.
Nie został jeszcze wykonany na rzeczywistych modelach dla PR #1444.
Zielone testy skryptu ani diagnostyka samego weryfikatora faktów nie zastępują tej oceny.

## Uruchomienie

Uruchom w backendzie o zweryfikowanym SHA, z jego zwykłą bazą, konfiguracją
modeli i bramką `ai_feature`. `--expected-sha` musi odpowiadać rzeczywistemu
runtime; nie nadpisuj `GIT_SHA`, aby ominąć kontrolę. Nie uruchamiaj lokalnego Dockera.

```sh
python -m scripts.eval_cv_full_documents \
  --output /tmp/cv-full-evaluation/RUN_ID \
  --run-key RUN_ID \
  --expected-sha VERIFIED_RUNTIME_SHA \
  --offset 0 --limit 2 --models all
```

`RUN_ID` zastąp nową tożsamością w formacie liczbowym `numer-próba`, np.
identyfikatorem wykonania workflow i jego próbą. Dla kolejnej partii wybierz
następny zakres i nową tożsamość. Zakresy są indeksowane od zera; `offset + limit`
nie może przekroczyć 40. `models=all` wykonuje osobno skonfigurowany model główny
i każdy fallback. Limit czasu jest sprawdzany między przypadkami.

Istniejący receipt kończy wywołanie bez ponownej generacji. Po przerwaniu sprawdź
`report.json`, `in_progress`, zapis operacji i metering przed zaplanowaniem
dalszego zakresu. Nowy `RUN_ID` nie jest mechanizmem bezkosztowego retry.

## Dowody odbioru

Zachowaj cały katalog: raport główny, manifest wejść, pliki źródłowe oraz katalogi
`model-*` z DOCX i payloadami. Sprawdź SHA runtime i korpusu, żądane identyfikatory
przypadków, rzeczywiste modele i kompletność kosztów. `complete=true` oznacza
zakończenie wybranej partii; `covers_full_corpus=false` nie jest oceną całego korpusu.

Dla każdego modelu zestaw wszystkie 40 identyfikatorów, bez braków i nieświadomych
duplikatów. Oceń zgodność całej historii, staż pełny i branżowy, podmiot, negacje,
jednostki, jakość podsumowania oraz zgodność pogrubień i reguł klienta. Otwórz
DOCX i porównaj z podglądem. Wykonaj również osobny przebieg 40 wariantów skanów/OCR opisany poniżej;
przebieg DOCX nie stanowi dowodu jakości odczytu skanów.

Odbiór Delivery Leada musi dotyczyć konkretnych plików i recept klientów.
`human_accepted=null` pozostaje brakiem odbioru; skrypt nie nadaje go automatycznie.
Transport pełnych artefaktów z właściwego runtime i uruchomienie tej procedury
pozostają otwarte. Obecny workflow `eval-cv-quality` obsługuje tylko diagnostykę
weryfikatora faktów i nie uruchamia powyższego polecenia.

### Known unsupported claims in rendered documents

The runner checks each case's `unsupported_claims` against visible DOCX body,
header and footer text, including table cells and claims split across Word runs.
A known claim or an unreadable/empty artifact makes the batch unsuccessful.
Reports include `rendered_text_readable`, `known_unsupported_claims_found` and
`known_unsupported_claims_absent`. This literal regression check does not prove
absence of paraphrased hallucinations; full semantic and human review remain
required. Source-ledger contents are not treated as rendered candidate claims.

Host-native validation: 22 runner tests passed, including complete batch return
codes with and without an invented career-duration claim in a real DOCX file.
No live provider evaluation was performed for this change. Read-only staging
status run 34417172000 still reported `exited:unhealthy` on another task's branch.
# Source role identity acceptance

All 40 corpus cases now specify the expected source date/company/title triples.
The runner compares these as a multiset against the extracted source ledger,
independently of presentation language and role ordering. A matching role count
cannot conceal duplicated roles or dates/titles transferred to another employer.
This changes the corpus digest; use a new output directory and run identity.
The check does not establish responsibility-level completeness or semantic truth;
real-model runs and human review remain required.

# Scanned source variants

Both preparation and full evaluation accept `--scan-font /absolute/path/to/font.ttf`.
This renders every original source history to an image-only PDF, then runs the
ordinary OCR and generation path during evaluation. Use a font covering Polish
characters, such as DejaVu Sans. Each paragraph is wrapped to the page width and
continues onto subsequent pages; an overwide word is rejected instead of clipped.

Use a separate output directory and run identity for the scan measurement. The
manifest records the font hash, renderer version and resolution, and derives a
different corpus hash from the DOCX measurement. All 40 language variants retain
their source paragraphs and acceptance criteria. Preparing these files does not
run OCR or a model and does not establish quality acceptance. Model measurement,
visual inspection of rendered inputs and outputs, and human acceptance remain
required. Existing output and input evidence is not overwritten on reuse.

## Arkusz odbioru jakości pojedynczego CV

Wypełnia oceniający po otwarciu źródła, wynikowego DOCX i HTML. Sama obecność
pliku lub status `verified` nie wypełnia żadnej oceny. Zapisz po jednym wierszu
dla każdego przypadku, modelu i rodzaju źródła. Brak pliku, błąd generacji lub
brak recenzji pozostaje jawnym wynikiem, a nie pominięciem z mianownika.

| Pole | Wartość do zapisania |
|---|---|
| Tożsamość | run ID, case ID, runtime SHA, corpus SHA, żądany i rzeczywisty model, DOCX/skan |
| Artefakty | ścieżka i SHA-256 źródła, DOCX, HTML oraz identyfikator i wersja receptury |
| Oceniający | imię/nazwa użytkownika, rola, data oceny |
| Fakty | każde twierdzenie bez potwierdzenia: cytat wyniku, lokalizacja i odpowiadający fragment źródła |
| Staż | oczekiwany i podany staż całkowity; osobno każda deklaracja stażu roli/technologii; nakładające się okresy i niepełne daty |
| Kompletność | pominięte fakty istotne dla roli; rozróżnij świadomy limit prezentacji od braku w ekstrakcji |
| Podsumowanie | ocena 0–3 według skali poniżej i konkretny przykład wymagający poprawy |
| Pogrubienia | frazy oczekiwane, brakujące i nadmiarowe; strona/akapit w DOCX i odpowiadający fragment HTML |
| Reguły klienta | każda aktywna reguła: spełniona / konflikt / nie dotyczy / wymaga oceny, z dowodem w pliku |
| Decyzja | zaakceptowane / do poprawy / brak oceny; przyczyna i zakres decyzji |

Skala podsumowania: **0** — błędne lub nieprzydatne; **1** — ogólne frazesy albo
lista technologii bez wyjaśnienia doświadczenia; **2** — zwięzły, czytelny opis
potwierdzonego doświadczenia i jego związku z rolą; **3** — spełnia poziom 2 oraz
jasno pokazuje wyróżniające, udokumentowane osiągnięcia lub odpowiedzialności bez
powtarzania historii stanowisk. Brak osiągnięć w źródle nie upoważnia do ich dopisania
w celu uzyskania wyższej oceny. Oceniaj źródło PL/EN, nie wyłącznie płynność tekstu.

Zmyślona kompetencja, zmiana negacji, zawyżony staż, przypisanie pracy szkoleniowej
do produkcyjnej lub ujawnienie prywatnej informacji oznacza „do poprawy” niezależnie
od średniej ocen. Nie kompensuj takich błędów dobrym formatowaniem. Porównanie modeli
musi pokazywać osobno: powodzenie generacji, odsetek odrzuceń kontroli, potwierdzone
błędy faktów, oceny podsumowań, błędy pogrubień, czas i koszt. Podaj licznik i mianownik
każdej miary; odrzucone generacje nie są poprawnymi CV.

Proponowany próg redakcyjny do zatwierdzenia przez DL: minimum 2 dla każdego
zaakceptowanego podsumowania, brak krytycznych błędów faktów i rozwiązanie wszystkich
konfliktów obowiązkowych reguł. To propozycja kryterium, nie zapis uzyskanego odbioru.
Recenzent zapisuje decyzję dla konkretnych artefaktów; nie nadpisuje automatycznie
`human_accepted` w surowym raporcie pomiarowym. Zbiorczy protokół wskazuje te decyzje
i brakujące przypadki osobno dla każdego modelu i formatu źródła.
