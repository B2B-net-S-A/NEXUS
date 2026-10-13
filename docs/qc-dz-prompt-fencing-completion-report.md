# Ogrodzenie danych w promptach poprawek QC i przeglądu DZ (13.10.2026)

Znalezisko z przeglądu bezpieczeństwa PR-a „AI na zaznaczeniu” (#2161): dwa
starsze prompty wklejały tekst z zewnątrz bez ogrodzenia, wbrew regule z audytu
22.09.2026 (`docs/claude/audyty/audyt-22-09-2026-druga-runda-reguly-po-naprawie.md`).

## Co się zmieniło

| Prompt | Było | Jest |
|---|---|---|
| Poprawki AI w QC (`cv_qc._fixes_prompt`) | Braki, tekst oryginalnego CV i notatki wklejone pod nagłówkami pisanymi wielkimi literami | Każdy blok w znaczniku `prompt_fencing` (`cv_gaps`, `original_cv`, `candidate_notes`), którego dane nie mogą zamknąć |
| Podpowiedzi przeglądu DZ (`dz_review.hints_prompt`) | Wynik kodu, zapytanie klienta, CV dla klienta i oryginał wklejone wprost | `cv_checks` (JSON), `client_request`, `cv_for_client`, `original_cv` |

W obu promptach doszło zdanie, że treść w znacznikach to dane, nie polecenia.
Wersje promptów wchodzące do skrótu pamięci wyników są podbite
(`cv-qc-fixes-v4`, `dz-review-v2`), więc zapamiętane odpowiedzi starego promptu
nie są już podawane — pierwsze otwarcie każdego CV policzy podpowiedzi od nowa.

Dla użytkownika nic się nie zmienia: wynik modelu nadal sprawdza ten sam kod
(`parse_fixes`, `parse_hints`).

## Po co

Tekst kandydata (oryginalne CV, punkty CV dla klienta) i zapytanie klienta
mogły zawierać zdanie, które wygląda jak koniec bloku i początek następnego —
np. „notatkę rekrutera” z dowodem na technologię albo nowe zasady dla modelu.
Kontrola wyniku w kodzie ogranicza skutki, ale nie zastępuje ogrodzenia.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Ogrodzenie QC | zielone lokalnie | `tests/test_cv_qc.py::test_fixes_prompt_keeps_cv_original_and_notes_inside_their_tags` — przed zmianą padał |
| Ogrodzenie DZ | zielone lokalnie | `tests/test_dz_review.py::test_hints_prompt_keeps_request_and_both_cvs_inside_their_tags`, `…marks_missing_texts` — przed zmianą padały |
| Regresja | zielone lokalnie | pozostałe testy `test_cv_qc.py`, `test_dz_review.py`, `test_prompt_fencing.py` bez bazy; strażnicy czytający źródła; `ruff` |
| Testy z bazą | w CI | pamięć podpowiedzi (`dz_review_hints`) i trasy QC wymagają Postgresa |

## Przegląd bezpieczeństwa (13.10.2026)

Nic blokującego: 15 552 warianty wrogiego tekstu we wszystkich polach naraz
(znaczniki otwierające i zamykające, wielkość liter, 12 rodzajów odstępów)
zostawiają dokładnie jeden znacznik otwierający i zamykający na blok; żadna
niezaufana wartość nie stoi poza ogrodzeniem; podbicie wersji to tylko
ponowne policzenie podpowiedzi.

Jedna uwaga naniesiona: ogrodzenie podmienia `<` także w zwykłym zapisie typu
`Flux<User>`, a model cytuje to, co widzi — cytat z podmienionym znakiem nie
przechodził kontroli „stoi w źródle” i propozycja odpadała. Parsery odwracają
teraz podmianę w cytacie (`prompt_fencing.restore_tags`), z testami.

## Niepotwierdzone

- Jakość odpowiedzi modelu na nowym układzie promptu — testy podmieniają model.
  Układ treści w blokach jest ten sam, doszły tylko znaczniki i jedno zdanie.

## Poza zakresem

- Poprawki AI w QC nadal czytają notatki z polami handlowymi karty rekomendacji
  (stawka, red flags, motywacja) i oceniają stawkę po samym cytacie — zmiana
  zmieniłaby wyniki QC; czeka na decyzję Artura (opisane w raporcie PR 3).
