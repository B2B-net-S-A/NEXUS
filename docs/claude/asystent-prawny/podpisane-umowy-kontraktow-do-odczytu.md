# Podpisane umowy kontraktów do odczytu (część E, 0789, 25.11.2026)
<!-- indeks: treść umowy, aneksu, wypowiedzenia i porozumienia z Dokumentów kontraktu, `contract_document_chunks`, Qdrant `nexus_contract_documents`, `termination_terms`, narzędzia Jarvisa `search_contract_documents` / `read_contract_document`, źródła z NEXUSA w ramce Jarvisa -->

Plan: `docs/asystent-prawny-plan.md` (część E). W obiegu są umowy z różnych
wersji wzoru: umowa z 2025 r. liczy wypowiedzenie „od kolejnego miesiąca”
i wymaga formy pisemnej z doręczeniem osobiście albo pocztą, dzisiejszy wzór
(`templates/contract/umowa_b2b_pl.html` § 12) liczy „na koniec miesiąca
kalendarzowego” i dopuszcza mail. **Asystent, Jarvis i pismo na kontrakcie
(część F) czytają PODPISANĄ umowę z Dokumentów kontraktu, nigdy wzoru.**

## Co jest czytane

- Dokumenty kontraktu typu `contract`, `annex`, `termination_notice`,
  `termination_agreement` (`index.READ_TYPES`). Zaświadczenia, polisy, NIP,
  NDA i zamówienia nie są treścią umowy z Partnerem.
- Tekst z PDF i DOCX przez `cv_text_extractor` (PDF w piaskownicy z OCR stron
  bez tekstu, `extract_pdf_all_pages_sandboxed`), tymi samymi funkcjami co
  umowy ramowe klientów (`framework_contract_index._read_file`, `_embed`).
- **Tekst tylko w Postgresie** (`contract_document_chunks`, ciągłe wycinki —
  sklejone dają cały tekst). W Qdrancie `nexus_contract_documents` same
  wektory: id punktu = id fragmentu, payload `contract_document_id`,
  `contract_id`, `chunk_index`, bez tekstu. Nazwa kolekcji nie zaczyna się
  od `nexus_candidates` (kasowanie wektora kandydata po id skasowałoby
  fragment o tym samym numerze).
- Stan odczytu w `contract_documents.text_*`; zapis stanu nie rusza
  `updated_at`. Bez Voyage albo Qdranta stan `text_only` i ranking po słowach.

## Kiedy powstaje treść

- Po wgraniu pliku (`upload_contract_document` → commit → odczyt w tle).
- Leniwie przy pierwszym pytaniu (`ensure_indexed`, czeka do 30 s, potem bieg
  trwa w tle) — obejmuje też pliki z SharePointa, Generatora i zmianę typu
  dokumentu w zakładce Dokumenty.
- Istniejące dokumenty: `python -m scripts.backfill_contract_document_text
  --dry-run | --commit [--limit N] [--after-id ID] [--client-id ID]`.
  Wznowienie samo z siebie (dokument z aktualnym stanem odpada z zakresu).
  Bez pętli w tle.
- Usunięcie dokumentu kasuje fragmenty kaskadą, a punkty w Qdrancie zadanie
  po commicie.

## Okres wypowiedzenia słownie

`termination._number` czyta liczebniki z „-naście”/„-dzieści” i pary
„dwudziestu jeden” („czternastu dni” → 14, „dwunastu miesięcy” → 12); do
25.11 takie zapisy dawały brak okresu albo pierwszą cyfrę („czternastu” → 4).
Liczba w nawiasie („trzydziestu (30) dni”) nie przerywa dopasowania.

## Wektory z pełnego tekstu (decyzja Artura 25.11.2026)

Fragment umowy idzie do Voyage (embedding) w pełnym brzmieniu, tak jak umowy
klientów — Artur rozszerzył zgodę z 09.10 na umowy z Partnerami (wybrał to
zamiast wariantu ze znacznikami). Ten sam tekst zostaje w Postgresie
(`contract_document_chunks`). Nie dokładaj maski „przy okazji” — to zmiana
decyzji, nie poprawka. Test: `tests/test_contract_document_text_embed.py`.

## Usługa (`services/contract_document_text/service.py`)

