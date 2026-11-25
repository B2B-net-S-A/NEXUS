# Asystent prawny — plan budowy (25.11.2026)

Jeden PR z gałęzi `claude/asystent-prawny`, budowany w kilku sesjach. Każda
sesja pracuje na własnej gałęzi `claude/asystent-prawny-<część>` (od tej
gałęzi), commituje i pushuje, **bez własnego PR-a i bez scalania** — części
scala sesja główna i ona otwiera jedyny PR.

## Decyzje (Artur, 25.11.2026)

1. **Asystent działa w tle, bez osobnego modułu.** Wpięcia w istniejące ekrany:
   lista i strona kontraktu, kreator aneksu i nowej umowy (Generator), zakładka
   Dokumenty Generatora (wzory własne), Jarvis, Przepisy → „Źródła i boty”.
   Trasy `/legal` we froncie nie ma.
2. **Nic nie wychodzi samo.** Pismo idzie przez okno maila NEXUSA albo jako DOCX
   do Dokumentów kontraktu; człowiek zatwierdza („Zatwierdzam”).
3. **Każdy cytat sprawdza kod** z tekstem źródła (przepis, podpisana umowa,
   umowa ramowa klienta, wzór, orzeczenie). Cytat bez pokrycia blokuje
   zatwierdzenie. **Terminy, daty, kwoty słownie i formy Pan/Pani liczy kod**,
   model pisze tylko zdania.
4. **Dane osób do modelu tylko jako znaczniki** (`[PARTNER]`, `[NIP]` …),
   podmiana z powrotem po stronie NEXUSA. Wybrane jako wariant rekomendowany
   i odwracalny (decyzja z 09.10.2026 dotyczy treści umów klientów, nie danych
   osób).
5. **LEX i Gofin nigdy do modelu** (licencje) — tylko link.
6. **Wzory własne** (uwaga zespołu): nowy wzór z asystentem w Generator →
   Dokumenty, zapis w bazie (nie w kodzie), zatwierdza administrator, potem
   widoczny w „Nowy dokument” → „Wzory własne”. Wzór własny tylko tworzy
   dokument; skutki w kontraktach zostają przy typach z rejestru programisty.
7. Asystent nie jest poradą prawną; próg do prawnika: kara umowna, spór
   z klientem, rozwiązanie ze skutkiem natychmiastowym (etykieta w UI).

Makiety (do wglądu, NIE do kopiowania danych): artefakt
https://claude.ai/artifact/Cff1Jn7pZyVcg4G6eyDYX8 oraz lokalny commit
`c39a73f38` na gałęzi `claude/polish-legal-assistant-d2fa28`
(`frontend/src/components/legal-assistant/*`). Makiety mają prawdziwe dane ze
stagingu — **repo i logi Actions są publiczne: w kodzie, testach i opisach
wyłącznie dane fikcyjne.**

## Części

| Część | Gałąź | Migracja | Funkcja AI | Porty (backend/front) |
|---|---|---|---|---|
| A. Fundament: korpus prawa, weryfikator, usługa, API | `-fundament` | `0779_legal_corpus` | `legal_assistant` (F19) | 8111 / 3111 |
| B. Wzory własne | `-wzory` | `0780_custom_document_templates` | `legal_template_draft` (F20) | 8112 / 3112 |
| C. Orzecznictwo i interpretacje | `-orzecznictwo` | `0781_legal_case_law` | — | 8113 / 3113 |
| D. Popraw dokument (DOCX ze śledzeniem zmian) | `-redline` | — | `legal_redline` (F21) | 8114 / 3114 |
| E. Podpisane umowy kontraktów do odczytu | `-umowy-kontraktow` | `0782_contract_document_chunks` | — | 8115 / 3115 |
| F. Pismo na kontrakcie, zadania po wypowiedzeniu, Jarvis | `-pisma` | `0783_legal_letters` | (F19) | 8116 / 3116 |
| G. Zgodność z umową klienta w tle | `-zgodnosc` | `0784_legal_client_fit` | `legal_client_fit` (F22) | 8117 / 3117 |
| H. Przepisy: źródła i „przejrzyj wzór” | `-przepisy` | — | — | 8118 / 3118 |

A–E startują od razu; F–H po scaleniu A i E do `claude/asystent-prawny`.

**Migracje:** każda część ma `down_revision = "0778_b2b_document_preliminary_jdg"`;
sesja główna łańcuchuje je przy scalaniu. DDL z jednego modułu `schema.py`
(wzór: `app/services/law_radar/schema.py`) dla migracji i `entrypoint.sh`
(`hr_schema_bundle`), każda nowa tabela ma sondę w `/api/health/deep`.

