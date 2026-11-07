# Aplikacja z formularza JustJoin.IT trafia do rekrutacji ogłoszenia (06.11.2026)

<!-- indeks: JJIT_APPLY_EMAIL, apply.email, POST /candidates/{id}/portal-application, services/portal_application, „Aplikacja CV” vs „Przekierowanie na ATS”, scraper CURRENT_AD -->

Decyzja Artura z 06.11.2026: kandydat aplikuje formularzem JustJoin.IT (jedno
kliknięcie, CV zostaje w panelu pracodawcy), a nie na naszej stronie kariery,
bo część ludzi odpada na drugim formularzu. NEXUS sam zakłada kartę w „Nowi”
rekrutacji, na którą kandydat aplikował.

Pomiar na kopii produkcji z 06.11.2026: 2 159 aplikacji z JustJoin.IT
i RocketJobs w 30 dni, 1 690 (78%) bez karty i bez propozycji w żadnej
rekrutacji. Import z panelu znał tylko tytuł ogłoszenia: profil trafiał do
bazy, a karta powstawała wyłącznie z auto-matcha CV, zwykle w innej
rekrutacji. Przykład: na „Data Engineer” (ZOB-3155) aplikowało 6 osób, żadna
nie była w rekrutacji.

Kod: `services/portal_application.py`, trasa
`POST /api/candidates/{candidate_id}/portal-application`
(`api/candidate_sources.py`), adapter `job_portals/jjit_payload.apply_method`,
scraper na Macu (`rocketjobs-traffit-scraper`: `CURRENT_AD`,
`nexus_pipeline.place_portal_application`).

- **Publikacja przez API wysyła `apply.email`, gdy jest `JJIT_APPLY_EMAIL`.**
  1EP przyjmuje dokładnie jedno z `url` / `email` (`ApplySharedDto`):
  `email` = formularz portalu, `url` = przekierowanie na nasze `/r/<slug>`.
  Pusta zmienna = jak dotąd link do strony kariery. Zmienia ją tylko
  workflow „Coolify set env”.
- **API 1EP nie ma aplikacji ani webhooków** (spec
  `integrations.rocketjobs.com/openapi/employer-public-api-1ep.json`, 06.11.2026).
  CV czyta import z panelu pracodawcy (`employer-api`), czyli scraper na Macu
  albo port w NEXUSIE (`services/integrations/jjit`, `JJIT_ENABLED`).
- **Rekrutację ogłoszenia wyznacza NEXUS, nie scraper:** najpierw
  `job_postings.external_id` (id ogłoszenia z API, UUID, ten sam w panelu),
  potem slug z `job_ad_publications.url` („Oznacz jako opublikowane”, żywa
  publikacja `jjit`, cały ostatni człon ścieżki). Nie dopasowuj po tytule:
  tytuły powtarzają się między rekrutacjami.
- **Kartę zakłada `add_candidates_to_job`**, czyli te same bramki co rekruter
  (czarna lista, NDA, konflikty klienta, weto, już w procesie), etap „Nowi”,
  `entry_source = application`, bez blokady 12 h. Źródło „ogłoszenie” z
  `job_id` to dowód zgłoszenia dla `integration_intake`.
- **Trasa przyjmuje tylko token integracji** (403 dla człowieka): pomija
  `ensure_job_membership`, więc człowiekowi zostaje „Dodaj do rekrutacji”.
  W mapie OAuth tylko `POST`.
- **Ogłoszenie bez rekrutacji = `no_job`, bez zapisu.** Rekrutacja zamknięta =
  źródło z `job_id`, bez karty (`job_not_open`).
- **Dzwonek idzie jak przy stronie kariery:** pracujący prowadzący, inaczej DL.
  Rekrutacja w P0 z uśpionym zespołem bywa bez odbiorcy; tak samo działa dziś
  strona kariery.
- **Scraper woła trasę po udanym `from-cv`.** 404 (NEXUS bez trasy) i błąd nie
  zatrzymują importu ani nie cofają `lastRun`. Auto-match do innych rekrutacji
  zostaje jako propozycje.
- **Niepotwierdzone przy wdrożeniu:** czy obiekt ogłoszenia z panelu ma `slug`
  (scraper szuka `slug`, `url`, `publicUrl`). Bez niego ogłoszenia wklejone
  ręcznie nie zostaną rozpoznane, a działać będą tylko te z API. Sprawdzenie:
  linia `🗂️ NEXUS rekrutacja ogłoszenia:` w logu biegu.
- **Strona kariery nie jest warunkiem publikacji na JJIT przy formularzu
  portalu (06.11.2026).** Przy `JJIT_APPLY_EMAIL` trasa `portal-ad/jjit` nie
  zwraca 409 `career_not_live`, a `build_content` nie wymaga zatwierdzonego
  opisu publicznego ani linku kariery (`_build_native_content`: zakładka
  JustJoin.IT, `apply_url` pusty). Bez zmiennej obowiązuje stara reguła.
- **„Aplikacje” i „Aplikował na …” (07.11.2026).** Kafel „Aplikacje N”
  w nagłówku rekrutacji otwiera listę wszystkich aplikujących na ogłoszenie
  z 90 dni (`GET /api/jobs/{id}/applicants`, `services/job_applicants.py`):
  kanał, data, etap w tej rekrutacji i propozycje w innych otwartych
  rekrutacjach. Zgłoszenie = zdarzenie źródła z `job_id` na kanale
  `career_link_job` (strona kariery, przekierowanie z portalu) albo `posting`
  (formularz portalu). Okno „Kandydaci do dodania” pokazuje „Aplikował na: …”
  z `proposal-facts.applied_to`. Pierwszy bieg scrapera 07.11.2026: 46
  aplikacji, 9 do swojej rekrutacji, 37 `no_job` (ogłoszenia bez rekrutacji
  w NEXUSIE, np. „Programista .NET”, „IT Recruiter”).
