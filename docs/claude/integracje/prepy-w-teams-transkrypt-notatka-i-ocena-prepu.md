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
- **Prep zmieniają ludzie pary, zaprosić można każdego (17.10.2026, decyzje
  D1–D4, zgłoszenie DL-a).** Do tej daty spotkanie było własnością prowadzącego
  (`created_by = organizator`): rekruter, który założył Prep 1 w kalendarzu
  DL-a, dostawał 404 na „Szczegóły” i 403 na zmianę, a lista zaproszonych
  przyjmowała wyłącznie zespół rekrutacji (422). Teraz:
  `PATCH /api/interview-cycle/preps/{event_id}` (termin, zaproszeni,
  prowadzący) i `POST …/{event_id}/cancel` rozstrzyga
  `prep_meetings.user_can_edit_prep` — prowadzący, `scheduled_by_user_id`,
  `job.delivery_lead_id`, rekruter kandydata (`default_recruiter_ids`),
  zastępcy (`operational_owner_ids`), HoR i admin — a nie
  `calendar_access` (reguła 17.09 „odwołuje tylko właściciel” zostaje dla
  zwykłych wydarzeń: tam odwołanie idzie kontem M365 twórcy, prep idzie
  aplikacją). Zmiana idzie najpierw do Outlooka prowadzącego, potem do bazy;
  kandydat dostaje aktualizację tego samego zaproszenia. **Inny prowadzący =
  nowe spotkanie, potem odwołanie starego** (Microsoft nie przenosi spotkania
  między kalendarzami); gdy odwołanie starego padnie, nowe jest odwoływane,
  a wiersze cofa rollback — nigdy dwa aktywne prepy o tym numerze. Zaprosić
  można każdego aktywnego z NEXUSA (`options.people`, zespół na górze) i do
  10 adresów spoza (`attendee_emails`, `EmailStr`); prowadzący dalej musi być
  z zespołu albo z podpowiedzi (jego skrzynka jest w grupie aplikacji).
  Planujący za kogoś jest od razu na liście zaproszonych (D3, front), więc ma
  spotkanie u siebie. Kroki odznaki na Tablicy niosą `event_id` — dok pokazuje
  zaplanowane prepy z „Zmień”/„Odwołaj” (`PrepEditButtons`, przyciski tylko
  przy `can_edit`), panel w kalendarzu też (zamiast „Szczegóły”). Jedno okno
  dla „Przełóż”, „Zmień” i „Odwołaj”: `ReschedulePrepDialog` (`mode`). Dopisku
  do zaproszenia nie da się zmienić (nie jest zapisany osobno); zmiana
  prowadzącego zakłada nowe zaproszenie bez dopisku. Osoba spoza NEXUSA na
  prepie to drugi mówca spoza zespołu — kandydat w transkrypcie jest wtedy
  rozpoznawany tylko po nazwisku (`teams_vtt`).
