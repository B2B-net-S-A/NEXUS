# Brakujące ogłoszenia — codzienny mail do osoby, która ma je wstawić (27.10.2026)

<!-- indeks: job_ad.reminders, job_ad_missing / job_ad_backlog / job_ad_nudge, rodzaj job_ad_reminders (obowiązkowy), job_ad_channel_skips „nie publikujemy”, ?ogloszenie= z maila, /jobs/ogloszenia -->

Decyzje Artura z 27.10.2026 (makiety https://claude.ai/artifact/XJYxX56Www29d7P3d9k2ia).
Pomiar na kopii produkcji z 22.10: żadna z 204 otwartych rekrutacji nie miała
kompletu ogłoszeń. Strony kariery brakowało w 201, Pracuj.pl w 181,
JustJoin.IT w 187. Ludzie chodzili po biurze i przypominali sobie nawzajem.
Kierunek „nie w NEXUSIE, tylko mail z przyciskami”: kolejka „Ogłoszenia bez
rekrutacji” z pierwszej wersji makiet jest odłożona.

Kod: `services/job_ad/reminders.py`, schemat `services/job_ad_reminder_schema.py`
(0526), trasy w `api/job_ads.py`, wpięcie w `notification_triggers.run_all_triggers`
i `tasks/notification_email_outbox`.

- **Trzy kanały** otwartej rekrutacji: strona kariery (zatwierdzony opis,
  `career_pages_for_jobs`), Pracuj.pl i JustJoin.IT (aktywne oznaczenie
  `job_ad_publications`). Kanał z wierszem `job_ad_channel_skips` („nie
  publikujemy tu”, z powodem) nie jest brakiem.
  Pracuj.pl po mailu do opiekuna ma stan `requested` i przez 3 dni robocze
  też nie jest brakiem (`ogloszenie-pracuj-mailem-do-opiekuna.md`).
- **Kto robi który kanał.** Strona kariery: Rekruterzy rekrutacji
  (`job_team.working`, bez propozycji automatu), bez nich Delivery Lead.
  Pracuj.pl i JustJoin.IT: Delivery Lead, bez aktywnego DL-a Head of
  Recruitment (`route_to_recipients`). DL dostaje mail o całej rekrutacji,
  także o tym, czego nie zrobił rekruter, z przyciskiem „Przypomnij”.
  Rekruter dostaje własne maile o stronie kariery.
- **Osobno albo zbiorczo.** Próg „wysyłaj od” rodzaju `job_ad_reminders` to
  start przypomnień. Rekrutacja otwarta po nim dostaje osobny wpis
  `job_ad_missing` od dnia roboczego po otwarciu (nie w dniu otwarcia).
  Starsze idą jednym wpisem `job_ad_backlog` na osobę i dzień. Bez tego DL 14
  dostałby pierwszego dnia 56 maili.
- **Kiedy.** Pętla triggerów, dni robocze 8–17, raz dziennie (stan
  `app_settings["job_ad_reminders_state"]`). Wczorajsze nieprzeczytane wpisy
  `job_ad_missing` i `job_ad_backlog` gasną przy nowym przebiegu, żeby
  dzwonek nie rósł codziennie.
- **Mail obowiązkowy** (`REQUIRED_KINDS`): konto go nie wyłączy, wstrzymuje
  tylko admin z powodem (`powiadomienia/maile-obowiazkowe.md`).
- **Kartę składa `reminders.mail_card` przy wysyłce**, ze świeżego stanu.
  Kanał zrobiony od rana wypada z maila, a gdy nic nie zostało, mail nie
  wychodzi. Treść dzwonka nie jest treścią maila.
- **Przyciski tylko otwierają okno** (`maile-z-przyciskami-akcji.md`):
  `/jobs/{id}?ogloszenie=jjit|pracuj|kariera` otwiera okno „Ogłoszenie” na
  kanale, `&przypomnij=rekruter` okno potwierdzenia „Przypomnij”,
  `?ogloszenie=pomin` okno „Nie publikujemy”. Zbiorczy prowadzi do
  `/jobs/ogloszenia` („Ogłoszenia do nadrobienia”). Nic nie zapisuje się
  z samego linku.
- **„Nie publikujemy” i „Przypomnij” decyduje DL rekrutacji, Head of
  Recruitment albo admin** (`reminders.can_manage`; reguła w handlerze, więc
  ma własny test, macierz bramek widzi tylko `RecruiterPlus`). Powód jest
  obowiązkowy (3–300 znaków) i trafia do Historii zdarzeń
  (`job_ad_channel_skipped` / `job_ad_channel_unskipped`).
- **„Przypomnij”** (`POST …/portal-ad/remind`) zakłada wpis `job_ad_nudge`
  każdemu rekruterowi rekrutacji: mail od razu, raz dziennie na osobę
  i rekrutację. Drugi klik tego dnia odpowiada listą `already`.
- **Lista do nadrabiania** (`GET /api/job-ads/missing`): rekrutacje, w których
  osoba ma brak albo prowadzi rekrutację z brakiem, od najnowszej;
  `backlog` = otwarta przed startem przypomnień.
