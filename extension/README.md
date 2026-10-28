# NEXUS — LinkedIn (wtyczka Chrome)

Panel boczny Chrome dla rekruterów: na profilu LinkedIna albo w Recruiterze
pokazuje, czy osoba jest w NEXUSIE, kto ją prowadzi, w jakich jest
rekrutacjach i czy wolno do niej pisać. Dodaje osobę do bazy i do rekrutacji,
pisze szkic wiadomości i zapisuje kontakt.

Czego wtyczka nie robi (decyzje właściciela z 28.10.2026):

- nic nie dokleja do strony LinkedIna — wszystko jest w panelu bocznym,
- czyta stronę tylko przy otwarciu panelu, po przejściu na inną stronę w tej
  karcie albo po kliknięciu „Sprawdź tę stronę”; zawsze jedną stronę naraz,
  nic w tle,
- nie woła wewnętrznego API LinkedIna i nie czyta jego danych z `<code>` w stronie,
- niczego nie wysyła na LinkedInie — tekst wiadomości kopiujesz i wysyłasz sam.

Kontrakt z backendem: [`API.md`](API.md) (trasy `/api/extension/*`, klucz w nagłówku
`X-Extension-Key`).

## Instalacja

**Zespół:** wtyczka jest w Chrome Web Store jako niepubliczna — link dostajesz od
administratora NEXUSA. „Dodaj do Chrome”, potem przypnij ikonę NEXUSA na pasku.

**Wersja deweloperska („Wczytaj rozpakowane”):**

1. `chrome://extensions` → włącz „Tryb dewelopera” (prawy górny róg).
2. „Wczytaj rozpakowane” → wskaż katalog `extension/` z repo.
3. Skopiuj identyfikator wtyczki z karty (32 litery). Backend przekaże klucz
   tylko wtyczce z listy `LINKEDIN_EXTENSION_IDS` — dopisz tam ten identyfikator
   (na produkcji przez workflow „Coolify set env”, lokalnie w `.env` stagingu).
4. Po zmianie plików: ikona odświeżenia na karcie wtyczki w `chrome://extensions`.
   Panel zamknij i otwórz ponownie.

Wymaga Chrome 116 lub nowszego (panel boczny).

## Połączenie z NEXUSEM

1. Otwórz LinkedIna i kliknij ikonę NEXUSA — otworzy się panel.
2. „Zaloguj przez NEXUS” otwiera kartę `<NEXUS>/extension/connect`. Jeśli nie
   jesteś zalogowany w NEXUSIE, zaloguj się tam jak zwykle.
3. Strona NEXUSA przekazuje klucz wtyczce, pokazuje „Połączono” i zamyka się po
   chwili. Panel odświeża się sam.

Klucz leży w `chrome.storage.local` tej przeglądarki. „Odłącz” w menu pod
imieniem usuwa go lokalnie; połączenia unieważnia się też w NEXUSIE
(Ustawienia → Wtyczka LinkedIn). Zmiana roli albo hasła w NEXUSIE odłącza
wtyczkę — panel wraca wtedy do ekranu „Połącz wtyczkę z NEXUSEM”.

Limit odczytów stron LinkedIna na osobę dziennie (licznik w menu) chroni konta
Recruiter przed wyglądem automatu. Profil albo strona wyników = 1 odczyt;
powrót na już sprawdzony profil w ciągu 10 minut nie zużywa odczytu.

## Staging na laptopie

Panel → „Serwer” (link na ekranie połączenia albo w menu) → „Staging na
laptopie”: front `http://localhost:3100`, API `http://localhost:8100`
(`docker-compose.staging.yml`, opis w `docs/claude/podstawy/staging-na-laptopie.md`).
Zmiana serwera odłącza wtyczkę — połącz ją ponownie. Front z gałęzi na porcie
3101 też może przekazać klucz.

## Testy

