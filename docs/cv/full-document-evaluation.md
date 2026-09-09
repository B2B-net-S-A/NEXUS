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
DOCX i porównaj z podglądem. Sprawdź także przypadki skanów/OCR po ich dodaniu
do korpusu — obecne 40 wariantów ich nie obejmuje.

Odbiór Delivery Leada musi dotyczyć konkretnych plików i recept klientów.
`human_accepted=null` pozostaje brakiem odbioru; skrypt nie nadaje go automatycznie.
Transport pełnych artefaktów z właściwego runtime i uruchomienie tej procedury
pozostają otwarte. Obecny workflow `eval-cv-quality` obsługuje tylko diagnostykę
weryfikatora faktów i nie uruchamia powyższego polecenia.
