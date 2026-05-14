# NEXUS — wtyczka Chrome "Dodaj z LinkedIn"

Manifest V3, vanilla JS, brak buildu. Działa load-unpacked, do Chrome Web Store
dystrybucja TODO.

## Co robi

Na profilu LinkedIn (`https://www.linkedin.com/in/*`) wyświetla pływający
przycisk **+ NEXUS**. Klik → otwiera się modal w-stronie (Shadow DOM) z:

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

## Limitacje (znane)

- **Ikony** są minimalne (solid violet + literka N) — wystarczające dla MVP, do
  Chrome Web Store potrzebny normalny brand asset.
- **Brak quick-add** (silent batch) — świadoma decyzja, mniej śmieci w bazie.
- **Selektory LinkedIn DOM** rotują — gdy preview puste, server (Proxycurl)
  i tak pociągnie pełne dane. Selektory są w `src/content/linkedin-scraper.js`.
- **JWT NIE szyfrowany** w `chrome.storage.local` (acceptable dla internal tool).
- **Brak Sentry** w extension (TODO — można dorzucić `@sentry/browser` standalone).

## Dystrybucja

MVP: load-unpacked dla Artura (+ ew. zespołu).

Chrome Web Store TODO:
- ✏️ Privacy policy URL (`nexus.dynaminds.pl/legal/extension-privacy`)
- ✏️ Justification dla każdego `host_permission`
- ✏️ Screenshoty (1280×800)
- ✏️ Promo tile (440×280)
- ✏️ Płatność $5 jednorazowa za konto deweloperskie
- ⏱ Review ~3 dni roboczych
