# Publikacja na RocketJobs i JustJoin.IT (0381, 25.09.2026)

Jedno Employer Public API dostawcy (1EP, `integrations.rocketjobs.com/docs/1ep`,
host `jobboardcore-external.justjoin.it/external-api`) obsługuje oba portale —
pole `jobBoard`. W NEXUSIE to dwa portale (`Portal.rocketjobs`,
`Portal.justjoinit`), jeden adapter (`services/job_portals/jjit.py`) i jedno
połączone konto firmy (`job_board_connections`). Za flagami
`PORTAL_ROCKETJOBS_ENABLED` / `PORTAL_JJIT_ENABLED` (domyślnie OFF); Etap 2
(dane OAuth od dostawcy, połączenie konta, pierwsze ogłoszenie) czeka na
odpowiedź integration@rocketjobs.com. Kontrakt API frontu:
`docs/job-boards-rocketjobs-contract.md`.

- **Tryb podstawowy = statyczny klucz API** (`JJIT_STATIC_ACCESS_TOKEN`,
  JWT ważny do 2 lat — rekomendacja dostawcy dla serwer-serwer, 29.09.2026).
  Ustawiony klucz: portal jest „ready” bez `JJIT_OAUTH_*` i bez wiersza
  połączenia, Ustawienia pokazują „Połączone kluczem API · ważny do …” (data
  z `exp`, bez weryfikacji podpisu) i ostrzegają 30 dni przed końcem (także
  `checks.job_portals` = `degraded`). 401 po kluczu = `PortalReconnectRequired`
  („poproś o nowy klucz”), bez odświeżania. Jednostkę czyta
  `jjit_connection.resolve_unit` z `/organizations/units` i trzyma
  w `app_settings['jjit_static_units']` z odciskiem klucza — nowy klucz czyta
  ją od nowa. Klucz ustawia się WYŁĄCZNIE workflowem „Coolify set env”
  z `value_from_secret`.
- **Tryb zapasowy OAuth: konto łączy admin RAZ** (Ustawienia → System → Portale ogłoszeniowe,
  `api/job_board_connection.py`). Dostawca ma tylko `authorization_code` +
  refresh token. Odświeżenie tokenu idzie we WŁASNEJ sesji z natychmiastowym
  commitem i pod `FOR UPDATE` wiersza (`jjit_connection.access_token`) —
  dostawca rotuje refresh token, a rollback żądania zgubiłby jedyny ważny.
  `invalid_grant` = `reconnect_required`; worker wtedy czeka i nie pali prób.
- **`externalId` NIE chroni przed duplikatem** (dokumentacja). Nasz jest
  STAŁY dla pary rekrutacja × portal (`nexus-job-{job_id}-{portal}`,
  `external_ref_for`): `publish` najpierw szuka po nim żywego ogłoszenia,
  dopiero potem `POST`, a zamknięcie bez znanego id też szuka po nim. Nowy
  wiersz po nieudanej/wycofanej publikacji znajdzie ogłoszenie, które mogło
  jednak powstać, zamiast kupić drugie. Wiersz, który worker brał choć raz,
  przy wycofaniu dostaje `close`, nie `removed`; publikacja poddana po
  timeoutach = `failed` + `close` (sprzątanie po externalId).
- **Worker dzierżawi wiersz, nie blokuje go na czas HTTP** (`claim_batch`
  ustawia `next_attempt_at` = teraz + 15 min, krótka transakcja), portal
  woła bez transakcji, a wynik zapisuje osobna transakcja per wiersz
  (`process_one`). Zlecenie zmienione w trakcie wysyłki (wycofanie, nowe
  ustawienia) zostaje w kolejce. Nieoczekiwany wyjątek jednego wiersza =
  ponowienie z backoffem, nie cofnięcie paczki.
- **Flaga portalu blokuje NOWE publikacje, nie zamykanie** — `unpublish`
  i `status` sprawdzają tylko konfigurację (`ensure_configured`), a worker
  startuje także przy wyłączonych flagach, gdy konto jest skonfigurowane.
