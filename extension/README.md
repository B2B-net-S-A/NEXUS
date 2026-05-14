# NEXUS — wtyczka Chrome "Dodaj z LinkedIn" (v0.2.0)

Manifest V3, vanilla JS, brak buildu. Działa load-unpacked, do Chrome Web Store
dystrybucja TODO.

## Co robi

Na **trzech surface'ach LinkedIn**:
- Publiczny profil — `https://www.linkedin.com/in/<slug>`
- **Sales Navigator** — `https://www.linkedin.com/sales/lead/...`, `/sales/people/...`
- **LinkedIn Recruiter** — `https://www.linkedin.com/talent/profile/...`, `/talent/people/...`

…wyświetla pływający przycisk **+ NEXUS**. Klik → otwiera się modal w-stronie (Shadow DOM) z:

- preview kandydata (imię, headline, lokalizacja, firma — wyciągnięte z DOM),
- search-as-you-type rekrutacji z NEXUS (dropdown z aktywnymi job postings),
- wybór etapu startowego (new / prep_call / screening / interview),
- pole tagów + notatka,
- przycisk **Dodaj do NEXUS**.

Backend wzywa `POST /api/candidates/from-linkedin`:
- jeśli profil już jest w bazie → modal pokaże "Już w bazie" + button **Odśwież z LinkedIn** (uderza `POST /api/candidates/{id}/sync-linkedin`),
- jeśli nowy → tworzy stub kandydata + odpala Proxycurl enrichment w tle (w
  ciągu ~30s pole `linkedin_sync_status` przejdzie na `ok` i UI pokaże pełne
  dane).

## Instalacja (load-unpacked)

1. Otwórz `chrome://extensions`
2. Włącz **Tryb dewelopera** (toggle w prawym górnym rogu)
3. Kliknij **Wczytaj rozpakowane** (Load unpacked)
4. Wybierz katalog `extension/` z tego repo
5. Kliknij ikonę NEXUS w toolbarze → otworzy się strona Ustawienia
6. Zaloguj się swoim emailem + hasłem NEXUS
7. (Opcjonalnie) zmień Backend URL na `http://localhost:8000` jeśli testujesz
   przeciw lokalnemu `docker compose up`

## Architektura

```
extension/
├── manifest.json
├── icons/
│   └── icon-{16,32,48,128}.png
└── src/
    ├── background/
    │   └── service-worker.js     # JWT, refresh, central fetch
    ├── content/
    │   ├── content-script.js     # FAB injection + MutationObserver
    │   ├── modal-host.js         # Shadow DOM modal
    │   ├── linkedin-scraper.js   # DOM extraction with fallbacks
    │   └── modal.css             # Linear theme (violet + zinc)
    ├── options/
    │   ├── options.html          # login + backend URL
    │   ├── options.js
    │   └── options.css
    └── shared/
        ├── messages.js           # MSG_TYPE constants
        ├── storage.js            # chrome.storage.local wrappers
        └── api-client.js         # fetch + 401 refresh
```

Komunikacja: content-script ↔ background service worker przez
`chrome.runtime.sendMessage`. Background SW jest jedynym kontekstem który robi
`fetch()` do NEXUS API — JWT nigdy nie wycieka do content scripta. Token w
`chrome.storage.local`.

## Smoke-test checklist (12 punktów)

Po `Wczytaj rozpakowane`:

1. **Options page** otwiera się po kliknięciu ikony w toolbarze, formularz login zsumitowany jednorazowo
2. **FAB** pojawia się prawym-dolnym rogu na `linkedin.com/in/<dowolny>`
3. **SPA navigation** — klikam inny profil bez full reload, FAB re-appears
4. **Preview** — modal pokazuje wyciągnięte imię, headline, lokalizację
5. **Job search** — wpisuję "Senior", po 300ms widzę dropdown z rekrutacjami
6. **Stage select** — disabled dopóki nie wybiorę rekrutacji, potem aktywuje się
7. **Submit (new)** — toast "Dodano X" + link do `/candidates/{id}`
8. **Submit (existing)** — drugi raz ten sam profil → "Już w bazie" + button "Odśwież z LinkedIn"
9. **Re-sync** — klik "Odśwież" wywołuje `/sync-linkedin`, button zmienia się na "Zsynchronizowano ✓"
10. **401 refresh** — ręcznie skoruptuj `access_token` w `chrome.storage`, submit działa silent refresh
11. **No-auth** — wipe storage, modal pokazuje "Zaloguj się"
12. **Network down** — stop backend, submit → "Błąd: Network error"

