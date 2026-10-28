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

**Zespół:** docelowa dystrybucja to Chrome Web Store jako niepubliczna (Unlisted).
Publikacja i przydzielenie identyfikatora sklepu są jeszcze do wykonania;
po publikacji link dostaniesz od administratora NEXUSA. Wtedy wybierz
„Dodaj do Chrome” i przypnij ikonę NEXUSA na pasku.

Polityka prywatności: [NEXUS — wtyczka](https://nexus.b2bnetwork.pl/wtyczka/prywatnosc).
Strona jest przygotowywana w tym samym wydaniu co materiały sklepu;
przed publikacją administrator sprawdza jej dostępność bez logowania.

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

## Jak wtyczka czyta stronę

Od 2025 LinkedIn ma haszowane klasy CSS (zmieniają się przy wydaniach), nie ma
`h1` ani list `ul/li` w sekcjach profilu. Dlatego główna ścieżka nie używa klas:

1. Panel wstrzykuje do karty jedną funkcję (`capturePage` w `src/page.js`). Na
   profilu przewija kontener strony krokami 600 px co 300 ms (razem najwyżej 4 s),
   bo sekcje doładowują się dopiero po przewinięciu, i wraca na miejsce.
2. Funkcja zbiera `innerText` żywej strony (podział na linie wynika z układu):
   imię z pierwszego `h2` w `main`, linie karty górnej, każdą `section` z jej
   nagłówkiem i pozycjami (doświadczenie: pozycje rozdzielone `hr[role=presentation]`),
   pozycje listy wyników (`[role=list] [role=listitem]`) i linki `/in/`.
3. Czytniki w `src/readers/text.js` rozpoznają pola po kolejności linii
   i słowach stałych, np. miasto = linia przed „Contact info”, nagłówek =
   pierwsza linia po imieniu, która nie jest szumem („She/Her”, „· 2nd”).
4. Kopia HTML (bez skryptów, obrazków i bloków `<code>`) jedzie obok jako zapas:
   czytniki starszego układu (`profile.js`, `recruiter-profile.js`,
   `search-results.js`) uzupełniają tylko puste pola i tylko wtedy, gdy rozpoznały
   tę samą osobę. W Recruiterze zrzut HTML ogranicza się do wybranego profilu
   i jawnie powiązanego panelu linku publicznego; tło wyników nie identyfikuje osoby.

Zmierzone na żywym LinkedInie 28.10.2026 (interfejs po angielsku): profil `/in/`
i lista wyników wyszukiwania osób. Tego dnia zmierzono też **aktywny
LinkedIn Recruiter**: trzy wiersze wyników i dwa układy profilu (panel boczny
oraz osobna strona `/talent/profile/…`). W obu układach sprawdzono obecność
imienia i nazwiska, nagłówka, lokalizacji, pozycji doświadczenia i umiejętności.
Pomiar wykrył, że przed imieniem w wierszu występuje kontrolka „Select …”,
a panel profilu leży poza główną sekcją strony z listą wyników. Wersja **1.0.1**
wprowadza poprawki czytnika dla tych struktur. W repo są wyłącznie syntetyczne
fixture’y; rzeczywiste nazwiska i treść profili nie są materiałem testowym.

Pomiar rzeczywistej strony i lokalny test instalacji ZIP-a są osobnymi etapami.
Nie potwierdzają pełnej ścieżki zainstalowanej wtyczki z kontem rekrutera i API
produkcyjnym. Przed uznaniem wydania za gotowe trzeba sprawdzić pola w panelu
na rzeczywistym Recruiterze oraz połączenie z NEXUSEM.

## Gdy LinkedIn zmieni stronę

Objaw: w panelu przy polu, które na stronie widać, stoi „nie odczytano — wpisz”,
albo lista wyników jest pusta.

1. Na tej stronie LinkedIna otwórz DevTools (F12) → Console i wpisz
   `document.querySelector("main section").innerText` (karta górna) albo
   `[...document.querySelectorAll("main section")].map(s => s.innerText)`.
   Zobaczysz linie dokładnie tak, jak widzi je czytnik.
2. Otwórz `src/readers/selectors.js` — wszystko, co czytnik rozpoznaje, jest tam:
   - nowa linia-przycisk albo plakietka myli nagłówek/miasto → dopisz wzorzec
     do `NOISE_LINES`,
   - sekcja ma inną nazwę → `SECTION_HEADINGS`,
   - „Contact info” po nowemu → `CONTACT_INFO`,
   - lista wyników ma inne role → `CAPTURE.listItems`,
   - daty i formy zatrudnienia → `MONTHS`, `PRESENT_WORDS`, `EMPLOYMENT_TYPE_WORDS`.
   Klasy CSS na dole pliku to tylko zapas starszego układu.
3. Dodaj zrzut w `test/fixtures/text/` (JSON z liniami jak w kroku 1, ale
   z **wymyślonymi** osobami i firmami) i test w `test/text-readers.test.mjs`.
4. `node --test extension/test`, przeładuj wtyczkę w `chrome://extensions`,
   sprawdź na żywej stronie.

## Paczka do Web Store

```sh
sh extension/scripts/pack.sh   # → extension/dist/nexus-linkedin-<wersja>.zip
```

ZIP zawiera tylko `manifest.json`, `icons/` i `src/`. Przed wysłaniem podbij
`version` w `manifest.json`, jeśli sklep otrzymał już tę wersję.
Skrypt wymaga zainstalowanych zależności testów i zielonego wyniku testów;
zapisuje też sumę SHA-256 ZIP-a.

Gotowe teksty formularza, uzasadnienia uprawnień i instrukcje do recenzji:
[`docs/linkedin-extension-webstore.md`](../docs/linkedin-extension-webstore.md).
Zrzuty sklepu na fikcyjnych danych: `node extension/scripts/store-screenshots.mjs`
(z katalogu repozytorium; wymaga istniejącej zależności Playwright frontendu).
Generator renderuje rzeczywiste komponenty panelu w rozmiarze 1280×800;
nie zastępuje sprawdzenia czytnika na żywym Recruiterze.

## Budowa

Bez bundlera: moduły ES, HTML i CSS.

- `src/background.js` — service worker: klik ikony otwiera panel; przyjmuje klucz
  ze strony połączenia (`onMessageExternal`, sprawdza nadawcę, kształt klucza
  i host API).
- `src/panel/` — panel boczny (ekrany w `screen-*.js`).
- `src/page.js` — odczyt aktywnej karty: `chrome.scripting.executeScript`
  z funkcją `capturePage`, która oddaje zrzut tekstu i kopię HTML (zapas).
- `src/readers/` — czytniki zrzutu tekstu (`text.js`), czytniki HTML starszego
  układu (zapas), łączenie w `index.js`, wszystkie wzorce w `selectors.js`.
- `src/api.js` — klient API i mapowanie błędów (401 → połącz ponownie,
  403 → zdanie z NEXUSA, 409 off-limits → pytanie, 429 → limit dzienny).
- `src/view/logic.js` — czysta logika ekranów (testowana w node).

Uprawnienia: `sidePanel` (panel), `storage` (klucz), `scripting` (odczyt karty
LinkedIna na żądanie). Bez `tabs` — adres karty LinkedIna i tak jest widoczny
dzięki `host_permissions`; bez `activeTab` — `host_permissions` na linkedin.com
już pozwala odczytać kartę, więc to uprawnienie niczego by nie dodało.

Wersja **1.0.2** usuwa dekoracyjny separator przed lokalizacją w topcardzie
Recruitera, zachowując wewnętrzną interpunkcję nazw miejsc.