- **Odpowiedź kandydata i powiadomienia pary (0453, 17.10.2026, D5–D8).**
  Do tej daty NEXUS nie czytał odpowiedzi z zaproszenia (mail „Zaakceptowano”
  dostawał tylko organizator), a zmianę zrobioną w Outlooku widział dopiero
  po starej godzinie prepu. Teraz pętla `teams_prep_transcripts` (działa też
  bez transkryptów, gdy `app_only_ready()`) co `TEAMS_PREP_POLL_MINUTES` woła
  `prep_responses.sync_upcoming`: prepy z 14 dni, `GET` wydarzenia
  z `attendees` (te same uprawnienia aplikacji, bez webhooków) →
  `prep_meetings.candidate_response` (`none|accepted|tentative|declined`,
  `NULL` = nie sprawdzano), `proposed_start/end`, przełożenie i odwołanie
  z Outlooka. Pierwszy odczyt prepu sprzed 0453 nie dzwoni o „przyjął”
  (inaczej wdrożenie wysłałoby zaległości naraz); odmowa i inny termin dzwonią
  zawsze. Nowy termin z NEXUSA zeruje odpowiedź (Outlook robi to samo).
  Powiadomienia (`services/prep_notifications.py`, ikona „Kalendarz”) do ludzi
  pary bez autora: `prep_changed_yours` (prowadzący — zmiana w jego kalendarzu,
  dymek), `prep_changed` (reszta pary, licznik; też zmiana z Outlooka),
  `prep_candidate_response` (przyjął / „może”, licznik),
  `prep_candidate_declined` (odmowa albo inny termin, dymek), `prep_no_response`
  (raz na prep, dobę przed, prowadzący + planujący; nie przy prepie założonym
  < 2 h temu). Dymek steruje front: `QUIET_INTERVIEW_TYPES`
  w `lib/interview-notifications.ts`. `prep_attention` idzie też do DL-a
  rekrutacji (D7). Plakietka Tablicy `prep_refused` („Prep N: kandydat
  proponuje …” / „odrzucił”) stoi przed „Prep 2 …”. **`ix_notif_dedup_daily`
  nie zna rodzaju encji** (adresat, typ, ID, dzień): „przełożony” tego samego
  dnia co „zaplanowany” był odrzucany, więc `prep_changed*` idą bez
  `related_entity_id`; odpowiedzi kandydata zostają przy dedupie.
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
- **Ocena v2 (22.10.2026, `services/prep_review.py` + czyste funkcje
  `services/prep_review_scoring.py`, `AIFeatureKey.prep_review`, F24 = GPT-6
  Luna, zapas Sonnet 5, `PROMPT_VERSION = prep-review-v2`).** Punkty buduje
  KOD: tematy prowadzącego z ustawień (`topic:<nr>`, status covered /
  partial / missing), odpowiedzi kandydata na must-have (pisownia DL-a)
  i pytania tego klienta (stopień strong / general / weak / missing ze skali
  w ustawieniach), w Prepie 2 zamiast must-have punkty z notatki na Prep 2
  (`followup:<klucz z Prepu 1>`). Model daje status albo stopień, cytat,
  jednozdaniową wskazówkę „co przećwiczyć” i listy went_well / went_wrong /
  improve (dla prowadzącego). Cytat spoza transkryptu = „nie było (bez
  dowodu)”; obce klucze / pominięta grupa / nieznane wartości dla większości
  punktów = awaria (`unavailable`, `level NULL`, nigdy „słaby”).
  **Wynik liczy kod:** kryterium 0–100, wynik = średnia ważona wagami z
  ustawień; kryterium bez punktów (brak pytań klienta, transkrypt bez mówców
  → brak udziału kandydata) wypada, a jego waga rozkłada się na resztę.
  Poziom z progów; „za krótki = słaby”, pominięty temat obowiązkowy albo
  słaba odpowiedź na must-have = najwyżej „OK” (`caps`). Pytanie klienta
  mocne w Prepie 1 ma w Prepie 2 `covered_in_prep1` i nie liczy się.
  **Notatka na Prep 2:** z Prepu 1 kod wybiera `criteria.followup` (słabe
  odpowiedzi → must-have, których nie omówiono → pominięte tematy
  obowiązkowe → ogólne → nieprzećwiczone pytania; przełączniki i limit
  w ustawieniach); `remaining` = ich etykiety. Prep 2 ocenia te punkty
  jeszcze raz — `criteria.comparison` (przed → po), `remaining` = co nadal
  nie jest „mocne”. Prep 1 sprzed v2 daje notatkę z `remaining`.
  `criteria.items` zostaje w kształcie sprzed v2 (stary widok okna i raporty).
  Notatka `teams_prep` ma fakty, wnioski i listę do powtórzenia — bez
  cytatów i bez transkryptu. Pomiar: `scripts/eval_prep_review.py`
  (Luna vs Sonnet, nic nie zapisuje, `old_level` do porównania).
