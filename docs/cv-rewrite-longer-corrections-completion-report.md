# Dłuższe poprawki do CV — „Co poprawić?” i asystent edytora (15.10.2026)

Prośba rekrutera: pole poprawek do wygenerowanego CV ma przyjmować więcej
tekstu. Makiety: https://claude.ai/artifact/TTR2H3eYv186tZ9rycvgiD (wariant A,
decyzje D1–D5). Artur 15.10.2026: „zgodnie z twoimi rekomendacjami”.
Reguła: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`, sekcja
„„Napisz od nowa””, punkt „Lista poprawek do 2000 znaków”.

## Co było nie tak

- Pole „Co poprawić?” w karcie „CV do klienta” i polecenie asystenta
  w edytorze miały 300 znaków w przeglądarce i na serwerze.
- Dłuższa wklejka ucinała się po cichu (`maxLength`). Na produkcji 1 z 3
  uwag „Uwaga do CV” z 15.10 ma dokładnie 300 znaków.
- Lista punktów sklejała się w jedno zdanie: pole miało jedną linię,
  a serwer (`recruiter_instruction`) i tak łączył tekst w jedną linię.
- Enter od razu pisał CV od nowa — listy nie dało się wpisać linia po linii.
- Asystent robi naraz najwyżej 40 zmian; nadmiar przepadał bez słowa.

## Co weszło

- **Limit 2000 znaków** w obu polach, po obu stronach
  (`INSTRUCTION_MAX`, `cv_command_ai.COMMAND_MAX`, `REWRITE_MAX`,
  `CV_COMMAND_MAX`). Bez migracji bazy.
- **Lista zostaje listą.** `recruiter_instruction` zwija spacje w każdej
  linii, wycina puste linie i stawki (linia po linii), ale nie skleja linii.
  Do modelu trafia ogrodzone `<recruiter_instruction>` z punktami; prompt
  systemowy legacy_v7 bez zmian. Notatka: „Uwaga do CV:” + nowa linia + lista.
- **Karta: `CvRewriteForm`.** Pole rośnie od 1 do 8 linii, dalej przewija się
  w środku (`lib/use-textarea-autogrow.ts` — ten sam rachunek co
  `MentionTextarea`, który został nietknięty). Enter = nowa linia,
  Ctrl/⌘+Enter = „Napisz od nowa”. Podpowiedź klawiszy pod polem.
- **Nic nie ucina się po cichu.** Bez `maxLength`; `TextLimitCounter` od
  1600 znaków, ponad limitem „… — skróć o N” na czerwono i nieaktywny
  przycisk.
- **Szkic listy** w `sessionStorage` (`lib/cv-rewrite-drafts.ts`, per osoba
  i wiersz etapu), kasowany przy wylogowaniu (`clearSessionArtifacts`).
  „Anuluj” w panelu generacji oddaje listę do pola.
- **Panel generacji** pokazuje długą listę zwiniętą do 3 linii
  z „Pokaż całość” / „Zwiń”.
- **Asystent edytora.** Pole rośnie od 2 do 4 linii, licznik, podpowiedź
  „Enter wyślij · Shift+Enter nowa linia”, przycisk nieaktywny ponad limitem.
  Trasa `cv-ai/command` zwraca `truncated`, gdy model zaproponował ponad 40
  zmian, a odpowiedź dopisuje: „Lista miała więcej zmian, niż asystent robi
  naraz (40) — sprawdź, czego brakuje, i dopisz to w kolejnej wiadomości.”

## Świadomie inaczej niż makieta

- Pole asystenta rośnie do 4 linii, nie 8. Zmierzone w harnessie
  `/preview/cv-editor`: przy 1280 × 650 pole na 5 linii zostawiało rozmowie
  21 px, na 4 linie — 41 px (przy 1280 × 720: 63–85 px). Po wysłaniu pole
  wraca do 2 linii, więc rozmowa odzyskuje miejsce.
- Opcja B („Powiększ”) nie weszła — decyzja Artura.

## Sprawdzone

- Backend bez bazy (Python 3.12): `test_cv_generator_legacy_v7.py`,
  `test_cv_command_ai.py` — 175 zielonych; nowe testy padały przed zmianą
  (lista sklejana, brak `truncated`). Testy tras z bazą — CI.
- Front: 476 testów w zmienionych plikach (karta, asystent, harnessy,
  szkic, sesja, hook, inwentarz), `npm run type-check`, eslint.
- Harness `/preview/cv-to-client` (1280 × 720, wbudowana przeglądarka):
  pusty stan w jednej linii; lista z Enterami rośnie do 174 px (8 linii)
  i przewija się; Ctrl+Enter → generacja → pasek „Nowa wersja CV”; panel
  pokazuje listę zwiniętą do 3 linii z „Pokaż całość”; 2351 znaków →
  czerwona ramka, „skróć o 351”, przycisk nieaktywny, tekst cały; szkic
  przeżywa przeładowanie strony.
- Harness `/preview/cv-editor`: pole asystenta 2 → 4 linie, licznik
  „1671 / 2000 znaków”, wymiary rozmowy jak wyżej.

## Niepotwierdzone

- Jak model legacy_v7 radzi sobie z długą listą (15–20 punktów) na
  prawdziwym CV — prompt bez zmian, sprawdzić na produkcji po wdrożeniu.
- Wdrożenie: tylko w oknie 19:00–07:00; potem `/api/health` = SHA z maina
  i przeklikanie karty na produkcji.
