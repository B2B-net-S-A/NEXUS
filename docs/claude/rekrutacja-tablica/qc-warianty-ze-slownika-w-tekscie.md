# QC i strażnik generatora szukają wymagania po wariantach ze słownika (etap 3a, 07.11.2026)
<!-- indeks: warianty narzędzi, metodyk, AI, standardów i dziedzin liczą się w tekście CV; „project” przy „Microsoft Project” nie; znacznik `skill_aliases.in_text`; pogrubianie bez zmian -->

Decyzja Artura z 07.11.2026 (audyt słownika, etap 3a). Do tej pory QC
(`dz_review._patterns`) i strażnik generatora (`strip_unsupported_terms`)
szukały wymagania w tekście po wariantach słownika tylko dla technologii
(`TECH_CATEGORIES`). Narzędzia, metodyki, AI, standardy i dziedziny szły
dosłownie, więc QC pytało analityków AML o „Anti-Money Laundering”.

- **Pomiar na kopii (704 pary QC od 15.10):** znika 126 fałszywych uwag
  w 129 parach, z czego 114 to AML. Do tego OOP, „wzorce projektowe” =
  Design Patterns, „Identity and Access Management” = IAM i DORA. Żadna
  prawdziwa uwaga nie zniknęła: „Microsoft Project” QC znajduje dalej po
  „MS Project”, a nie po słowie „project”. 21 pozycji zmienia rodzaj
  („brak w CV” → „jest w CV, nie ma w oryginale”).
- **Reguła domyślna** (`skill_normalize.alias_counts_in_text`):
  - wariant technologii liczy się jak dotąd;
  - przy pozostałych kategoriach nie liczy się jedno słowo będące częścią
    wielowyrazowej nazwy („project”, „word”, „teams”, „office”, „excel”,
    „windows”), bo samo uznałoby brak za trafienie;
  - role nie mają wariantów w tekście.
- **Znacznik `skill_aliases.in_text` (0659):** `NULL` oznacza regułę domyślną,
  a TRUE/FALSE to decyzja HoR+ w „Słowniku umiejętności”. Przekreślony chip
  wariantu nie liczy się, kliknięcie go przestawia
  (`PATCH /api/skills-admin/aliases/{id}`). Znacznik nie zmienia
  wyszukiwania ani dopasowania (mapa aliasów scoringu zostaje ta sama), więc
  wyniki rekrutacji się nie przeliczają.
- **„Usuń termin” zostaje przy technologiach** (`dz._tech_patterns`).
  Pogrubianie od G2 (07.11.2026) bierze technologie, narzędzia, standardy
  i AI ze słownika razem w generatorze i w QC (`cv_qc._bold_patterns`) —
  patrz `generator-cv/pogrubianie-wymagan-przez-slownik.md`. Nie przenoś
  `_has_unbolded`, `bold_all` ani `remove_term` na `_patterns`: dziedziny
  i metodyki się nie pogrubiają.
- `QC_VERSION = "qc-truth-5"`, więc pętla `cv_qc_recompute` przelicza
  nieudane przebiegi sprzed wysłania.
- Testy: `tests/test_skill_alias_in_text.py`. W testach bez bazy słownik
  wczytuje `tests/taxonomy_fixture.hydrated_taxonomy`, który liczy też
  `TEXT_ALIASES`.
