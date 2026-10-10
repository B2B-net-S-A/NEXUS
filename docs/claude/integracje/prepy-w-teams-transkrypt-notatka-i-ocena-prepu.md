# Prepy w Teams → transkrypt, notatka i ocena prepu (0370, 23.09.2026)

Zastępuje martwą integrację Fireflies (klucz pusty na prodzie, 0 notatek).
Przed każdą rozmową u klienta są DWA prepy z kandydatem przez Teams: Prep 1
prowadzi Delivery Lead, Prep 2 — rekruter (telefon po rozmowie zostaje
zwykłym telefonem z ręcznym debriefem). Konfiguracja M365: `docs/teams-prep-setup.md`.

- **App-only, OSOBNA rejestracja „NEXUS Teams Prep”** (`TEAMS_PREP_CLIENT_ID/SECRET`,
  `services/m365/teams_prep_auth.py`, `AppGraphClient(token_provider=…)`), nie
  „NEXUS ATS - Mailbox and Login”: polityka Exchange zawęża aplikację do
  SKRZYNEK, nie do uprawnień — skrzynki zespołu w zakresie aplikacji z
  `Mail.Read` dałyby jej odczyt ich poczty. Spotkanie powstaje w kalendarzu
  ORGANIZATORA (`POST /users/{upn}/events`, `transactionId`), bo M365 ma
  połączone 2 z ~30 osób. Edycja i odwołanie prepu idą tą samą aplikacją
  (`_push_prep_changes`, gałąź w `cancel_event` w `api/calendar.py`).
- **Tylko prepy założone w NEXUSIE** (`POST /api/interview-cycle/preps`,
  `prep_meetings` 1:1 z wydarzeniem). Spotkania z Outlooka nie są wciągane
  (decyzja). Organizator podpowiadany: Prep 1 → `job.delivery_lead_id`, Prep 2 →
  `interview_slots.default_recruiter_id`; organizator i uczestnicy muszą być
  w zespole rekrutacji. Po utworzeniu PATCH `recordAutomatically` — porażka nie
  cofa prepu (`transcription_setup=failed` + „włącz ręcznie”).
- **Zaproszenie na prep = `services/prep_invitation.py`** (02.10.2026,
  zgłoszenie DL). Tytuł jak w dotychczasowych zaproszeniach zespołu z Outlooka:
  „Przygotowanie do spotkania z Klientem <klient> - <kandydat>” (Prep 2:
  „(spotkanie 2)”) — z nazwą klienta, bez „Prep” i bez półpauz; do tej daty
  „Prep 1: <kandydat> — <stanowisko>” (kandydat przed rozmową u klienta i tak
  go zna). Treść to stałe akapity (powitanie, zaproszenie z klientem
  i stanowiskiem, termin rozmowy tylko gdy prep jest PRZED nią, dopisek
  z okna, zakończenie, podpis organizatora), a informacja o nagrywaniu
  i administratorze danych (`NOTICE_TEXT`, wersja robocza do akceptacji
  prawnej) stoi pod kreską jako adnotacja. Do Outlooka idzie HTML
  (`as_html` — do tej daty zwykły tekst w treści HTML sklejał wszystko w jeden
  akapit), w NEXUSIE opis jest zwykłym tekstem (`as_plain`). Terminu samego
  prepu w treści NIE ma — niesie go zaproszenie, a wpisany tekstem zostałby
  nieaktualny po przełożeniu spotkania (zmiana terminu nie przepisuje treści). Okno
  „Zaplanuj prep” pokazuje podgląd z tego samego szablonu
  (`options.invitation`, pola `{note}`/`{organizer}` podstawia
  `lib/prep-invitation.ts`) i mówi, w czyim kalendarzu powstaje spotkanie
  i kto dostaje zaproszenie.
