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
| Pieniądze wpisane prozą | `parse_fixes` odrzuca propozycję, która wnosi pieniądze spoza CV kandydata (`brings_money`): zdanie albo cytat ze stawką, cytat z notatek z jakąkolwiek kwotą, kwotę, której nie ma w cytacie z oryginału ani w zastępowanym punkcie. Kwota z CV kandydata (wynik projektu) może zostać |
| Propozycje zapamiętane wcześniej | `load_fix` stosuje tę samą regułę — propozycji ze stawką sprzed zmiany nie da się już zastosować z otwartej wcześniej karty |
| Wzorzec kwoty | Ścisły `_MONEY` przeniesiony z „AI na zaznaczeniu” do `cv_qc` (jedna definicja, dwa miejsca użycia) |
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
| Pieniądze z notatek | zielone lokalnie | `test_parse_fixes_drops_a_proposal_that_brings_money_from_the_notes` (5 przypadków, w tym kwota bez słowa „stawka”) — przed zmianą wszystkie przechodziły jako poprawka |
| Kwota z CV kandydata zostaje | zielone lokalnie | `test_parse_fixes_keeps_an_amount_the_candidate_wrote_in_the_cv`, `test_parse_fixes_does_not_take_a_number_before_a_word_for_money` („3 europejskich”, „5 złożonych”) |
| Zapamiętane propozycje | zielone lokalnie | `test_a_stored_proposal_with_a_rate_can_no_longer_be_applied` |
| Reszta QC, przegląd DZ, AI w edytorze | zielone lokalnie (bez bazy) | 290 testów w `test_cv_qc.py`, `test_dz_review.py`, `test_cv_selection_ai.py`, `test_cv_command_ai.py`, `test_recommendation_card_ai_privacy.py`; `ruff check`, `ruff format --check` |
| Trasa `qc/fixes` z bazą | w CI | `test_ai_fix_is_proposed_from_sources_and_applied_to_the_draft` i pozostałe testy z Postgresem |

## Przegląd bezpieczeństwa przed PR-em (13.10.2026)

Niezależny przegląd pierwszej wersji (sama reguła „słowo o wynagrodzeniu
i kwota”) znalazł lukę, potwierdzoną na prawdziwym kodzie: stawka wpisana prozą
bez słowa „stawka” („…przez dwa lata, 160 zł/h B2B”) nie znika przy czytaniu
notatek, a propozycja z taką kwotą była przyjmowana. Poprawione od testu —
stąd reguła `brings_money` i kontrola w `load_fix`. Przy poprawce wyszło
jeszcze, że luźny wzorzec kwoty z reguł klienta odrzucałby uczciwe zdania
(„w 3 europejskich bankach”) — stąd ścisły `_MONEY`. Pozostałe punkty
przeglądu bez uwag: notatki w prompcie, zgodność skrótu pamięci z materiałem,
kontrakt „nigdy 5xx”, ogrodzenie promptu i weryfikacja cytatu.

## Niepotwierdzone

- **Jakość propozycji prawdziwego modelu po zmianie** — testy podmieniają model.
- **Ile propozycji ubędzie na produkcji** — nie mierzone (wymagałoby wywołań
  modelu na prawdziwych notatkach).

## Znane ograniczenia

- Stawka zapisana bez waluty i bez „/h” („oczekuje 150 netto”) w zwykłym zdaniu
  notatki nie jest rozpoznawana jako kwota; pola karty i wiersze zaczynające
  się od „Stawka…” znikają wcześniej, przy czytaniu notatek.
- Red flag albo motywacja wpisane prozą, bez etykiety karty, zostają w notatkach
  — tego nie rozpozna żaden wzorzec; pilnuje ich zasada 6 promptu i rekruter,
  który czyta propozycję przed „Zastosuj”.
- Zdanie z notatek z liczbą „na godzinę” („1000/h zdarzeń”) zostanie odrzucone
  jako kwota — ubywa wtedy propozycji, nie treści CV.
- Ta sama kwota w innym zapisie („20 000 EUR” i „20 tys. euro”) liczy się jako
  nowa i odrzuca propozycję.
- Propozycje sprzed zmiany, które niosły red flag albo motywację (bez kwoty),
  nadal da się zastosować z karty otwartej przed wdrożeniem — do odświeżenia.