- **Treść = biała lista `public_job_payload`** (zatwierdzony opis publiczny),
  link aplikacji = `/r/<slug>` strony kariery z `utm_source=<portal>`,
  `utm_medium=job_board`, `utm_campaign=nexus-job-<id>` (`portal_apply_url`,
  29.09.2026 — raport źródeł widzi JJIT/RocketJobs osobno), więc zgłoszenia wpadają do
  NEXUSA istniejącą ścieżką. Nic o kliencie ani stawce.
- **Widełki są opcjonalne i wpisuje je człowiek** (decyzja Artura 25.09.2026),
  nigdy z budżetu rekrutacji ani stawki Championa. B2B netto, `do ≤ 3 × od`.
- **Ustawienia ogłoszenia** (`job_postings.options`: kategoria ze słownika
  portalu, poziom, wymiar, tryb, dni w biurze, miasto, widełki) walidują
  JEDNĄ regułą w dwóch lustrach: `jjit_payload.validate` ↔
  `validateListingOptions` (`lib/api/jobPortals.ts`). Braki = 422
  `listing_invalid` z listą — kredyt jest płatny, więc nie wysyłamy czegoś,
  co portal odrzuci.
- **`pending_action`** (`publish|update|close`) mówi workerowi, co zrobić
  z żywym wierszem. Nowe zatwierdzenie opisu publicznego i zmiana ustawień =
  `update` (pełny `PUT` z klauzulą i kontaktem z `GET`; tytułu portal nie
  zmienia). Wycofanie i zamknięcie rekrutacji = `close`; nieudane zamknięcie
  zostaje w kolejce co godzinę. Worker co tick zamyka też ogłoszenia
  rekrutacji, które przestały być `published` (każda ścieżka zmiany statusu,
  także nocne archiwum Traffita), a co `JOB_PORTAL_STATUS_SYNC_HOURS`
  sprawdza stan (`expired` po 90 dniach / końcu subskrypcji, 404 = `removed`).
- **`DELETE /api/jobs/{id}` z żywym ogłoszeniem = 409** — kaskada skasowałaby
  wiersz, a ogłoszenie zostałoby na portalu bez możliwości zamknięcia.
- **`/jobs/new`**: sekcja „Ogłoszenie na portalach” (tylko przy `any_ready`),
  szkic z `POST /api/job-intake/public-draft` (bez zapisu, z uwagami
  kontroli), po publikacji rekrutacji: opis → zatwierdzenie → link →
  publikacja (`lib/new-job-portal-publish.ts`). Awaria po utworzeniu =
  toast + `?tab=portals`, rekrutacja zostaje.
- **Kształty potwierdzone na sandboxie dostawcy 29.09.2026** (pełny cykl
  publikacja → edycja → zamknięcie na obu portalach; do tej daty każda
  publikacja by padła, a testy przechodziły, bo kodowały założenia):
  `/oauth/me` NIE niesie jednostki (`organization_id` to ID organizacji) —
  jednostkę daje `GET /employer/organizations/units`, jedna na oba portale;
  lista ogłoszeń wymaga `order`, `orderBy` i `state` (tylko `Published`
  albo `Expired`); `PUT /skills` zwraca `{"skills": […]}`; w saldzie
  `currentUsage` to POZOSTAŁE użycia, `-1/-1` = subskrypcja bez limitu
  (`payment_remaining`); słowniki obejmują naraz JJIT, RocketJobs i HelloHR,
  nazwa jest w `displayName`, a RocketJobs odrzuca kategorię nadrzędną
  (formularz dostaje same podkategorie `children`); `PUT` wymaga
  `categories: [{key}]`, `expiredAt` (wartość tylko przy subskrypcji, przy
  kodzie `null`) i lokalizacji z ulicą i współrzędnymi — bierzemy je
  z `GET`, więc miasta po publikacji nie zmienimy (`city_unchanged`, jak
  tytuł); ponowne zamknięcie = 400 `errors.jobAdvertisementNotActive`
  (traktowane jak sukces); POST, GET i lista zwracają gotowy `url`.
  Bez logo w profilu firmy portal odmawia 422 `hiring.company.logo.required`.
  Sandbox: `jobboardcore-external.stage-wj4yiuqw6nwl.justjoin.it/external-api`
  (token od dostawcy, NIE w repo). Harnessy:
  `/preview/job-portals?dialog=1`, `/preview/new-job?state=portals`.