**AI:** funkcja w rejestrze `services/ai_models.py` + `AIFeatureKey`, wywołanie
w `ai_feature()`; wynik modelu jest dodatkiem, ścieżka działa bez modelu.
Model na start jak w podobnych funkcjach rejestru (zapisz uzasadnienie);
zmiana modelu po pomiarze, test tylko na modelu z produkcji.

**Uprawnienia:** nowa trasa `/api/**` ma bramkę sekcji albo opisany wyjątek;
w Delivery alias z `api/permission_access.py`; dostęp do treści umów jak
`LegalDocsReader` (pobranie pliku). Diff `tests/data/authz_golden/` w PR-ze.

**Reguły do przeczytania przed kodem:** `CLAUDE.md`, `docs/claude/kontrakty/`
(generator, rejestr, dokumenty), `docs/claude/przepisy/radar-przepisow-dwa-boty.md`,
`docs/claude/ai-jarvis/modele-ai-per-funkcja-…`, `jarvis-czyta-umowy-ramowe-klientow.md`,
`docs/claude/uprawnienia/dziewiec-uprawnien-…`, `docs/claude/podstawy/migracje-zgodne-wstecz.md`,
`healthcheck-endpoint.md`, `staging-na-laptopie.md`, `test-calej-sciezki-na-stagingu.md`,
`docs/claude/ui/design-system-…`, `ui/responsywnosc-…`.

## Kontrakt fundamentu (część A) — z niego korzystają B–H

Pakiet `backend/app/services/legal/`:

- `corpus`: tabele `legal_acts` (klucz `kc`, `kp`, `pr_aut`, `pip`,
  `min_wynagrodzenie`, `zatory`, `pit`, `ksh`, `kpc`, `sus`, `odo`, `znk`,
  `prawo_przedsiebiorcow`, `rodo`, `dora`, `ai_act`; źródło `eli`/`eurlex`),
  `legal_act_versions` (tekst jednolity / wersja skonsolidowana, data
  obowiązywania od–do, adres, skrót treści), `legal_provisions` (jednostka
  redakcyjna: `art. 61 § 1`, tekst, kolejność). Wektory w Qdrancie
  `nexus_legal_corpus` (id punktu = id przepisu, bez tekstu w payloadzie).
- `search_provisions(db, query, *, acts=None, on_date=None, limit=8)`,
  `get_provision(db, act_key, ref, *, on_date=None)`.
- `SourcePassage(kind: law|contract|client|template|case, ref, text, url, label)`.
- `citations.extract(text) -> list[Citation]`,
  `citations.verify(text, passages) -> list[CitationCheck]` (`ok` / `missing`
  / `mismatch`), bez modelu.
- `pseudonymize.mask(text, entities) -> (masked, mapping)`, `unmask(text, mapping)`.
- `deadlines`: liczenie terminów (art. 111–116 KC, „na koniec miesiąca”,
  „od kolejnego miesiąca”) — czyste funkcje.
- `assistant.draft(db, *, kind, instruction, passages, entities) -> Draft`
  (`text`, `citations`, `checks`, `blocked`), funkcja AI `legal_assistant`.
- API (`/api/legal`): `GET /sources` (stan korpusu), `GET /provisions/search`,
  `POST /verify`, `POST /draft`.
- Pobieranie: ELI Sejmu (`api.sejm.gov.pl/eli`) i EUR-Lex, z wersjami;
  odświeżanie w pętli (zablokowana na stagingu w `STAGING_BLOCKED_TASKS`),
  zmiana tekstu → zdarzenie dla Przepisów (część H).

## Testowanie

- Lokalnie: `ruff`, pytest przez `uv` (testy bez bazy), `npx vitest run <pliki>`,
  `npm run type-check`; testy z Postgresem sprawdza CI.
- Staging: backend z gałęzi na porcie części, z własną kopią bazy
  `nexus_branch_<część>` (po teście usunąć), front z gałęzi na porcie części
  (pośrednik CORS jak w notatce o zrzutach headless). Stałego stagingu
  (3100/8100) nie zmieniać. Całą ścieżkę rolami przechodzi sesja główna na
  scalonej gałęzi.
- Wdrożenie: PR z migracjami idzie pasem migracji (etykieta `czeka-na-migracje`,
  bez auto-merge), produkcja w oknie pon–pt 18:00–08:00.