- **Ocena w Kalendarzu (22.10.2026, decyzja Artura: wszystko zostaje
  w przepływie Kalendarz → Rozmowy u klienta, bez osobnego menu „Prepy”).**
  Karta osoby: pod krokiem Prep / Prep 2 z oceną `PrepStepReview` (plakietki
  Nagranie · Transkrypt · Ocena, poziom z wynikiem, „Prowadzący: x z y
  tematów”, „Kandydat: mocne · ogólne · słabe”, dwa zdania i wejścia „Pełna
  ocena” / „Podsumowanie i follow-up” / „Transkrypt”); pod krokiem Prep 2,
  zanim się odbył, `Prep2FollowupFromPrep1` — lista „Do powtórzenia na
  Prepie 2” z oceny Prepu 1. Okno `PrepReviewDialog` ma zakładki Ocena (wynik
  z wagami, `caps`, tematy, odpowiedzi z cytatem i „Przećwicz”, link „Jak
  liczona jest ocena” → `/settings/prep-review`) · Podsumowanie i follow-up
  (wnioski, notatka na Prep 2 albo porównanie Prep 1 → Prep 2) · Transkrypt
  (`cues` z `GET …/transcript`: czas, mówca, rola; szukanie; klik w cytat
  przenosi tu i podświetla wypowiedź; bez mówców — baner o ustawieniu Teams).
  Ocena sprzed v2 = stary widok punktów bez zakładki podsumowania.
- **Ustawienia → Ocena prepów (0505, 22.10.2026, makiety
  https://claude.ai/artifact/1h38jS5LMc1673CENvUejR, plansza 5).** Head of
  Recruitment i admin publikują wersję ustawień (`PUT /api/prep-review-config`,
  `HeadOfRecruitmentPlus`); rekruter, DL, HoR i admin czytają (`ConfigReader`,
  sekcja Pipeline). Każda publikacja = nowy wiersz `prep_review_configs`,
  obowiązuje najnowszy, `prep_reviews.config_version` mówi, według której
  wersji powstała ocena; zmiana działa od NASTĘPNEJ oceny (starych nie
  przeliczamy). Brak wierszy = ustawienia startowe z kodu
  (`prep_review_config.defaults()`), które odtwarzają ocenę sprzed 0505: progi
  z `PREP_REVIEW_*` i do 20 pytań klienta — env zostaje tylko jako start.
  Wersja z bazy czyta się na tle startowej (nowy klucz dostaje wartość
  startową); nieczytelna = startowa + log, ocena nie staje. Progi, minimalna
  długość, udział kandydata i limit pytań działają od 0505; wagi kryteriów,
  tematy prowadzącego, skala odpowiedzi, notatka na Prep 2 i wskazówki dla AI
  czyta ocena v2 (punkt wyżej). W menu Ustawień pozycja jest dla admina, HoR
  i DL-a — rekruter ma w Ustawieniach samo „Moje konto”, stronę otwiera
  linkiem „Jak liczona jest ocena” z oceny prepu (middleware go wpuszcza).
- **Bramki MIĘKKIE** (nic nie blokuje): Prep 2 wymagany zawsze, gdy rozmowa
  u klienta jest w przyszłości (`PREP2_HINT_DAYS` usunięte); jedyny wyjątek
  z powodem i telefonem przed rozmową — `rozmowa-bez-prepu-2.md` (0482); todo
  `prep_weak`/`prep_unrecorded`, `urgent` <24 h; plakietki kanbana
  `prep_weak`/`prep_missing`; kolejka „Czeka na Ciebie” (`prep_attention`,
  `services/prep_attention.py` — organizator + HoR/admin) i dzwonek
  `prep_attention` raz na sprawę (organizator + każdy HoR). Raport HoR:
  `GET /api/interview-cycle/prep-quality` → Insights → Wyniki → „Jakość prepów”.
- **Po Fireflies zostaje:** wartość enuma `fireflies_meeting`, migracje
  0129/0187, `Note.audio_url`/`source_ref`, `enrich_from_meeting` (używane
  przez „Powiąż + AI” i briefing).
