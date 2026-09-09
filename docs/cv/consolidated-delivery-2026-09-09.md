# Jeden wspólny PR poprawek CV

Generator potrafił liczyć staż ze skróconej historii, przypisywać kandydatowi niepotwierdzone umiejętności i tworzyć podsumowania podporządkowane wymaganiom oferty. Wspólny pakiet oddziela pełne fakty źródłowe od redakcji CV i wymaga końcowego potwierdzenia twierdzeń przed wygenerowaniem DOCX.

## Zakres wspólnego PR

- Pełna historia źródłowa, dokładne obliczenia zakończonych lat bez tolerancji dodatkowego roku i bez podwójnego liczenia nakładających się okresów.
- Podsumowania oparte na dowodach, bez wymuszania branży IT, największej firmy i wszystkich wymagań MUST.
- Kontrola wszystkich końcowych twierdzeń po tłumaczeniu i redakcji; kompletność werdyktów, dokładne cytaty i schemat JSON odpowiedzi dostawcy. Błędy protokołu pozostają błędami.
- Skracanie zbyt długich obowiązków przez ograniczoną redakcję zamiast obcinania fragmentu tekstu, z ponowną kontrolą faktów.
- Próbki reguły klienta sprawdzane względem konkretnego szkicu i wariantu bazowego, wspólne źródła i jeden pełny zestaw faktów dla obu wariantów.
- Przechwycenie źródeł rekrutacji i wymagań przed przyjęciem zadania; kontrola pliku przed naliczeniem limitu.
- Jedna rezerwacja dwóch jednostek dla porównania reguł; prawidłowe przypisanie wywołań drugiego języka do jego własnej operacji.

To jedyny dalszy PR dla poprawek z obu audytów CV. Obejmuje kod wcześniejszych PR #1463, #1466, #1467, #1468 i #1469 oraz zastępuje wcześniejszy szkic #1441. Zmiany już scalone są częścią aktualnego main. Dalsze brakujące elementy CV-01–CV-20 będą dopisywane tutaj, bez kolejnych osobnych PR-ów.

## Weryfikacja i warunki odbioru

Po integracji aktualnego main: 133 testy źródeł, gotowości, redakcji, faktów, protokołu i rozliczeń przeszły lokalnie. Testy kontrolują odpowiedzi modeli; nie dowodzą jakości rzeczywistych CV. Pełne CI dla końcowego SHA pozostaje wymagane.

Ostatni pomiar starego wdrożonego weryfikatora: 1/4 przypadków, trzy błędy invalid_json, cztery rozliczone wywołania, USD 0.013773. Cztery mikroprzypadki nie są benchmarkiem kompletnego generatora. Zmiana wymuszająca schemat dostawcy wymaga nowego pomiaru.

PR pozostaje szkicem do zakończenia prac i odbioru. Otwarte: pełny korpus CV PL/EN i primary/fallback, koszt/opóźnienie/fałszywe odrzucenia, trwałe zadania i źródła, jawny wybór źródła, brakujące przepływy zatwierdzania, pełna weryfikacja UI oraz odbiór DL i potwierdzone standardy klientów. Rejestr wymagań: docs/cv/remediation-2026-09-09.md i szczegółowe dowody docs/cv/*delivery-2026-09-09.md. Zielone testy nie oznaczają zamknięcia całego zakresu.

## Dalsze poprawki w tym samym PR

Obie wersje językowe zwykłej generacji korzystają z jednego niezmiennego zestawu pełnych faktów (pipeline i upload). Wywołania redakcji i końcowej kontroli nadal są osobne. Po integracji 31 testów źródeł, pełnej historii i obu workerów przeszło.

Ocena instrukcji DL wymaga teraz kompletnej, jednoznacznej odpowiedzi o zadanym schemacie. Duplikat, brak indeksu, indeks logiczny/tekstowy, obcy werdykt, dodatkowe pola i błędny JSON oznaczają wszystkie linie jako wymagające sprawdzenia. Wcześniej parser mógł pominąć nieprawidłowy lub sprzeczny werdykt. 20 testów protokołu i wymuszenia schematu przeszło; nie jest to pomiar jakości modelu. Ocena instrukcji pozostaje poradą; twarda kontrola faktów następuje osobno przed DOCX.

## Pełnodokumentowy korpus v1

`backend/app/data/cv_quality/full_documents_v1.json` zawiera 20 ręcznie opisanych syntetycznych historii z 40 wariantami języka wyniku (PL/EN). Źródła są polskie; wariant EN obejmuje tłumaczenie. Pliki wejściowe DOCX mają akapity lub tabele, doświadczenie, wykształcenie i języki. Kryteria dotyczą m.in. podwójnego liczenia okresów, przerw, brakujących miesięcy, negacji, kursów, certyfikatów, danych prywatnych i instrukcji klienta dopisujących fakty. Etykiety nie pochodzą z ocenianego generatora.

`python -m scripts.prepare_cv_document_corpus --output /tmp/cv-document-corpus` tworzy 40 źródłowych DOCX oraz manifest z hashami i stanem `not_run`. Weryfikacja roundtrip potwierdza zachowanie wszystkich akapitów także w tabelach. Nie wykonuje wywołań modelu ani nie przyznaje ocen jakości. Korpus nie zawiera jeszcze skanów/OCR ani anglojęzycznych źródeł; nie zastępuje niezależnego odbioru DL. Pomiar pełnego pipeline i przegląd wyników pozostają otwarte.
