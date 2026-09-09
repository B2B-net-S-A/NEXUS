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