- **Prep po rozmowie u klienta należy do jej rundy** (`PairSnapshot.late_preps`,
  lustro w `prep_meetings.active_prep`, 02.10.2026). Rekruter zaplanował
  Prep 1, zanim DL potwierdził termin rozmowy na dwa dni wcześniej; prep nie
  należał do żadnej rundy, ekran pokazał „Prep 1 bez terminu”, serwer założył
  drugi i kandydat miał dwa zaproszenia. Teraz prep po OSTATNIEJ zaplanowanej
  rozmowie pary to krok „po terminie” z akcją „Przełóż” (`open_event`), zadanie
  `prep_late`, powód `late` w `prep_attention` (dzwonek od razu), a drugi prep
  o tym numerze = 409 ze zdaniem, kiedy jest istniejący. Między dwiema
  zaplanowanymi rozmowami prep nadal należy do następnej. Okno prepu liczy
  podpowiedź i ostrzeżenie także względem terminu, który dopiero czeka na
  wybór albo potwierdzenie (`tentative_interview_at` w pozycji ekranu
  i w odznace doku). Kroki w odznace doku niosą `at` — do tej daty miały tylko
  `key` i `state`, więc okno prepu otwarte z doku nie znało terminu rozmowy,
  podpowiadało „jutro 10:00” i nie ostrzegało.
- **Pętla `teams_prep_transcripts`** (`TEAMS_PREP_TRANSCRIPTS_ENABLED`, OFF
  kończy ją przed pętlą; heartbeat). Stan kolejki w bazie, odświeża termin
  z Outlooka przed pobraniem, backoff, po `TEAMS_PREP_FETCH_GIVE_UP_HOURS` →
  `missing` („bez nagrania”); 403 → `forbidden` bez zużywania prób +
  `checks.teams_prep=degraded`. Do logu tylko kod/klasa błędu.
- **Transkrypt w `prep_transcripts` BEZ limitu czasu** (decyzja), kaskadą
  z kandydatem (art. 17; `calendar_events.candidate_id` to SET NULL, dlatego
  każda tabela ma własny CASCADE). Pełny tekst: `GET …/preps/{id}/transcript`
  za `ensure_job_read_access` (od #1742 każda rola wewnętrzna, nie tylko zespół). Notatka (`external_source='teams_prep'`) niesie
  WYŁĄCZNIE podsumowanie — czyta ją nocny `notes_insights` (GPT-6 Luna).
  Mówcy z VTT (`services/teams_vtt.py`): zespół po nazwisku, kandydat po
  nazwisku albo jako jedyny mówca spoza zespołu; udział kandydata `None`, gdy
  nie da się go wskazać — nigdy 0.
- **Ocena (`services/prep_review.py`, `AIFeatureKey.prep_review`, F24 = GPT-6
  Luna, zapas Sonnet 5):** punkty buduje KOD (must-have w pisowni DL-a z
  `dz_review.job_requirements` + pytania klienta z debriefów i przypięte),
  model daje status i cytat, cytat spoza transkryptu = „nie było (bez
  dowodu)”. Poziom liczy kod (`PREP_REVIEW_*`); w Prepie 2 punkt zaliczony
  w Prepie 1 = `covered_in_prep1` poza mianownikiem. **Awaria modelu = `level
  NULL`, nigdy „słaby”.** Pomiar Luny: `scripts/eval_prep_review.py`.
- **Bramki MIĘKKIE** (nic nie blokuje): Prep 2 wymagany zawsze, gdy rozmowa
  u klienta jest w przyszłości (`PREP2_HINT_DAYS` usunięte); todo
  `prep_weak`/`prep_unrecorded`, `urgent` <24 h; plakietki kanbana
  `prep_weak`/`prep_missing`; kolejka „Czeka na Ciebie” (`prep_attention`,
  `services/prep_attention.py` — organizator + HoR/admin) i dzwonek
  `prep_attention` raz na sprawę (organizator + każdy HoR). Raport HoR:
  `GET /api/interview-cycle/prep-quality` → Insights → Wyniki → „Jakość prepów”.
- **Po Fireflies zostaje:** wartość enuma `fireflies_meeting`, migracje
  0129/0187, `Note.audio_url`/`source_ref`, `enrich_from_meeting` (używane
  przez „Powiąż + AI” i briefing).
