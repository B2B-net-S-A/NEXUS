# Asystent prawny — fundament: korpus prawa, weryfikator cytatów, znaczniki, terminy, szkic pisma
<!-- indeks: asystent prawny, legal, /api/legal, korpus prawa, legal_acts, legal_act_versions, legal_provisions, nexus_legal_corpus, ELI, tekst jednolity, EUR-Lex, CELLAR, SPARQL, weryfikator cytatów, citations, pseudonimizacja, znaczniki [PARTNER], terminy art. 111–116 KC, na koniec miesiąca, od kolejnego miesiąca, legal_assistant F57, LEGAL_CORPUS_REFRESH_ENABLED, LEGAL_CORPUS_EMBEDDINGS_ENABLED, legal_corpus_seed -->

Decyzje Artura z 25.11.2026: asystent prawny do umów B2B działa **w tle
istniejących ekranów** (kontrakty, Generator, Jarvis, Przepisy), bez trasy
`/legal` we froncie. Plan, części A–H i kontrakt: `docs/asystent-prawny-plan.md`.
Ten plik opisuje część A (pakiet `backend/app/services/legal/`, migracja 0784).

## Decyzje, które łatwo cofnąć „przy okazji”

- **Nic nie wychodzi samo.** `assistant.draft` zwraca szkic; nie zapisuje
  i nie wysyła. Pismo idzie oknem maila NEXUSA albo jako DOCX do Dokumentów
  kontraktu po „Zatwierdzam” człowieka (części D–F).
- **Każdy cytat sprawdza kod** (`citations.verify`) z tekstem źródła; cytat
  bez pokrycia (`missing`, `mismatch`) ustawia `blocked` i blokuje zatwierdzenie.
  Po przeglądzie 25.11: jednostka nadrzędna pokrywa podjednostkę tylko, gdy
  źródło jej nie dzieli i w jej tekście stoi ślad podjednostki („§ 7”, „8.”,
  „2)”) — „art. 111 § 7 KC” przy § 1–6 i „§ 9 ust. 8 Umowy” bez ust. 8 to
  `missing` (korpus: `get_provision(nearest_parent=True)` nie oddaje artykułu
  z podziałem). „umowy ramowej” czyta tylko fragmenty `client`, „Umowy” —
  `contract`, „wzoru” — `template` (`citations.document_kinds`). Kawałki
  cytatu przy „(…)” mają ≥ 3 wyrazy albo ≥ 15 znaków, w granicach słów
  i w kolejności — „Klient (…) kara umowna (…) przekracza” nie przeskoczy „nie”.
- **Terminy, daty, kwoty liczy kod** (`deadlines`), model dostaje je jako
  znaczniki (`[DATA_ROZWIAZANIA]`). Data, kwota albo „14 dni” wpisane przez
  model to `issues` i `blocked` (`assistant.code_issues`).
- **Dane osób do modelu tylko jako znaczniki** (`pseudonymize.mask`), podmiana
  z powrotem po stronie NEXUSA. Bez tego PESEL, NIP, e-mail, telefon i rachunek
  i tak są wyłapywane automatem (cyfra kontrolna PESEL i NIP).
- **LEX i Gofin nigdy do modelu** (licencje): fragment z adresem `lex.pl`
  albo `gofin.pl` odpada w `assistant.allowed_passages` (także z portem,
  zapytaniem i fragmentem: `sip.lex.pl:443/x`, `gofin.pl#x`).
- **Próg do prawnika:** kara umowna, spór z klientem, rozwiązanie ze skutkiem
  natychmiastowym → `lawyer_review` (etykieta w UI). Odpowiedź `/draft` niesie
  `disclaimer`: szkic nie jest poradą prawną.

## Korpus prawa

- **Akty** w `services/legal/acts.py` (klucz jest kontraktem dla części B–H):
  `kc`, `kp`, `pr_aut`, `pip`, `min_wynagrodzenie`, `zatory`, `pit`, `ksh`,
  `kpc`, `sus`, `odo`, `znk`, `prawo_przedsiebiorcow` (ELI) oraz `rodo`,
  `dora`, `ai_act` (EUR-Lex). Identyfikatory sprawdzone w API 25.11.2026.
