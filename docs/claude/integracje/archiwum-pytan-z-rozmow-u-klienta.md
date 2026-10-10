# Archiwum pytań z rozmów u klienta (0383, 25.09.2026)

Excel rekruterów „Pytania z interview” (28 arkuszy = klienci, 432 wpisy; Nordea
197) wchodzi do banku `interview_questions` ze źródłem **`legacy_import`**,
skryptem `backend/scripts/import_legacy_interview_questions.py`: przebieg
próbny `--xlsx … --plan … --review …` (GPT-6 Luna, `AIFeatureKey.interview_question_import`,
F25; nic nie zapisuje) → przegląd arkusza przez człowieka → `--apply plan.json`
(idempotentny, paragon `app_settings['legacy_interview_questions_import']`) /
`--rollback`. Decyzje Artura: arkusz „Wszystkie” pominięty, SANTANDER → klient
103 (ERSTE). Excel zostaje poza repo (nazwiska).

- **Archiwum nigdy nie jest „najnowszymi N pytaniami klienta”.** Listy
  „ostatnie 15/20” (prep-kit `client_debrief`, `prep_review`, Luna na
  `/jobs/new` `debrief_questions`, `GET /interview-cycle/client-questions`,
  historia klienta) czytają WYŁĄCZNIE `client_debrief` — surowy import dałby
  każdemu prepowi Nordei ocenę „słaby” (ocena bierze 20 najnowszych pytań
  klienta bez filtra roli). Nowy czytelnik typu „najnowsze N” = filtr po
  `client_debrief`, nigdy po samym kliencie.
- **Archiwum dociera po roli:** `services/client_question_archive.py`
  (tagi `@>` + `mentioned_technologies` ∩ wymagania roli, limit PO
  filtrze; pytanie bez technologii tu nie wchodzi) oraz przypięcie do starej
  rekrutacji źródłowej (numer z nazwy roli albo jednoznaczny tytuł) → tiery 1/2
  prep-kitu, etykieta `client_archive`, a każdy kubełek fallbacku dokłada
  najwyżej tyle pytań, ile brakuje do `target_count` (`_take_missing`).
- **Ocena prepu nie czyta archiwum** — pytanie z archiwum liczy się dopiero
  po przypięciu przez człowieka. Kopia rekrutacji z szablonu nie kopiuje
  przypięć z archiwum. Baza pytań ukrywa je bez `include_archive=true`.
- **Wzorzec taksonomii (`scoring_service._alias_pattern`) oddaje tylko
  prawdziwe wzmianki technologii** (`is_technology_mention`, opakowanie
  `_AliasPattern`): aliasy 1–2-znakowe mają granicę słowa unikodową,
  jednoliterowe i polskie słowa („jest”, „go”) — wielką literę. Dłuższe nazwy
  CELOWO zostają przy granicy ASCII: odmiana „websocketów”, „Elasticsearchów”
  to prawdziwa technologia. Zmierzone 25.09 na produkcji: surowe CV dawało
  fałszywe R 15 773 ×, C 9 398 ×, Jest 4 154 ×, Go 1 753 × (scoring czyta surowe
  CV u 937 kandydatów, zmiana u 379); wymagania ofert — 0 zmian. Jedna reguła
  dla wymagań z prozy, surowego CV i prep-kitu — nie dokładaj filtra obok.
- Pytanie z archiwum zadane znowu w debriefie przechodzi na `client_debrief`
  (`_save_client_questions`). Panel Championa ma zwiniętą sekcję „Z archiwum
  rozmów (podobne role)” (`GET /api/interview-cycle/client-questions/archive`).
