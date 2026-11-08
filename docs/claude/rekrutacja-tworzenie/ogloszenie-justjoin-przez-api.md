# JustJoin.IT przez API z okna „Ogłoszenie” (03.11.2026)

<!-- indeks: „Opublikuj na JustJoin.IT”, POST portal-ad/jjit, jjit_api, job_ad.portal_content, record_portal_send, PORTAL_JJIT_ENABLED -->

Ostatni krok decyzji Artura z 21.10.2026 (`ogloszenie-jedna-tresc-strona-kariery.md`).
Do tej daty adapter i kolejka istniały (`publikacja-na-rocketjobs-i-justjoin-it.md`),
ale okno „Ogłoszenie” miało tylko kopiuj-wklej, a kolejka wysyłała inny tekst niż
zakładka. Ani jedno prawdziwe ogłoszenie nie poszło przez API do 03.11.2026; ręcznie
oznaczono wtedy 41 ogłoszeń.

Kod: `POST /api/jobs/{id}/portal-ad/jjit` (`api/job_ads.py`),
`services/job_ad/portal_content.py`, `job_portals/service.py` (`send_ad_to_jjit`,
`_sync_ad_publication`), `publications.record_portal_send` i `record_portal_removal`;
front `components/v2/job-ad/JjitPublishDialog.tsx`, karta w `AdPublications`
(`jjitActions`, `state.jjit_api`).

- **Działa dopiero przy `PORTAL_JJIT_ENABLED`, włączonej na polecenie Artura 04.11.2026.**
  Flaga wyłączona: `jjit_api` = `null` i okno jest takie jak było. Zmienia ją tylko
  „Coolify set env”. Bez logo w profilu firmy portal odmawia 422
  `hiring.company.logo.required`, a odmowa wraca na kartę.
- **Na portal idzie zakładka JustJoin.IT, nie opis publiczny.** `portal_content.prepare`
  liczy ten sam render i tę samą kontrolę co odpowiedź okna, w chwili wysyłki. Znalezisko
  blokujące po kliknięciu = odmowa workera, nic nie wychodzi. Rozjazd treści między
  portalami to błąd z pomiaru 12.10.2026, więc nie dokładaj osobnego tekstu dla API.
  Bez wiersza `job_ads` kolejka wysyła jak dawniej opis publiczny.
- **Publikuje DL rekrutacji, Head of Recruitment albo admin**, także starszymi trasami
  `/portals/justjoinit/*`, bo kredyt jest płatny. Rekruter robi stronę kariery i widzi stan.
- **Oznacza też tylko DL rekrutacji, Head of Recruitment albo admin** (decyzja Artura
  08.11.2026, `publications.can_mark`, `can_mark_publications` w odpowiedzi okna). Dotyczy
  „Oznacz jako opublikowane”, zmiany linku, „Zaktualizowane na portalu” i „Zdjęte z portalu”
  na obu portalach, także w zamkniętej rekrutacji. Oznaczenie rekrutera blokowało DL-owi
  publikację (409 `ad_marked_published`). Kopiowanie treści i stronę kariery rekruter ma dalej.
- **`PUT` odsyła kontakt z `GET` tylko z telefonem** (`_contact_with_phone`). Portal oddaje
  kontakt bez telefonu, a przy aktualizacji go odrzuca (produkcja, 08.11.2026).
- **Strona kariery musi wisieć w tej samej wersji** (409 `career_not_live`) —
  tylko w trybie linku (`apply.url`). Przy `JJIT_APPLY_EMAIL` (formularz
  portalu, od 06.11.2026) nie jest warunkiem:
  `aplikacja-z-formularza-justjoin-do-rekrutacji-ogloszenia.md`. Kandydat
  aplikuje przez `/r/<slug>`, więc nie może trafić na starszą treść. „Zaktualizuj na
  stronie” sama kolejkuje aktualizację portalu (`queue_content_update`).
- **Ogłoszenie oznaczone ręcznie nie kupuje drugiego kredytu** (409 `ad_marked_published`):
  wklejone nie ma naszego `externalId`, więc szukanie przed `POST` go nie znajdzie.
  W drugą stronę: gdy ogłoszenie trzyma kolejka, ręczne oznaczanie = 409 `jjit_api_live`,
  a „Zdejmij z JustJoin.IT” kolejkuje zamknięcie zamiast zapisywać sam stan.
- **Sprzątanie po nieudanej publikacji niczego nie zdejmuje** (wiersz `failed` + `close`).
  W godzinę po niepewnej próbie ktoś mógł wkleić ogłoszenie ręcznie i je oznaczyć. Zamknięcie
  po `externalId` go nie znajdzie, a skasowane oznaczenie otworzyłoby drugą płatną publikację.
- **RocketJobs jest poza tym krokiem.** Reguła ról obejmuje tylko `justjoinit`, a RocketJobs
  nie zapisuje „gdzie wisi”. Przed włączeniem `PORTAL_ROCKETJOBS_ENABLED` trzeba objąć go
  obiema zasadami, bo żywe ogłoszenie na RocketJobs nie zablokuje drugiego kredytu na JustJoin.IT.
- **„Gdzie wisi” zapisuje worker**, w tej samej transakcji co wynik: sukces = wiersz
  `job_ad_publications` z odciskiem WYSŁANEJ treści, więc poprawka z czasu wysyłki zapala
  „do aktualizacji”. Zamknięcie, 404 i wygaśnięcie = `removed_at`. Dzięki temu lista
  rekrutacji i codzienne przypomnienia nie wymagają zmian.
- **Link z portalu przechodzi `clean_url`.** Adres spoza domeny portalu nie trafia na listę
  rekrutacji jako odnośnik; ogłoszenie zostaje oznaczone bez linku.
- **Bez migracji.** Kolejka to `job_postings`, stan to `job_ad_publications`.
- **Niepotwierdzone na prawdziwym API:** `body` z `<ol>` (etapy procesu; na sandboxie
  29.09.2026 wysyłaliśmy tylko `h3`, `p`, `ul`). Pierwsza publikacja na produkcji to pokaże.
