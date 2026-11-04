# „Oceń z AI” na zaznaczonych osobach (28.10.2026)

Zgłoszenie rekrutera z 28.10.2026: zamiast ufać „Propozycjom z bazy” pobierał
CV hurtem (alarm „masowe przeglądanie CV”), wrzucał je do prywatnego czatu,
a ten mówił, kogo dodać i w jakiej kolejności dzwonić. W 30 dniach pliki na
dysk zapisało 30 osób, 5 hurtem — dane osobowe kandydatów poza firmą.
Decyzja Artura: wariant C z makiet https://claude.ai/artifact/TBHtexa3vvyK76HW2vkSMS
(po słowniku IdentityIQ = IIQ i sekcji ukrytych + najlepszych 40).

- **Gdzie:** okno „Kandydaci do dodania”. W „Szukaj ręcznie” pasek
  zaznaczonych ma „✦ Oceń z AI” jako główną akcję i „Dodaj N do Nowych” obok
  (`CandidatesListEmbed.onAssessWithAi`); w propozycjach („Nowi z ogłoszeń”,
  „Propozycje z bazy”) przycisk stoi w stopce obok „Pomiń zaznaczone”. Do 30
  osób naraz (`AI_ASSESSMENT_MAX` ↔ `MAX_BATCH`).
- **Panel „Ocena AI · N zaznaczonych osób”** (`AiAssessmentPanel`, nakładka
  `overlayPane` w `RecruitmentSheet`, Esc zamyka najpierw panel): liczniki
  Dzwoń / Może / Nie pasuje, osoby w kolejności dzwonienia, 1–2 powody, każdy
  z cytatem („CV: „…”” albo „Notatka: „…””). Na dole „Dodaj K „Dzwoń” do
  Nowych w tej kolejności” — dodanie drogą zakładki (lista `addToEmbedJob`,
  propozycje `proposals.addToJob`), więc rezerwacja 12 h, „Cofnij” i odmowy
  bez zmian. Bez własnego `POST /api/pipeline/move`.
- **Model czyta więcej niż bramka:** całe `raw_cv_text` (24 tys. znaków),
  notatki-dowody (`EVIDENCE_NOTE_TYPES` — bez maili; bez notatek zakrytych
  przed oglądającym: `note_rate_visibility_clause`, `hidden_send_note_ids`)
  i rolę z Championem, krytycznymi, must i nice (`job_prompt_block(...,
  with_critical=True)`). Bez stawek, klienta i kontaktów.
- **Reguła z cytatem — wspólna z przeglądem zgłoszeń** (`services/
  cv_quoted_evidence.py`, wydzielone z `application_screening`): kod liczy
  must-have, model uzasadnia, powód bez cytatu obecnego w CV, notatce albo
  profilu znika. Werdykt (`candidate_ai_assessment.decide`): „Nie pasuje” bez
  cytatu → „Może”; „Dzwoń” bez cytatu albo przy must-have < 50% → „Może”.
  „Nie pasuje” z cytatem zostaje nawet przy must-have w tekście — słowo bywa
  nazwą czegoś innego (aplikacja z innej dziedziny), a to widzi tylko model.
- **AI niczego nie odrzuca** i nie zmienia procentu dopasowania — tylko
  kolejność (`call_order_key` ↔ `callOrder`: werdykt, siła 1–5, must-have,
  miejsce w zaznaczeniu). Brak CV albo awaria modelu = „AI nie oceniło”,
  osoba zostaje na liście i da się ją dodać.
- **Model:** F39 `candidate_ai_assessment` w rejestrze (GPT-6 Luna, zapas
  Sonnet 5, env `CANDIDATE_AI_ASSESSMENT_MODEL`), wywołanie w `ai_feature()`.
  Klucz w enumie, seedzie `ai_features`, migracji 0620 i lustrze w
  `entrypoint.sh`.
- **Zapis przy rekrutacji:** `candidate_ai_assessments` (kto, kiedy, kogo,
  werdykt, powody; DDL w `candidate_ai_assessment_schema.py`). `GET
  /api/jobs/{id}/ai-assessments/latest` oddaje ostatnią paczkę tej osoby
  (≤ 7 dni) — „Ostatnia ocena AI · Otwórz” nad wynikami „Szukaj ręcznie”.
  Ponowne „Oceń z AI” tej samej osoby w ciągu 24 h przepisuje wynik bez
  modelu; „Oceń jeszcze raz” (`refresh`) woła model od nowa.
- **Audyt i alarm:** paczka zapisuje `Activity(job, "ai_candidates_assessed")`
  z samymi id i liczbami. Alarm o masowym przeglądaniu CV
  (`candidate_data_access_alerts.WATCHED_ACTIONS`) tego NIE liczy — CV nie
  opuszcza serwera, rekruter widzi tylko cytaty. Pilnuje test.
- **Dostęp:** `POST /api/jobs/{id}/ai-assessments` i `…/latest` — sekcja
  Pipeline, `RecruiterPlus`, `ensure_job_membership` (wzorzec golden jak
  `proposals/bulk`). Kto nie może dodać do rekrutacji, nie zleca oceny.
- **Limit:** 150 osób ocenionych modelem na osobę i dzień firmy
  (`CANDIDATE_AI_ASSESSMENT_DAILY_LIMIT`), 429 z liczbą pozostałych. To nie
  budżet AI (`ai-jarvis/nexus-bez-limitow-ai.md` zostaje), tylko zapora przed
  przeczesaniem bazy przez AI hurtem: zgłaszający ocenia ~30–40 osób dziennie,
  150 = pięć pełnych zaznaczeń. Przepisane wyniki limitu nie zużywają.
- **Paczki:** przeglądarka wysyła po 6 osób (`MAX_PER_REQUEST`), dwie paczki
  naraz, jeden `batch_id`; serwer woła model dla paczki równolegle. Żadne
  żądanie nie czeka dłużej niż jedna runda modelu, panel pokazuje postęp.
  Wywołania modelu idą przez własny limiter wątków (`MODEL_THREADS = 8` na
  cały serwer), nie przez wspólną pulę `run_in_threadpool` — kilka osób
  klikających naraz zajęłoby ją na 45 s. Front czeka `SLOW_ENDPOINT_TIMEOUT_MS`
  (domyślne 30 s zrywało paczkę, choć serwer zapisywał wynik i liczył limit).
  Po 429 reszta zaznaczenia zostaje w panelu jako „AI nie oceniło — dzienny
  limit”. Awaria przed modelem kończy się `rollback()`, który wygasza obiekty
  sesji — serwis i trasa trzymają same id, nie obiekty ORM.
