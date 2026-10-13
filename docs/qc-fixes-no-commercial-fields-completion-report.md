# Propozycje poprawek QC bez pól handlowych karty rekomendacji (13.10.2026)

Decyzja Artura z 13.10.2026. Znalezisko z przeglądów Edytora CV 2 (raporty
PR 3 i ogrodzenia promptów): propozycje poprawek w QC czytały notatki razem ze
stawką, red flags i motywacją z karty rekomendacji, a zdanie z takiej propozycji
trafia do CV dla klienta.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Notatki dla modelu | `cv_qc.generate_fixes` czyta notatki bez pól handlowych karty (`CV_HIDDEN_FIELDS`: stawka, red flags, motywacja, narodowość) — tak jak generator CV i „Rozwiń z oryginału” w edytorze |
| Cytat źródła | Cytat sprawdzany jest na tych samych, okrojonych notatkach — wiersz karty ze stawką albo red flag nie może już być „źródłem” zdania |
| Stawka wpisana prozą | `parse_fixes` odrzuca propozycję, w której zdanie albo cytat podaje stawkę (`states_pay`: słowo o wynagrodzeniu i kwota — ta sama reguła, którą QC wytyka stawkę w CV) |
| Prompt | Nowa zasada 6: stawki, oczekiwania finansowe, motywacja i zastrzeżenia rekrutera nie są treścią CV; wersja `cv-qc-fixes-v5` |

Bez zmian: sprawdzenia QC (lista „Do poprawy”, potwierdzenia z notatek) czytają
notatki jak dotąd, bez samej narodowości — tam notatka jest dowodem, a nie
źródłem zdania. Bez migracji, bez zmian tras i uprawnień, bez zmian we froncie.

## Skutki dla użytkownika

- Okno QC i panel „Do poprawy” w edytorze CV: propozycja AI nie zacytuje już
  stawki, red flag ani motywacji i nie zbuduje z nich zdania.
- Zapamiętane propozycje policzą się raz od nowa przy następnym otwarciu
  (nowa wersja promptu) — jedno wywołanie modelu na CV, na żądanie.
- Może ubyć pojedynczych propozycji, których jedynym źródłem był wiersz
  pola handlowego karty.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Notatki bez pól handlowych | zielone lokalnie | `tests/test_cv_qc.py::test_fix_proposals_read_notes_without_commercial_card_fields` — przed zmianą padał (stawka, red flag i motywacja były w materiale dla modelu) |
| Zdanie albo cytat ze stawką | zielone lokalnie | `test_parse_fixes_drops_a_sentence_or_quote_that_states_pay` (2 przypadki) — przed zmianą oba przechodziły jako poprawka |
| Reszta QC, przegląd DZ, AI w edytorze | zielone lokalnie (bez bazy) | 239 testów w `test_cv_qc.py`, `test_dz_review.py`, `test_cv_selection_ai.py`, `test_recommendation_card_ai_privacy.py`; `ruff check`, `ruff format --check` |
| Trasa `qc/fixes` z bazą | w CI | `test_ai_fix_is_proposed_from_sources_and_applied_to_the_draft` i pozostałe testy z Postgresem |

## Niepotwierdzone

- **Jakość propozycji prawdziwego modelu po zmianie** — testy podmieniają model.
- **Ile propozycji ubędzie na produkcji** — nie mierzone (wymagałoby wywołań
  modelu na prawdziwych notatkach).

## Znane ograniczenia

- Stawka zapisana bez waluty i bez „/h” („oczekuje 150 netto”) w zwykłym zdaniu
  notatki nie jest rozpoznawana przez `states_pay`; pola karty i wiersze
  zaczynające się od „Stawka…” znikają wcześniej, przy czytaniu notatek.
- „rate limiting 100/h” w zdaniu technicznym zostanie odrzucone jako stawka
  (ta sama fałszywa zgodność istnieje w sprawdzeniu „Reguły klienta”).
