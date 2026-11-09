# Rozmowy i profil: rejestr faktów, bramka, przeliczenie (08.11.2026)

Decyzja Artura z 08.11.2026 (wariant A, raport
https://claude.ai/artifact/HgCGsxN7Nk7ENGpb6iNg2B, sekcja „Rozmowy i CV”): fakty
z rozmów zapisują się automatycznie, bez potwierdzania. Przycisku „Potwierdź”
z makiet nie budujemy. Flaga `CONVERSATION_FACTS_ENABLED`, domyślnie false;
false = zachowanie sprzed zmiany, a trasa `conversation-facts` zwraca `enabled: false`.

- **Źródłem prawdy jest tabela `candidate_conversation_facts`** (migracja 0670,
  DDL w `services/conversation_facts_schema.py`, lustro w `entrypoint.sh`). Wiersz:
  osoba, rodzaj (skill, domain, certification, regulation), wartość, status
  (confirmed, absent), źródło (sheet, note_ai), etap lub notatka, rekrutacja, autor,
  data rozmowy, bieg skryptu. Cofnięcie stawia `retired_at`; wiersz zostaje jako ślad.
- **Czytelnicy bramki i wyniku czytają projekcję** `cv_extracted_data._conversation_facts`,
  przebudowywaną z tabeli przy każdym zapisie (`refresh_projection`). Bo `must_text_evidence`
  i `scoring_service` to czyste funkcje nad załadowanym kandydatem: zapytanie per osoba
  zabiłoby nocny przegląd. Projekcję pisze wyłącznie `conversation_facts`; klucz jest
  w `NON_CV_EXTRACTED_KEYS`, więc nowe CV go nie kasuje.
- **Mapowanie na słownik** (`map_requirement`, helpery `canonical_of`, `canonical_skill_names`,
  `_alias_pattern`): cała nazwa ze słownika liczy się przy obu statusach; technologia
  wyjęta ze zdania („Optymalizacja zapytań PL/SQL” → PL/SQL) tylko przy potwierdzeniu.
  Zdanie bez odpowiednika liczy się wyłącznie w swojej rekrutacji (`jobs` w projekcji,
  `attach_gate_evidence(job_id=…)`). „Kafka lub RabbitMQ” i „np. Oracle, PostgreSQL” nie
  potwierdzają żadnej opcji, bo nie wiadomo której. Pomiar na kopii z 08.11: z 324
  potwierdzonych umiejętności 40 trafia w słownik, reszta to zdania z Championa.
- **„Nie ma” pochodzi wyłącznie z arkusza** (CHECK `absent_sheet`) i poza swoją rekrutację
  wychodzi tylko przy nazwie dokładnie ze słownika. Bije ślad w CV, ustępuje jawnej
  weryfikacji rekrutera (`reviewed_gate_status`). `skills_gaps_observed` z modelu nie jest
  faktem „nie ma”. Przy kilku opcjach odpada tylko ta jedna (`narrow_requirement`).
- **Pierwszeństwo:** kliknięcie człowieka bije odczyt modelu niezależnie od daty, z kilku
  kliknięć wygrywa najnowsze. Model dopisuje i niczego nie gasi; gasi `retire_note_facts`
  (kandydat bez czytelnych notatek) i skrypt cofnięcia. Zdjęcie kliknięcia w arkuszu gasi fakt.
- **Lista umiejętności:** `skills_manually_curated` i `_manual_override_skills` blokują dopisywanie,
  fakt zostaje dowodem w bramce przez `profile_text`. Projekcja pamięta w `written`, co dopisał
  rejestr, więc cofnięcie zdejmuje tylko te pozycje. REFRESH nowego CV przywraca fakty
  (`reapply_after_cv`), a pozycja obecna też w nowym CV przestaje należeć do rejestru.
- **Oba silniki wyszukiwania** czytają to przez `skill_match` (`candidate_search_predicates`):
  v2 widzi potwierdzone i wycina „nie ma”, v1 (alerty) bez zmian. Bez prywatnych kopii.
- **Przeliczenie po rozmowie:** zapis arkusza i pól profilu dodaje zdarzenie `conversation`
  do `candidate_match_outbox` z bieżącą `candidate_revision` (wersja obejmuje fakty, także odcisk
  notatek `notes_read`). Notatka z rozmowy dodaje zdarzenie `note:<id>`, a worker najpierw
  czyta notatki tej osoby (`extract_candidate_now`, odcisk chroni przed płaceniem za te same),
  potem liczy z bieżącą wersją. Wymaga `AUTO_MATCH_ENABLED`, odczyt `NOTES_INSIGHTS_SYNC_ENABLED`.
- **Weto i „nie szuka”** (`blocked_for_job`) działają tylko w doborze kart, `ranked_picks`.
  Dopasowanie klienta przez `client_off_limits`. „Nie pracował wcześniej w Nordei” nie jest
  wetem (31 z 460 wpisów na kopii z 08.11). „Nie szuka” z datą w tekście rozstrzyga data,
  bez daty obowiązuje 183 dni od odczytu notatek.
- **Pola arkusza** (`SaveInput.profile`): okres wypowiedzenia, dni w biurze i tryb pracy idą
  do profilu, świeża deklaracja nadpisuje jak przy odrzuceniu za tryb pracy (D3 z 14.10.2026).
  Wersji formularza nie tworzą. Dni wygrywają z trybem.
- **Historia:** `scripts/conversation_facts_backfill.py`: podgląd domyślnie, `--apply` wymaga
  flagi, paragon `app_settings['conversation_facts_backfill_<id>']`, `--recalc --batch` pasami
  (`--open-limit`, wznawia po id), `--revert`. Bez wołania modelu.