## Co nowego w v0.2.0

- **Sales Navigator support** — wtyczka działa na `linkedin.com/sales/lead/<id>` i `linkedin.com/sales/people/<id>`. Scraper czyta dane z DOM Sales Nav (selektory `data-anonymize`) i wyciąga canonical `/in/<slug>` URL z elementu "Public profile" w panelu profilu.
- **LinkedIn Recruiter support** — analogicznie dla `linkedin.com/talent/profile/<id>` i `/talent/people/<id>`. ⚠ **Risk Recruiter ToS:** używaj manualnie, nie batch; LinkedIn monitoruje konta Recruiter agresywniej niż zwykłe.
- **Sentry integration** — minimal client (zero deps, MV3 CSP-safe, bez CDN load). Wklej DSN w options page → błędy wtyczki trafią do Sentry projektu `nexus-extension`. Domyślnie disabled.
- **Pre-fill jobs z otwartych kart NEXUS** — jeśli masz otwarte `nexus.dynaminds.pl/jobs/<id>` w innej karcie, modal pokazuje chips "Otwarte rekrutacje" nad job-search inputem. Jedno kliknięcie pre-filluje dropdown bez wpisywania.
- **Backend dedup performance** — migracja Alembic 0106 dodaje `linkedin_slug` GENERATED column + index. Dedup query z `LIKE '%slug%'` na full-table-scan → exact match na indexed column (O(log n)).

## Risk Recruiter ToS — przeczytaj

LinkedIn Recruiter to płatny enterprise tier (~150 USD/seat/mc). LinkedIn
**aktywnie monitoruje** konta Recruiter pod kątem automation / scraping i
agresywnie banuje konta. Nasza wtyczka **nie wykonuje żadnych masowych akcji**,
nie scrolluje listy, nie wysyła InMail, nie wykonuje akcji w Twoim imieniu —
tylko czyta DOM aktualnie otwartego profilu który Ty kliknąłeś. To bardzo
niski risk, ale risk niezerowy.

**Best practices:**
- Używaj manualnie, jeden profil naraz (NIE batch loop).
- Nie zostawiaj wtyczki uruchomionej kiedy nie jesteś przy klawiaturze.
- Po dodaniu kandydata zamknij modal i poczekaj kilka sekund zanim klikniesz "+" na następnym profilu.
- Jeśli LinkedIn pokaże CAPTCHA lub komunikat o nietypowej aktywności — natychmiast przestań i zaczekaj 24h.

Oficjalna integracja byłaby przez LinkedIn Talent Solutions Partner Program
(Recruiter System Connect / RSC) — ~6-12 miesięcy procesu certyfikacji, revenue
share, minimum customer base. Nie dla solo-ATS.

## Limitacje (znane)

- **Ikony** są minimalne (solid violet + literka N) — wystarczające dla MVP, do
  Chrome Web Store potrzebny normalny brand asset.
- **Brak quick-add** (silent batch) — świadoma decyzja, mniej śmieci w bazie.
- **Selektory LinkedIn DOM** rotują — gdy preview puste, server (Proxycurl)
  i tak pociągnie pełne dane. Selektory są w `src/content/linkedin-scraper.js`.
- **JWT NIE szyfrowany** w `chrome.storage.local` (acceptable dla internal tool).
- **Race condition na dedup** — dwa równoczesne kliknięcia w tym samym czasie =
  2 duplikaty (theoretical for solo-recruiter). Phase 3 follow-up: candidate
  merge UI + partial unique index.

## Dystrybucja

MVP: load-unpacked dla Artura (+ ew. zespołu).

Chrome Web Store TODO:
- ✏️ Privacy policy URL (`nexus.dynaminds.pl/legal/extension-privacy`)
- ✏️ Justification dla każdego `host_permission`
- ✏️ Screenshoty (1280×800)
- ✏️ Promo tile (440×280)
- ✏️ Płatność $5 jednorazowa za konto deweloperskie
- ⏱ Review ~3 dni roboczych