- **ELI:** najnowszy tekst jednolity z `references["Inf. o tekście
  jednolitym"]` aktu, **po roku i pozycji, nie po kolejności listy** (25.11.2026
  pierwszy na liście PIP był `DU/2024/97`, a najnowszy `DU/2024/1712`). **Tekst HTML samego aktu to brzmienie
  pierwotne** (KC z 1964 r.: art. 61 bez § 2) — nie używać. Tekst jednolity ma
  HTML (5 z 13 aktów) albo tylko PDF typu `T` (8 z 13: KC, KP, PIT, KPC…).
  `valid_from` = `legalStatusDate`. Zmiany ogłoszone po tej dacie (`Akty
  zmieniające`) trafiają do `meta.amendments_after`: tekst jednolity ich nie
  obejmuje i ekran ma to powiedzieć.
- **EUR-Lex:** `eur-lex.europa.eu` odpowiada automatom 202 z pustą treścią
  (WAF), więc tekst idzie z CELLAR (`publications.europa.eu/resource/celex/…`,
  XHTML po polsku), a najnowsza wersja skonsolidowana z SPARQL
  (`0<CELEX>-<RRRRMMDD>`). Link dla ludzi zostaje do EUR-Lex.
- **Podział** (`parse.py`): linie z trzech formatów → jedna maszyna stanów
  (art. → § albo ust. → pkt → lit.). PDF: treść 10 pt, przypisy 9 pt
  (odpadają po rozmiarze), indeks górny wychodzi jako `[1]` → „442¹”, klucz
  `442^1`. Numer spoza kolejności („2.” w zawiniętej linii) zostaje tekstem.
  Obwieszczenie i załączniki odpadają. Tiret nie jest jednostką (dokleja się
  do punktu).
- **PDF czyta osobny proces** (`pdf_worker`, limit 300 s i 2 GB), bo
  `pdfplumber` na KC to ok. 7,5 s czystego Pythona i w wątku trzymałby GIL
  pętli workera.
- **Wersje i zdarzenie dla Przepisów (część H):** nowy tekst = nowy wiersz
  `legal_act_versions` z `previous_version_id` i `changes` (oznaczenia
  dodane, usunięte, zmienione); poprzednia dostaje `valid_to` = dzień przed
  nową. Czyta to `corpus.changes_since(db, since)`; osobnej tabeli zdarzeń nie ma.
- **Wyszukiwanie:** `search_vector` (FTS `simple` na tekście bez polskich
  znaków, kolumna generowana) + wektory Voyage w Qdrancie `nexus_legal_corpus`
  (id punktu = id przepisu, w payloadzie tylko `act_id` i `version_id`),
  łączone RRF jak umowy ramowe. Ranking po słowach pomija jednostki dłuższe
  niż 20 tys. znaków (`KEYWORD_MAX_CHARS`; art. 21 ustawy o PIT ma 120 tys.
  i pasował do każdego pytania) — ich ustępy i punkty są w korpusie osobno. Wektor mają artykuły, § i ustępy; pkt i lit.
  znajduje FTS albo jednostka nadrzędna. Odwołanie w pytaniu („art. 61 § 1
  KC”) trafia na pierwsze miejsce. Wyłącznik wektorów:
  `LEGAL_CORPUS_EMBEDDINGS_ENABLED` (teksty są publiczne).
- **Odświeżanie:** pętla `legal_corpus` w workerze co godzinę bierze akty
  sprawdzone ponad 20 h temu (nieudane po 2 h); pierwszy bieg po wdrożeniu
  zasila cały korpus. Wyłącznik `LEGAL_CORPUS_REFRESH_ENABLED` (domyślnie
  włączony). Na stagingu pętla stoi (`STAGING_BLOCKED_TASKS`), korpus zasila
  `python -m scripts.legal_corpus_seed [--acts kc,kp] [--force]` z
  `STAGING_EXTRA_ALLOWED_HOSTS=api.sejm.gov.pl,publications.europa.eu`.