```sh
cd extension && npm install   # jedna zależność deweloperska: linkedom (DOM w node)
cd .. && node --test extension/test
```

Testy czytników działają na syntetycznych stronach w `test/fixtures/` —
wymyślone osoby i firmy, bo repo jest publiczne. **Nie wklejaj tam zapisanych
stron prawdziwych osób z LinkedIna.**

## Gdy LinkedIn zmieni stronę

Objaw: w panelu przy polu, które na stronie widać, stoi „nie odczytano — wpisz”,
albo lista wyników jest pusta.

1. Na tej stronie LinkedIna: prawy klik na brakującym polu → „Zbadaj”. Zapisz
   tag, klasy i atrybuty `data-*` elementu i jego najbliższego kontenera.
2. Otwórz `src/readers/selectors.js` — wszystkie selektory są tylko tam.
   Dopisz nowy selektor **na początek** listy danego pola; starych nie usuwaj
   (LinkedIn testuje układy A/B, różne osoby widzą różne wersje).
   - profil publiczny: `PROFILE`, sekcje doświadczenia/umiejętności: `SECTIONS`
     i `LIST_ITEMS`,
   - Recruiter: `RECRUITER` (w tym `publicLinkLabels` — teksty linku do profilu
     publicznego),
   - listy wyników i projekt: `RESULTS`,
   - daty i formy zatrudnienia: `MONTHS`, `PRESENT_WORDS`, `EMPLOYMENT_TYPES`.
3. Dodaj fixture w `test/fixtures/` z **samą strukturą** nowego DOM-u i wymyśloną
   treścią oraz test w `test/readers.test.mjs`.
4. `node --test extension/test`, przeładuj wtyczkę w `chrome://extensions`,
   sprawdź na żywej stronie.

Gdy żaden selektor nie trafi, czytnik próbuje heurystyk (imię = pierwszy `h1`
w głównej treści, nagłówek = linia pod imieniem, miasto = linia przed „Dane
kontaktowe”, doświadczenie = lista pod nagłówkiem „Doświadczenie”/„Experience”).
Link do profilu publicznego w Recruiterze bierzemy tylko z karty osoby albo z linku
„Profil publiczny” — nigdy pierwszy lepszy `/in/` ze strony, a slug sprzeczny
z nazwiskiem jest odrzucany.

## Paczka do Web Store

```sh
sh extension/scripts/pack.sh   # → extension/dist/nexus-linkedin-<wersja>.zip
```

ZIP zawiera tylko `manifest.json`, `icons/` i `src/`. Przed wysłaniem podbij
`version` w `manifest.json`.

## Budowa

Bez bundlera: moduły ES, HTML i CSS.

- `src/background.js` — service worker: klik ikony otwiera panel; przyjmuje klucz
  ze strony połączenia (`onMessageExternal`, sprawdza nadawcę, kształt klucza
  i host API).
- `src/panel/` — panel boczny (ekrany w `screen-*.js`).
- `src/page.js` — odczyt aktywnej karty: `chrome.scripting.executeScript`
  oddaje kopię DOM-u (bez skryptów, obrazków i `<code>`), czytniki parsują ją
  w panelu.
- `src/readers/` — czytniki (`profile`, `recruiter-profile`, `search-results`),
  selektory w `selectors.js`.
- `src/api.js` — klient API i mapowanie błędów (401 → połącz ponownie,
  403 → zdanie z NEXUSA, 409 off-limits → pytanie, 429 → limit dzienny).
- `src/view/logic.js` — czysta logika ekranów (testowana w node).

Uprawnienia: `sidePanel` (panel), `storage` (klucz), `scripting` (odczyt karty
LinkedIna na żądanie). Bez `tabs` — adres karty LinkedIna i tak jest widoczny
dzięki `host_permissions`; bez `activeTab` — `host_permissions` na linkedin.com
już pozwala odczytać kartę, więc to uprawnienie niczego by nie dodało.
