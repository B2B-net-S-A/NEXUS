# Strona kariery dla kandydatów (kariera.dynaminds.pl, 0339, 22.09.2026)

Publiczny landing, który rekruterzy wrzucają na LinkedIna. Raport:
`docs/career-landing-completion-report.md`. Dwa rodzaje linku w
`candidate_invite_links` (`kind`):
- **`job`** — `/r/<slug>`: opis publiczny rekrutacji + formularz; kandydat
  trafia na etap „Nowy” tej rekrutacji po przeglądzie AI (0404 — sekcja
  „Zgłoszenia z linku rekrutacji przegląda AI” wyżej). Domyślnie **bez terminu** — ważny, póki
  rekrutacja jest otwarta (zamknięta = strona „proces zakończony” z odesłaniem
  do stałego linku rekrutera; stare `/apply/{token}` też dają wtedy 404).
- **`recruiter`** — `/<slug>` (np. `/marta-n`): stały link do bazy, jeden
  aktywny na osobę (częściowy UNIQUE). Bez rekrutacji: brak `open_process`,
  `CandidateSourceEvent.job_id = NULL`, osoba **przypięta w „Moich ludziach”**
  właściciela linku (`my_people` nie czyta `created_by`).

Reguły, które łatwo cofnąć:
- **Na stronę trafia wyłącznie zatwierdzony opis publiczny**
  (`job_public_profiles`, status liczony z hasha treści — edycja po zatwierdzeniu
  = szkic). Niezatwierdzony profil = 404. Publiczne GET-y budują odpowiedź z
  białej listy (`services/job_public_profile.py`): **nigdy klient, stawka,
  budżet ani nazwisko rekrutera** (tylko imię). Pilnuje test kształtu odpowiedzi.
- **Kontrola przed publikacją jest deterministyczna**
  (`services/public_profile_lint.py`): nazwa i aliasy klienta, kwoty, kontakty,
  nazwiska. `approve` odmawia 422 `PUBLIC_PROFILE_FINDINGS`. Szkic AI
  (`AIFeatureKey.job_public_description`, Sonnet 5) jest tylko podpowiedzią —
  nie zapisuje się sam i nie omija kontroli. Kontrola skanuje też tytuł
  rekrutacji: klient w tytule blokuje publikację.
- **Zgoda jest wymagana na OBU formularzach** (nowym i starym `/apply/{token}`),
  zapis w `candidate_consents` w tej samej transakcji (tekst + wersja + sha256,
  `services/career_consent.py`; administrator B2B.NET S.A.). Zmiana treści zgody
  = nowa wersja, nigdy edycja w miejscu. FK CASCADE z kandydatem i ze zgłoszeniem
  (art. 17 RODO).
- **Jedna ścieżka zapisu zgłoszenia:** `services/public_apply.submit_application`
  (stary i nowy endpoint). Duplikat e-maila (od 22.09.2026, decyzja Artura —
  kolejka `/applications` przez całe życie nie dostała ani jednego wpisu) NIE
  czeka na decyzję: pola profilu nietknięte (P0-CAND-01), CV dochodzi jako
  dodatkowy, NIE główny dokument, link rekrutacji otwiera proces „Nowy”,
  stały link przypina w „Moich ludziach”; globalna czarna lista = sam
  dokument, bez procesu. `ApplicationSubmission` zostaje jako zapis
  (`linked`, zgoda, pola opcjonalne w `raw_payload`), powiadomienie linkuje
  do profilu. „Zgłoszenia” zdjęte z menu i ⌘K; strona i resolver zostają dla
  starych wierszy i linków z powiadomień.
  Pułapka na boty `website` = cichy 201 bez zapisu. `new_application` do
  właściciela linku po commicie.
- **Routing po hoście** (`middleware.ts`, env `NEXT_PUBLIC_CAREER_HOST`): na
  domenie kariery nie działa żadna logika logowania, dozwolone są tylko `/`,
  `/r/*`, `/rodo`, `/<slug>`, `/kariera/*` i `/_next`; reszta = 404. Pusta
  zmienna = routing wyłączony, strona żyje pod `/kariera/*` na hoście aplikacji
  (publiczna ścieżka) i tam prowadzą linki (`career_base_url()` bez
  `CAREER_PUBLIC_BASE_URL` = `PUBLIC_BASE_URL/kariera`). `AppShellV2` renderuje
  gołą stronę po segmencie `kariera` — po rewrite `usePathname()` zwraca adres
  widoczny, nie wewnętrzny.
- **Fonty strony kariery (Geist, JetBrains Mono) są lokalne** i ładowane tylko w
  jej layoucie; grafiki OG czytają TTF przez `fs`, stąd
  `outputFileTracingIncludes` w `next.config.ts` (obraz standalone).
- Klauzula `/kariera/rodo`: kontakt rodo@b2bnetwork.pl, okres przechowywania
  3 lata od zgłoszenia lub do cofnięcia zgody (decyzja Artura 27.09.2026, F16).
- Aktywacja domeny: rekord DNS `kariera` w Cloudflare → serwer NEXUSA, domena
  w Coolify dla serwisu frontend, env `NEXT_PUBLIC_CAREER_HOST` (build arg),
  `CAREER_PUBLIC_BASE_URL` i `CORS_ORIGINS` + `https://kariera.dynaminds.pl`.