## Kontrakt dla części B–H

- `corpus.search_provisions(db, query, *, acts=None, on_date=None, limit=8)`
  → `ProvisionHit`; `corpus.search` niesie też `retrieval`
  (`hybrid` | `keywords` | `none`).
- `corpus.get_provision(db, act_key, ref, *, on_date=None, nearest_parent=False)`;
  dzień sprzed najstarszej wersji = najstarsza z `exact_date=False`.
- `SourcePassage(kind, ref, text, url, label, act_key)`; `kind`: `law`,
  `contract`, `client`, `template`, `case`; `corpus.as_passage(hit)`.
- `citations.extract(text)`, `citations.verify(text, passages)`,
  `corpus.verify_text(db, text, passages, *, on_date=None)` (przepisy dobiera
  z korpusu sam), `citations.blocking(checks)`.
- `pseudonymize.mask(text, entities)` → `(masked, mapping)`, `unmask`,
  `unknown_tokens`; `Entity(label, value, inflect=False)`.
- `deadlines.term_end`, `notice_end_of_month` (miesiąc doręczenia nie wchodzi
  do okresu, także przy doręczeniu 1. dnia), `notice_days_end_of_month`,
  `from_next_month`, `next_working_day` (art. 115 tylko dla terminu na
  czynność, nie dla dnia końca umowy).
- `assistant.draft(db, *, kind, instruction, passages, entities, user_id=None,
  on_date=None)` → `Draft(text, citations, checks, blocked, passages, issues,
  lawyer_review, model, error)`. Bez modelu: pusty tekst, fragmenty źródeł
  i `error`.

## Funkcja AI

`legal_assistant` (F57; F19–F22 z planu były już zajęte w rejestrze) —
Sonnet 5.5 z zapasem Sonnet 5, jak tekst do osoby spoza firmy w F46/F54
i najmniej zdań bez pokrycia w pomiarze F50. Bez osobnego pomiaru; zmiana po
pomiarze na modelu z produkcji. Wywołanie w `ai_feature()`, env
`LEGAL_ASSISTANT_MODEL`. Prompt: `llm_prompts.LEGAL_ASSISTANT_DRAFT`.

## Uprawnienia

Trasy `/api/legal` stoją za sekcją Sourcing i `B2BGeneratorAccess` — jak
`/api/b2b-generator/documents`. Asystent działa w tle Generatora i ekranów
kontraktu, a każdy, kto pracuje na kontrakcie (DL z klientami, Back office,
Finanse, admin), ma Generator. Trasy nie czytają żadnego kontraktu: fragmenty
umów podaje ekran, który przeszedł własną bramkę (`LegalDocsReader`,
Dokumenty kontraktu). `/draft` wymaga poziomu „generowanie” Generatora
(`require_legal_draft`) i zapisu w Sourcing, limit 20/min; `/verify` jest
odczytem (`READ_ONLY_POST_ROUTE_TEMPLATES`). Wzorzec:
`tests/data/authz_golden/legal.json` (odmowa: Pracownik, Rada, Automatyzacje,
`user`, praktykant).

## Staging 25.11.2026 (port 8111, kopia `nexus_branch_ap_fundament`, usunięta)

Zasilenie z ELI i CELLAR: 16 z 16 aktów, 27 191 jednostek, 19 267 wektorów,
11 min. Wyszukiwanie „wypowiedzenie umowy forma” → KC art. 77 § 1–3, KP
art. 30 (`hybrid`); „art. 61 § 1 KC” w `/verify`: cytat dosłowny `ok`,
zmieniony `mismatch`. `/draft` na Sonnecie 5.5: trzy odwołania `ok`, dane
osoby i daty tylko jako znaczniki. Rada: 403, bez tokenu: 401.
