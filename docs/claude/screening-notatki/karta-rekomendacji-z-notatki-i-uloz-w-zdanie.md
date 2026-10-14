# Karta rekomendacji z notatki i „Ułóż w zdanie” (0421, 06.10.2026)

Propozycja Olafa, decyzje Artura D1–D5 z 06.10.2026 (makieta:
https://claude.ai/artifact/3xRoTbWQpYWX33ME3Z4BPr). Kod:
`services/recommendation_card_assist.py` (reguły i model),
`api/recommendation_card_assist.py` (trasy), front (od 0424)
`components/v2/screening-form/NoteFillBar.tsx`, `PhraseSuggestion.tsx`.
Harness `/preview/screening-form?state=note`. Raport:
`docs/recommendation-card-from-note-completion-report.md`.

- **Wyłącznik `RECOMMENDATION_CARD_ASSIST_ENABLED` (domyślnie OFF)** — trasy
  404, karta niesie `assist_enabled: false`, okno karty i arkusz działają
  ręcznie jak dotąd. Włączenie po pomiarze `python -m
  scripts.eval_recommendation_card_note --limit 40` w kontenerze backendu.
- **Od 0424 „Uzupełnij z notatki” stoi na górze formularza screeningu**
  (sekcja „Jeden formularz screeningu”). Odczyt (`/note/read`,
  `/note/read-file`) NIC nie zapisuje — wypełnia pola formularza w miejscu,
  a notatka zapisuje się razem z „Zapisz”. `/note/apply` i okno przeglądu
  usunięte. Pliku nie zapisujemy (D1) — jego tekst trafia do historii jako
  zwykła notatka (rodzaj `human`, NIE `card`: projekcja kart 0413 wpisałaby do
  karty pola, których rekruter nie przyjął).
- **Najpierw reguła wzoru, potem Luna** (`AIFeatureKey.recommendation_card_note_read`,
  F28). Pole z reguły wygrywa. Narodowość czyta WYŁĄCZNIE reguła; model dostaje
  tekst po `redact_card_text` i `strip_contacts`. Wartość bez dosłownego cytatu
  odpada; stawka musi mieć swoją liczbę w cytacie.
- **`phrase_guard` odrzuca zdanie z nowym faktem** — liczba, miesiąc, słowo
  wielką literą w środku zdania albo z `+`/`#`/cyfrą spoza haseł i pytania
  (odmiana tolerowana po wspólnym rdzeniu). Fałszywy alarm („w 12” →
  „grudniu”) jest świadomy: rekruter zostawia hasła albo poprawia. Nie luzuj
  reguły bez pomiaru.
- **Odpowiedzi z notatki trafiają do arkusza screeningu (D2)** — świadome
  odstępstwo od 0413, bo zatwierdza je człowiek. Najnowszy wiersz etapu pary,
  arkusz bazowy z `_latest_filled_screening`, tylko pytania z profilu Championa.
  `ScreeningAnswerItem.origin` += `note_import`, `phrased`; `keywords` = hasła
  rekrutera, poza białą listą `client_safe_screening` (klient widzi samo zdanie).
- **Pola karty pamiętają pochodzenie** (`manual_value(provenance=…)`:
  `origin` `note_ai`/`note_rule`/`phrased`, `keywords`, `note_id`). Zwykła
  edycja zapisuje pole bez pochodzenia. `PUT` karty przyjmuje `origins` tylko
  dla pól opisowych (`PHRASABLE_FIELDS`, D4). Skutki zapisu pól (dziennik,
  zmiana stawki 0418, „Stawka od”) idą jedną funkcją `after_card_save`.
- **Język zdań = język CV klienta (D3)** — `phrase_language`
  (`resolve_client_rule`, przy 503 polski), przełącznik PL/EN w oknie i nad
  arkuszem. `AIFeatureKey.screening_answer_phrasing` (F29).
- Odczyt notatki nie jest już blokowany przy niezapisanych zmianach — od 0424
  wypełnia tylko puste pola formularza, a przy pełnych proponuje „Użyj”.
- **Jedna notatka wypełnia formularz (D3, 14.10.2026).** Gdy formularz screeningu osoby jest otwarty po
  „Rozwiń” i przyjmuje notatkę (ten sam warunek co pasek „Uzupełnij z notatki”: włączona funkcja i prawo
  zapisu), pole notatki w doku ma drugi przycisk „Zapisz notatkę i wypełnij formularz” (Enter dalej tylko
  dodaje notatkę). Notatka zapisuje się zwykłą drogą (`POST /api/notes`), dok przekazuje jej numer i treść
  formularzowi kanałem `lib/note-fill-channel.ts`, a formularz czyta ją trasą `/note/read` i wypełnia puste
  pola jak przy wklejeniu. Zapis formularza odsyła `note_import.note_id`: serwer wiąże wersję i pochodzenie
  pól z tą notatką i NIE zakłada drugiej (`screening_form._reused_note`). Notatkę przyjmuje tylko z tej
  samej pary, autorstwa zapisującego, nieusuniętą u źródła i rodzaju z `NOTE_REUSE_KINDS` (`human`,
  `screening_facts`, `card` — reguła rodzajów robi z notatki z rozmowy także te dwa; sama `human` zamykałaby
  drogę dla „Stawka 150, od listopada…”); inaczej 422 `SCREENING_FORM_INVALID` przed jakimkolwiek zapisem.
  Treść i rodzaj notatki z doku zostają, jakie były. Porażka odczytu: formularz pokazuje powód, dok mówi, że
  notatka jest zapisana, a formularza nie wypełnił. Formularz z niezapisanym wypełnieniem z innej notatki
  drugiej nie przyjmuje.
