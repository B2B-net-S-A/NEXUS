# Karta rekomendacji z notatki i „Ułóż w zdanie” — raport (06.10.2026)

Propozycja Olafa (Head of Recruitment), decyzje Artura D1–D5 z 06.10.2026.
Makieta i analiza wpływu: https://claude.ai/artifact/3xRoTbWQpYWX33ME3Z4BPr.

## Co powstało

1. **Karta z notatki** — w oknie „Karta rekomendacji” trzy kafle: „Wgraj
   notatkę” (.docx/.pdf/.txt, 5 MB), „Wklej tekst”, „Wpisz ręcznie”. NEXUS
   czyta notatkę (reguła wzoru działu, potem GPT-6 Luna) i pokazuje listę
   „obecnie → propozycja” z cytatem z notatki. „Zastosuj zaznaczone” zapisuje
   pola karty, odpowiedzi w arkuszu screeningu i tekst notatki w historii.
2. **„Ułóż w zdanie”** — przy każdej odpowiedzi w arkuszu screeningu, zbiorczo
   („Ułóż wszystkie w zdania (N)”) i przy polach „Dlaczego ten kandydat”,
   „Motywacja”, „Red flags”. Propozycja: „Użyj zdania” / „Popraw” / „Zostaw
   hasła”. Przełącznik PL/EN, domyślnie język CV klienta.
3. **Plakietki** — „z notatki (AI)”, „z notatki”, „zdanie z haseł” w karcie,
   arkuszu, profilu kandydata i przeglądzie Delivery Leada; w dymku hasła
   rekrutera.

## Decyzje

| | Decyzja | Gdzie w kodzie |
|---|---|---|
| D1 | Pliku nie zapisujemy, tylko jego tekst jako zwykła notatka (`human`, nie `card` — projekcja nie dopisze odznaczonych pól) | `api/recommendation_card_assist.py` (`read_note_file`, `apply_note`) |
| D2 | Zatwierdzone odpowiedzi idą do arkusza screeningu | `_write_answers` |
| D3 | Język zdań = język CV klienta, przełącznik PL/EN | `phrase_language`, `PhraseLanguageToggle` |
| D4 | „Ułóż w zdanie” także w polach opisowych karty | `PHRASABLE_FIELDS`, `CardUpdate.origins` |
| D5 | Tylko z okna karty, bez automatu | brak haka w zapisie notatki |

## Ochrona przed zmyśleniem

- Reguła wzoru działu (bez AI) wygrywa z modelem; narodowość wyłącznie z reguły.
- Model dostaje notatkę bez narodowości, e-maili, telefonów i LinkedIna.
- Pole bez dosłownego cytatu z notatki odpada; stawka musi mieć swoją liczbę w cytacie.
- `phrase_guard`: zdanie z liczbą, miesiącem, nazwą własną albo technologią
  spoza haseł się nie wstawia — rekruter widzi, co dopisała Luna.
- AI to podpowiedź: awaria modelu = propozycja z samej reguły i komunikat.

## Zmiany techniczne

- Migracja `0421_recommendation_card_assist`: klucze AI
  `recommendation_card_note_read` (F28) i `screening_answer_phrasing` (F29),
  lustro w `entrypoint.sh`.
- `ScreeningAnswerItem`: `origin` += `note_import`, `phrased`; nowe `keywords`
  (poza białą listą dla klienta).
- `manual_value(provenance=…)`, `after_card_save` (wspólne skutki zapisu karty).
- Wyłącznik `RECOMMENDATION_CARD_ASSIST_ENABLED` (domyślnie OFF).
- Pomiar: `scripts/eval_recommendation_card_note.py`.

## Testy

- Backend: `tests/test_recommendation_card_assist.py` (reguła faktów,
  ugruntowanie, prywatność promptu, trasy z bazą), strażnicy rejestru AI,
  allowlisty czytelników karty, wzorzec bramek (`authz_golden`).
- Front: `RecommendationCardDialog.test.tsx` (odczyt → przegląd → zapis,
  blokada przy niezapisanym arkuszu), `PhraseSuggestion.test.tsx`,
  `recommendation-card-note.test.ts`.

## Przeglądy przed PR-em

- Bezpieczeństwo: reguła faktów przepuszczała nazwy zaczynające się od „w”,
  „a”, „do” z notatki (np. „Azure”, „Allegro”) — krótkie słowa porównujemy
  teraz tylko dokładnie, cytat ma min. 5 znaków; walidacja odpowiedzi modelu
  idzie poza pętlą zdarzeń.
- Kod: kolejność zapisu w `apply` (odpowiedzi przed polami, bo zmiana stawki
  bywa z commitem), odświeżenie obiektów po rollbacku, wynik odczytu i zdań
  tylko dla osoby, dla której zapytanie ruszyło, notatka jako `human`.

## Do zrobienia po wdrożeniu

1. Pomiar na 40 notatkach-kartach z produkcji (skrypt wyżej).
2. Włączenie `RECOMMENDATION_CARD_ASSIST_ENABLED=true` workflowem „Coolify set env”.
3. Przeklikanie na produkcji kroku „Odczytaj notatkę” (bez „Zastosuj”).
