# Autonomiczny przepływ CV (17.09.2026)

Raport: `docs/cv-autonomous-flow-completion-report.md`. Trzy reguły, które łatwo cofnąć:

- **Każde wejście CV kończy się `cv_ingest_service.finish_cv_ingest`**: pola →
  języki → indeks technologii → kategoria → wektor → cache → kolejka
  auto-dopasowania. Do 17.09 sześć miejsc robiło po odczycie co innego (CV z maila
  nie trafiało do wektora). Skan AST w `test_cv_ingest_service.py` pilnuje, że
  poza tym modułem `_apply_cv_enrichment` wołają tylko dwa biegi masowe
  (`cv_backfill`, `cv_field_backfill`) — świadomie bez auto-dopasowania, bo nocny
  sync Traffita dodawałby do pipeline'ów tysiące historycznych osób.
- **Pełny profil (prompt `cv_enrichment` v7) tylko dla nowych/odświeżonych CV**
  (decyzja: bez backfillu 49 tys.). Znacznik `cv_extracted_data._profile_schema = 2`
  odróżnia profil v7; frontend pokazuje certyfikaty, projekty i oś technologii
  WYŁĄCZNIE przy nim (pusta sekcja twierdziłaby, że CV ich nie ma). Oś
  (`skill_timeline`, tabela `candidate_skill_usage`) liczy Python z dat stanowisk
  i projektów — model jej nie pisze. Tekst embeddingu dla profili bez schematu 2
  musi zostać bajt w bajt taki sam (inaczej reindeks całej bazy), a próg
  „ostatnich lat" liczy się od daty odczytu CV, nie od zegara. Opis stanowiska
  z CV ma `source: "cv"` i NIE blokuje nadpisania historii nowym CV; opis
  z importu Traffita blokuje jak dotąd. Waga świeżości skilli w scoringu:
  `AI_SCORING_SKILL_RECENCY` (domyślnie OFF do pomiaru `eval_matching.py`).
- **Auto-dopasowanie** (`auto_match_service`, worker `candidate_auto_match`,
  tabele `candidate_match_outbox` + `candidate_auto_match_log`): nowe CV →
  opublikowane rekrutacje, publikacja/istotna zmiana rekrutacji → CV odczytane
  w ostatnich `AUTO_MATCH_JOB_LOOKBACK_DAYS`. Dodaje przez
  `proposals_bulk.add_candidates_to_job` (te same bramki co rekruter) na etap
  `posting` z tagiem `auto-match` i dzwonkiem `auto_match` (dedup po wierszu
  etapu; typ musi być w `NOTIFICATION_SECTION_BY_TYPE`, inaczej rekruter go
  nie widzi). Pula to wyszukiwanie w Qdrancie ZAWĘŻONE filtrem po id do
  opublikowanych rekrutacji albo profili v7 z okna — nie „najbliższe z całej
  bazy". Częściowy UNIQUE kolejki obejmuje `pending`/`processing`/`failed`
  (bez `failed` przejęcie paczki łapało konflikt unikalności i stawało na
  zawsze). Dziennik decyzji jest dedupem (kandydat × rekrutacja × wersja CV):
  `added` blokuje zawsze, `dry_run` nigdy, reszta do zmiany rekrutacji — i
  podglądem w Ustawieniach → AI. Reguła progu jest JEDNA z importerem JJIT
  (`auto_match_rules.is_good_match`). **Tryb rozstrzyga `AUTO_MATCH_MODE`
  (od 21.09.2026, domyślnie `propose`)** — patrz „Automaty rekrutacji v3";
  `AUTO_MATCH_DRY_RUN` został aliasem (true → `dry_run`, false → `add`)
  czytanym tylko, gdy `AUTO_MATCH_MODE` jest puste.
  **Konflikt z klientem (`active_conflict`) i wykluczenie klienta
  (`client_excluded`) BLOKUJĄ automat**, choć od #1589 rekruterowi tylko
  ostrzegają: ostrzeżenie czyta człowiek, a automat nie ma kogo ostrzec
  (`auto_match_service._BLOCKING_WARNINGS` → decyzja `penalized`).
- **CV z maila od nadawcy spoza bazy** (`attachment_handler.try_create_candidate_from_cv`):
  tożsamość z TREŚCI CV (rekruterzy przesyłają CV dalej). E-mail/telefon/LinkedIn
  pasuje → mail podpięty (`EmailMatchMethod.cv_identity`); pasuje samo imię
  i nazwisko → nic (`possible_duplicate_name`); CV bez imienia, nazwiska albo
  kontaktu → nic (`identity_insufficient`). Tylko poczta z ostatnich
  `M365_AUTO_CREATE_LOOKBACK_DAYS` (14). Wyłącznik `M365_AUTO_CREATE_CANDIDATE_FROM_CV`.
