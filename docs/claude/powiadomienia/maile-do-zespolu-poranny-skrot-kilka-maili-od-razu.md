# Maile do zespołu: poranny skrót + kilka maili od razu (07.10.2026)

Pomiar 30.09–07.10.2026: dzwonek ma ~11 tys. wpisów w 30 dni na 35 osób,
czytanych w 0–8%, więc nie jest kanałem dla spraw, na które ktoś czeka.
Decyzja Artura 07.10.2026: mail ma nieść tylko to, co wymaga ruchu odbiorcy.

- **Poranny skrót** (`tasks/daily_digest_email.py`, rodzaj `daily_digest`):
  dni robocze 8:00–17:00 Warszawa, jeden mail na osobę z rolą rekruter, TCM,
  DL, Head of Recruitment albo Finanse (admin bez tych ról — nie). Treść to
  kolejka „Czeka na Ciebie” z TEJ SAMEJ funkcji co pulpit
  (`api/board_tasks.build_board_tasks`) + otwarte sprawy klientów DL + terminy
  rekrutacji w 7 dni (`services/daily_digest.py`, czyste funkcje). Listy
  informacyjne („U innych”, wysłane do Cpro) zostają na pulpicie. Pusty skrót
  nie wychodzi. Rezerwacja dnia i ponowienia po restarcie = mechanizm raportów
  KPI (`kpi_email_reports._send_report`, `kpi_email_report_runs`). Nowa
  sekcja panelu „Czeka na Ciebie” = rozważ jej miejsce w `build_sections`.
- **Maile od razu** (`tasks/notification_email_outbox.py`, co 60 s): wiersze
  dzwonka typów z `notification_delivery.notification_kind` →
  `immediate_email_kind`: `dl_review` (CV w QC CV albo kolejce Cpro),
  `cv_returned` (zwrot do poprawy — rozpoznawany po początku tytułu,
  stałe `TITLE_*` w `stage_handoff_recipients`; zmieniasz tytuł dzwonka =
  zmieniasz stałą), `request_assigned` (tylko encja `job`, poranny skrót
  przydziałów nie), `signature_request`, `system_failure`. Powiadomienie
  starsze niż 24 h nie idzie mailem. Rezerwacja i wynik niepewny jak
  w `job_deadline_alerts`.
- **Alerty klientów i umów mailem tylko do Delivery Leada** (rola główna albo
  dodatkowa, `dl_alerts.send_pending_alert_emails`) — admin ma je w panelu.
- **Alarm wydatków AI**: raz w tygodniu na funkcję i miarę, raz w miesiącu na
  funkcję (bez poziomów w kluczu) — tylko dzwonek.
- Wszystko za polityką z Ustawień → Powiadomienia (domyślnie OFF, włączenie
  nie wysyła zaległości). Bez maili do kandydatów (`application_confirmation`
  zostaje wyłączone — decyzja Artura). Wyłączniki pętli:
  `DAILY_DIGEST_EMAIL_ENABLED`, `NOTIFICATION_EMAIL_OUTBOX_ENABLED`.
