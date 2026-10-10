# Profil Championa: sekcje 4 i 8 + propozycja Luny z maila (23.09.2026)

Decyzje Artura 23.09.2026: dziedzina „musi mieć” = plakietka + frazy, nigdy
bramka; „Z historii klienta” liczy Luna automatycznie przy tworzeniu;
propozycja profilu na `/jobs/new` przychodzi wypełniona z chipem źródła.
Wzór Word i edytor mają OSIEM sekcji: 1 Podstawy · 2 Search · 3 Stack ·
**4 Doświadczenie poza stackiem** · 5 Projekt · 6 Screening · 7 O kliencie ·
**8 Wiedza z rozmów**.

- **`experience`** (`domains` z `min_years`, `certifications`, `regulations`;
  `level` must/nice) — normalizacja `champion_intake.normalize_experience_items`
  (także w `build_champion_dict`: model oddaje `level: null` albo 50 lat).
  Konsumenci: prompt propozycji wyszukiwań v3 (przed prozą — wycinek cięty do
  6000 znaków), generator CV „Pod rekrutację” (zaraz po MUST/NICE), plakietki
  `experience_evidence` w `/api/search/candidates/scores` (`met|unknown`, nigdy
  „brak”; klucz `experience` TYLKO przy wypełnionej sekcji), lista „Sprawdź
  w rozmowie” w screeningu (`ScreeningAnswers.experience_checks` — zapis, nie
  punktacja). **Scoring i tekst embeddingu oferty nietknięte** (A/B).
- **`insights`** = notatki zapisane (`manual`/`ai_intake`/`document`) +
  WIDOK składany w `champion_view.insights`: `verification:*` (tylko do odczytu,
  źródłem jest blok `verification`) i `legacy:client.*` (stare pola
  `consultant_insight`/`historical_questions`). **Wpisy `legacy:*` edytor zmienia
  przez STARE POLE sekcji `client`** (`lib/champion-insights.ts`); serwer ich nie
  zapisuje. Zapis zwrotny po stronie serwera czyścił stare pola przy każdym
  zapisie z pustą listą notatek (no-op, import) — złapał to test. Autora i daty
  stempluje `champion_insights.merge_insights`; id nieznane w bazie = nowa
  notatka. Brak klucza `insights` w PUT = sekcja nietknięta.
- **`audience: "team"` nie wychodzi poza zespół**: publiczna karta Championa
  to biała lista bez `insights`/`client_history`, szkic opisu na stronę
  kariery bierze wyłącznie `candidate_insights`.
- **Notatki nie zmieniają wymagań**: `champion_view.requirement_source`
  (kontrakt wymagań) i `RANKING_IGNORED_KEYS` (odcisk rankingu) pomijają
  `insights`/`client_history` i PUSTE `experience`; zmiana `experience`
  unieważnia przejrzany kontrakt. Odcisk rankingu pomija tylko te klucze,
  które pomijał — poszerzenie zmieniłoby odcisk KAŻDEJ oferty.
- **Kopia rekrutacji** nie przenosi notatek, historii ani weryfikacji.
- **`client_history`** (blok maszynowy): `POST /api/jobs/{id}/champion-profile/client-history`,
  `champion_client_history.py` — werdykty HM, odrzucenia PO wysłaniu CV,
  zastrzeżenia kandydatów (18 mies.), nazwiska wycinane przed modelem
  (`scrub_names`), `inputs_hash` = brak wywołania przy tych samych danych,
  awaria = `status=failed` (200), `ai_feature` tylko przy realnym wywołaniu.
  `/jobs/new` woła go po zapisie Championa bez czekania.
- **`JOB_REQUEST_INTAKE` v2** (Luna, `champion_draft`): kontekst klienta
  (`champion_client_context` — karta klienta, 3 profile z tego klienta po
  słowach tytułu, bank pytań z debriefów; bez insightów konsultanta, bo
  niosą imiona); pozycje `experience` tylko z cytatem obecnym w mailu;
  `provenance` per pole; `ask_client` → notatki `topic=ask_client`.
- **Wzór Word v5** (`app/assets/champion/Profil_Championa_v5.0.docx`) budowany
  skryptem `scripts/build_champion_template_v5.py` z v4 — zmieniasz wzór =
  zmieniasz skrypt i budujesz ponownie. v4 nadal się wczytuje (etykiety,
  sekcja projektu po nazwie `[45]. O projekcie`). Parser AI v8.
- UI: `components/champion/*` (sekcje, skrót dla rekrutera, plakietki),
  `ds/RequirementChipInput`, harness `/preview/champion-profile` (przypadek 3).