- `search_contract_documents(db, contract_id, query)`, `read_contract_document(db,
  document, from_chunk)` — cytaty jako `SourcePassage(kind="contract", ref=…)`,
  np. `ref="umowa 12/2025 § 8 ust. 2"` (numer z nagłówka dokumentu, inaczej
  nazwa pliku; paragraf i ustęp z układu tekstu, `structure.py`).
  `SourcePassage` jest lokalną kopią kształtu z części A — do podmiany na
  `app.services.legal.SourcePassage` po scaleniu fundamentu (TODO w kodzie).
- `termination_terms(db, contract_id)` — okres (`end_of_month`,
  `from_next_month`, `days`), forma (`written`, `documentary`,
  `electronic`, rygor nieważności) i doręczenie (`in_person`, `post`,
  `email`) **regułami i wzorcami tekstu, bez modelu** (`termination.py`).
  Umowa = najnowszy plik „umowa” z sekcji „Aktualna umowa”, PDF przed DOCX;
  aneks z tej sekcji z własnym zapisem o wypowiedzeniu wygrywa. Niepewność
  daje `terms=None` z powodem: kilka różnych okresów (np. inny w okresie
  próbnym), okres w miesiącach bez sposobu liczenia, oba sposoby naraz,
  brak zapisu, brak treści. Termin policzy wtedy człowiek — nie zgadujemy.
  Brak zapisu o formie albo doręczeniu to `notes`, nie domysł.
- Pomiar 25.11.2026 na kopii stagingu, klient z największą liczbą kontraktów
  (332): reguła dla 291, w tym 116 × „koniec miesiąca” z mailem (dzisiejszy
  wzór) i ok. 160 × „od kolejnego miesiąca” 1–3 mies. bez maila (starsze
  wzory). `None`: 14 bez pliku umowy w „Aktualnej umowie”, 13 bez zapisu
  w treści (część to inny dokument oznaczony jako umowa albo tekst z ubytkami
  słów z PDF-u), 10 bez pliku na dysku, 3 okres bez sposobu liczenia, 1 kilka
  okresów. Tryby wyliczone w jednym zdaniu („a. … b. … d. w trybie
  natychmiastowym”) są oceniane punkt po punkcie.

## Dostęp

- Bramka = pobranie pliku dokumentu kontraktu: sekcja Delivery, „Stawki
  i kwoty: podgląd” (`AmountsViewUser`) i `_assert_contract_document_client_access`
  (Delivery Lead tylko u klienta z przypisania). Treść umowy niesie stawki.
- Trasy: `GET /api/contracts/{id}/documents/search?q=`,
  `GET /api/contracts/{id}/documents/termination-terms`,
  `GET /api/contract-documents/{document_id}/text?from_chunk=`. Wzorzec
  bramek: `tests/data/authz_golden/contract_document_text.json` (te same
  litery co `…/documents/{document_id}/download`).

## Jarvis

- Narzędzia `search_contract_documents` i `read_contract_document`
  (`any_permission=("amounts_view",)`, poza `WEB_SAFE_TOOLS`), własny `shape`
  bez przycinania tekstu — limit znaków pilnuje serwer (`PASSAGE_BUDGET`).
  Instrukcja w sekcji „UMOWY Z KLIENTAMI” promptu: zapis z umowy, z `ref`,
  nigdy ze wzoru.
- Ramka źródeł (`JarvisSources.tsx`) ma dwie grupy: „Źródła z NEXUSA”
  (dokument kontraktu, umowa ramowa klienta) i „Źródła z internetu”. Źródło
  NEXUSA buduje backend z identyfikatorów w wyniku narzędzia
  (`jarvis/nexus_sources.py`), front przyjmuje wyłącznie ścieżkę aplikacji
  (`isNexusPath`); idzie przy ostatniej wiadomości tury i zostaje w historii.

## Testy

`tests/test_contract_document_text_embed.py` (pełny tekst do Voyage),
`tests/test_contract_document_termination.py` (obie generacje wzoru,
niepewności, odnośniki), `tests/test_contract_document_text_api.py` (bramki,
odmowy, źródła Jarvisa, narzędzia), `src/components/jarvis/__tests__/JarvisSources.test.tsx`.
