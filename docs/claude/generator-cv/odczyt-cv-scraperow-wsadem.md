# CV ze scraperów do istniejących profili czytamy wsadem (22.11.2026)

<!-- indeks: cv_parse_batch, cv_parse_batch_items, Message Batches API, CV_PARSER_BATCH_ENABLED, CV_PARSER_BATCH_FALLBACK_HOURS, cv_read_queued_at, „Czytamy nowe CV z portalu” -->

Decyzja Artura z 22.11.2026, po pomiarze z PR #3683
(`odczyty-parsera-cv-konto-scraperow.md`). Konto scraperów pracuj.pl i JJIT
robi 86% odczytów parsera CV i nikt nie czeka na ich wynik, więc idą przez
Message Batches API za pół ceny. Ręczne „Wczytaj CV” i wgrania przez ludzi
zostają natychmiastowe.

- **Wsad obejmuje tylko `POST /api/candidates/{id}/cv` z tokenem integracji**
  (`candidate_claim.is_integration_request`). To wgrania nowej wersji CV do
  istniejącego profilu, ok. 1708 odczytów w 03–22.11. **`/from-cv` zostaje na
  żywo** (wybór Artura 22.11): duplikat po e-mailu z CV oraz po telefonie
  z imieniem i nazwiskiem trzeba sprawdzić przed założeniem profilu, a scraper
  po 201 od razu kładzie kartę w rekrutacji. Zakładki „Pliki”, „Ponów odczyt”,
  poczta M365 i API v1 też czytają na żywo.
- **Przebieg.** Wgranie robi te same sprawdzenia co dotąd: plik już odczytany,
  kopia z kwarantanny, wyciągnięcie tekstu. Zamiast modelu wstawia wiersz
  `cv_parse_batch_items` z tekstem CV. Pętla `cv_parse_batch` (worker, co
  `CV_PARSER_BATCH_TICK_SECONDS`) wysyła zebrane CV jedną paczką, odbiera
  wynik zakończonej paczki i zapisuje go tą samą ścieżką co odczyt na żywo
  (`_apply_document_read`: bramka tożsamości, `finish_cv_ingest` z REFRESH).
  Przed zapisem sprawdza drugi raz, czy plik jest dalej głównym CV z tym samym
  skrótem i czy nie jest kopią z kwarantanny.
- **Awaria nie gubi odczytu.** Odczyt na żywo (status `fallback`, potem `live`,
  powód w `error`) dostają: błąd utworzenia paczki, wynik `errored`/`canceled`/
  `expired`, brak wyniku, niepoprawny JSON, błąd zapisu i CV bez wyniku po
  `CV_PARSER_BATCH_FALLBACK_HOURS` (domyślnie 6 h, API daje paczce do 24 h).
  Paczka, w której nic już nie czeka, jest anulowana. Pętla czyta najwyżej
  20 CV na żywo na tick. Status `live` dostają dopiero po odczycie, więc
  proces zabity w trakcie czyta je jeszcze raz. Odczyt na żywo, który padł
  wyjątkiem (zadanie zwraca `False`), wraca najwyżej 3 razy (`live_attempts`),
  potem `live` z powodem `live_failed`.
- **Wynik opłaconej paczki wygrywa z limitem czasu.** Tick najpierw odbiera
  wyniki, potem liczy limit, a paczka zakończona (`ended`), której wyników nie
  udało się pobrać, w limit nie wpada. Twardy koniec to 25 h: API trzyma
  paczkę najwyżej 24 h. Paczka ma najwyżej 100 CV, bo paczka zgubiona między
  API a bazą (zerwana odpowiedź, padnięty commit) oznacza płatny odczyt
  drugi raz.
- **Nowsze CV i odczyt przez człowieka zamykają wiersz** (`superseded`). Wynik
  dla pliku, który przestał być głównym CV, niczego nie zapisuje
  (`done` + `not_applied`).
- **Model z rejestru** (`cv_parser`, dziś Sonnet 5.5). Treść żądania to
  `claude_cv_request_params` po `claude_client.batch_request_params`, czyli ta
  sama translacja co na żywo: Sonnet 5.5 odrzuca `thinking: disabled` kodem
  400 także w paczce. Koszt liczy `record_batch_message_usage` w
  `ai_feature(cv_parser)` z wyceną −50%. Model parsera u innego dostawcy niż
  Anthropic, `CV_ENRICHMENT_ENABLED=false` albo `CV_PARSER_BATCH_ENABLED=false`
  oznaczają odczyt na żywo jak przed zmianą. CV już czekające w kolejce
  pętla czyta wtedy na żywo.
- **Do wyniku profil ma dane z poprzedniego CV.** `GET /api/candidates/{id}`
  podaje `cv_read_queued_at`, a sekcja CV w profilu pokazuje „Czytamy nowe CV
  z portalu…” (`getCvProjectionNotice`, rodzaj `queued`) zamiast „Ponów
  odczyt”. Lista kandydatów tego pola nie liczy.
- **Tekst CV leży w wierszu tylko do zamknięcia** (`raw_text` czyszczony).
  Zamknięte wiersze zostają 60 dni do pomiaru udziału wsadu, potem znikają.
- **Staging:** pętla stoi (`STAGING_BLOCKED_TASKS`), bo kopia produkcji z CV
  scraperów oznaczałaby płatne odczyty drugi raz.
- **Pomiar po wdrożeniu** (`prod_readonly.py`): udział
  `cv_parse_batch_items.status = 'done'` w odczytach konta scraperów oraz CV
  z kolejki bez zamknięcia po 24 h (ma być 0):
  `SELECT status, error, count(*) FROM cv_parse_batch_items WHERE queued_at > now() - interval '7 days' GROUP BY 1, 2;`
  i `SELECT count(*) FROM cv_parse_batch_items WHERE status IN ('queued','submitted','fallback') AND queued_at < now() - interval '24 hours';`.
