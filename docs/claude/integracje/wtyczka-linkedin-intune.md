# Wtyczka LinkedIn przez Intune — polityka Chrome i własny .crx (29.10.2026)
<!-- indeks: decyzje Artura 29.10, ExtensionInstallForcelist pmnon…;update.xml, .crx podpisany tylko na laptopie Artura, pilot 2–3 osoby, warunki Chrome dla wtyczki spoza sklepu, współistnienie z ZIP-em i sklepem -->

Trzecia droga instalacji wtyczki „NEXUS — LinkedIn” (obok ZIP-a z `/wtyczka`
i Chrome Web Store, opis w `wtyczka-linkedin.md`). Intune wymusza wtyczkę
w Chrome na laptopach zespołu: nie trzeba trybu dewelopera, a aktualizacje
przychodzą same z NEXUSA.

## Decyzje Artura z 29.10.2026

- **Laptopy:** zespół pracuje na firmowych laptopach z Windows w Intune.
- **Od razu `.crx` z NEXUSA,** bez czekania na recenzję sklepu. Intune wymusza
  id zespołu `pmnonjpommkjblgacmpaclgacjmipplm` (pole `key` w manifeście),
  a nie id sklepu `iaajabmhhcchodnkkgdffclgihdeipmo`.
- **Klucz prywatny tylko na laptopie Artura**
  (`~/.config/nexus/linkedin-extension-team.pem`). Nie trafia do repo, do
  sekretów GitHuba ani do Actions.
- **Najpierw pilot na 2–3 osobach,** potem cały zespół.

## Dlaczego to zadziała (warunki Chrome)

- Polityka `ExtensionInstallForcelist`: wpis `<id>;<adres update.xml>`. Adres
  z polityki służy tylko do pierwszej instalacji. Kolejne wersje Chrome bierze
  z `update_url` w manifeście wtyczki, więc `.crx` musi go mieć (dodaje go
  `pack.sh`). Źródło: opis polityki w Chromium,
  [`ExtensionInstallForcelist.yaml`](https://chromium.googlesource.com/chromium/src/+/main/components/policy/resources/templates/policy_definitions/Extensions/ExtensionInstallForcelist.yaml).
- **Windows:** wtyczkę spoza sklepu Chrome wymusi tylko na urządzeniu
  dołączonym do AD albo Entra ID, zapisanym w MDM (Intune) albo zapisanym
  w Chrome Enterprise Core. Na innych komputerach, np. prywatnych albo tylko
  „zarejestrowanych” w Entra bez Intune, polityka zmienia się w zwykłe „wolno
  zainstalować”. Wtyczka się wtedy nie pojawi. Kod:
  [`extension_management.cc`](https://chromium.googlesource.com/chromium/src/+/main/chrome/browser/extensions/extension_management.cc)
  (`IsLowTrustEnforcementActive`),
  [`platform_management_status_provider_win.cc`](https://chromium.googlesource.com/chromium/src/+/main/components/policy/core/common/management/platform_management_status_provider_win.cc)
  i [`management_service.cc`](https://chromium.googlesource.com/chromium/src/+/main/components/policy/core/common/management/management_service.cc).
  Zapis w MDM ma poziom `TRUSTED`, a dołączenie do Entra `FULLY_TRUSTED`.
  Windows Home się nie liczy (`IsDeviceRegisteredWithManagement` w
  [`win_util.cc`](https://chromium.googlesource.com/chromium/src/+/main/base/win/win_util.cc)).
- **macOS:** tylko urządzenie w MDM (profil konfiguracyjny `com.google.Chrome`).
  Dziś nie dotyczy, bo zespół pracuje na Windows.
- **Intune → Chrome:** ustawienia Chrome są wbudowane w katalog ustawień
  (Settings catalog), więc ADMX od Google nie trzeba importować
  ([Microsoft: wspólne zadania w katalogu ustawień](https://learn.microsoft.com/en-us/intune/device-configuration/settings-catalog/common-tasks),
  [import ADMX](https://learn.microsoft.com/en-us/intune/device-configuration/settings-catalog/import-custom-admx-templates)).
  Google pisze, że w katalogu jest tylko podstawowy zestaw ustawień Chrome
  ([Google: Chrome w Intune](https://support.google.com/chrome/a/answer/9102677)).
  `ExtensionInstallForcelist` jest wśród nich. Jeśli w danej dzierżawie go
  brakuje, zostaje import ADMX z tej strony Google.
- **Hosting:** `frontend/public/wtyczka/update.xml` i `nexus-linkedin.crx`
  idą pod `https://nexus.b2bnetwork.pl/wtyczka/…` bez logowania, bo matcher
  middleware pomija ścieżki z kropką (`frontend/src/middleware.ts`, `matcher`).
  Aktualizator wtyczek Chrome nie sprawdza Content-Type, więc wystarczy
  `application/octet-stream` z `nosniff` z Next.js: w
  [`extension_downloader.cc`](https://chromium.googlesource.com/chromium/src/+/main/extensions/browser/updater/extension_downloader.cc)
  nie ma sprawdzania typu. Typ `application/x-chrome-extension` jest
  potrzebny tylko przy instalacji kliknięciem
  ([Google: hosting poza sklepem](https://developer.chrome.com/docs/extensions/how-to/distribute/host-on-linux)).

## Co jest w repo

`sh extension/scripts/pack.sh` robi trzy paczki z tych samych plików:

1. ZIP zespołu `frontend/public/wtyczka/nexus-linkedin.zip` (bez zmian, #2798),
2. paczkę do sklepu w `extension/dist/` (bez `key`, nie commitujemy),
3. **`frontend/public/wtyczka/nexus-linkedin.crx` i `update.xml`**. Pakuje
   sam Chrome (`--pack-extension` na osobnym profilu). Manifest to manifest
   ZIP-a zespołu plus
   `"update_url": "https://nexus.b2bnetwork.pl/wtyczka/update.xml"`.
   `update.xml` niesie wersję i `prodversionmin` z manifestu. Klucz:
   `NEXUS_EXTENSION_PEM`, domyślnie plik na laptopie Artura. Chrome przyjmuje
   tylko PKCS#8, więc skrypt robi kopię w katalogu tymczasowym (0600)
   i kasuje ją zaraz po pakowaniu. Bez klucza krok jest pomijany.

Ten sam kod daje ten sam `.crx`: podpis RSA PKCS#1 v1.5 nie ma losowości,
a pliki mają stałą datę. Sprawdzone 29.10: dwa przebiegi dały ten sam SHA-256.
Dlatego commit `.crx` zmienia się tylko przy zmianie kodu.

`extension/scripts/crx3.mjs` rozbiera CRX3, sprawdza podpis i liczy id.
Na `.crx` z Chrome daje `pmnon…`. Uszkodzony bajt kończy się błędem „podpis się
nie zgadza”, a obce id kodem wyjścia 1. Test `extension/test/team-crx.test.mjs`
(CI, krok „Wtyczka LinkedIn — testy”) pilnuje czterech rzeczy: podpis kluczem
z pola `key`, pliki zgodne z `extension/`, manifest z `update_url` oraz
`update.xml` z wersją z manifestu. Zapomniany `pack.sh` z kluczem = czerwone
CI, a nie laptopy po cichu na starej wersji.

Baner „Jest nowa wersja” w panelu (`updateNotice`) nie pokazuje się, gdy
manifest ma `update_url` (`.crx` z polityki albo wersja ze sklepu). Takie
wtyczki Chrome aktualizuje sam, a link do ZIP-a tylko by mylił.

## Klucz prywatny

- Kto ma klucz, ten podpisze wersję z dowolnym kodem. Wtyczka czyta LinkedIna
  i trzyma klucz `nxe_` osoby. Dlatego klucz nie trafia do Actions: repo
  i logi są publiczne, a sekret w workflow podpisałby kod każdego, kto zmieni
  workflow na main.
- Wypchnięcie takiej wersji wymagałoby też podmiany `update.xml` na
  `nexus.b2bnetwork.pl`, czyli wejścia do repo i wdrożenia. Sam klucz to
  jeszcze nie dostęp do laptopów zespołu.
- **Kopia w menedżerze haseł** (do zrobienia przez Artura). Utrata klucza
  oznacza nowe id: nowy wpis w polityce, `LINKEDIN_EXTENSION_IDS` przez
  „Coolify set env” i ponowne połączenie każdej osoby.
- Wyciek: nowy klucz → nowe id → nowe pole `key`, nowa polityka i nowy env.
  Stare id usunąć z `LINKEDIN_EXTENSION_IDS`, żeby podpisana nim wtyczka nie
  dostała klucza NEXUSA.

## Krok po kroku

### Repo (sesja Claude'a albo Codex, na laptopie Artura)

1. Scalić #2798 (ZIP zespołu i pole `key`), potem PR z `.crx` (draft, czeka
   na Artura).
2. Po wdrożeniu (okno pon–pt 18:00–08:00): `/api/health` → `version` = SHA
   z maina oraz
   `curl -sI https://nexus.b2bnetwork.pl/wtyczka/update.xml` i
   `…/nexus-linkedin.crx` → `200`.
3. Id `pmnon…` jest już na `LINKEDIN_EXTENSION_IDS` (#2798), więc env się
   nie zmienia.

### Intune (Artur, intune.microsoft.com)

0. **Sprawdzenie sprzętu:** Devices → Windows → kolumny „Join type” (Microsoft
   Entra joined / hybrid joined) i „OS”. Każdy laptop z pilota musi być
   joined, z Windows Pro albo Enterprise, i mieć Chrome 116 lub nowszy.
1. **Grupa:** Entra ID → Groups → nowa grupa zabezpieczeń „NEXUS wtyczka —
   pilot”: Artur i 1–2 rekruterów.
2. **Profil:** Devices → Configuration → Create → New policy → Windows 10 and
   later → Settings catalog. Nazwa „Chrome — wtyczka NEXUS”. Add settings →
   szukaj „force-installed” → Google Chrome → Extensions → **Configure the
   list of force-installed apps and extensions** → Enabled, jedna wartość:

   ```
   pmnonjpommkjblgacmpaclgacjmipplm;https://nexus.b2bnetwork.pl/wtyczka/update.xml
   ```

   W tym samym profilu, zalecane: **Configure extension installation
   blocklist** → `iaajabmhhcchodnkkgdffclgihdeipmo` (id sklepu). Bez blokady
   osoba, która doda wtyczkę ze sklepu, ma dwie wtyczki NEXUSA. Każde
   połączenie odwołuje poprzednie (`wtyczka-linkedin.md`), więc wtyczki
   wylogowują się nawzajem.
3. **Przydział:** Assignments → grupa pilota. Profil ustawia politykę
   urządzenia (HKLM), więc przy przydziale do grupy osób trafia na urządzenia
   tych osób.
4. **Sprawdzenie na laptopie z pilota:** Portal firmy → Synchronizuj (albo
   odczekać), potem `chrome://policy` → „Ponownie wczytaj zasady”.
   `ExtensionInstallForcelist` ma stan OK, w `chrome://extensions` jest
   „NEXUS — LinkedIn” z „Zainstalowane przez administratora”, a id to
   `pmnon…`. Panel → „Zaloguj przez NEXUS”. Zrzut z każdego kroku do wątku.
5. **Po dniu bez problemów:** dodać przydział grupy rekruterów. Tryb
   dewelopera można wtedy wyłączyć (na pilocie najpierw sprawdzić, czy nie
   wyłącza go już inna polityka).

**Cofnięcie:** usunięcie przydziału albo profilu. Chrome sam odinstaluje
wtyczkę (opis polityki), a z nią klucz z `chrome.storage.local`. Połączenie
w NEXUSIE odłącza admin w Ustawieniach → Integracje → Wtyczka LinkedIn.

### Wydanie nowej wersji (po wejściu polityki)

Jak w `extension/README.md` → „Wydanie nowej wersji”, z jednym warunkiem:
`pack.sh` uruchamia się na laptopie Artura, bo tam jest klucz. Commit niesie
ZIP, `.crx` i `update.xml`. Laptopy dostają wersję po wdrożeniu (okno
18:00–08:00), gdy Chrome sprawdzi aktualizacje, co robi co kilka godzin.
Od razu: `chrome://extensions` → tryb dewelopera → „Aktualizuj”.

## Współistnienie z ZIP-em i ze sklepem

- **Wersja rozpakowana z ZIP-a ma to samo id `pmnon…`.** Wtyczka z polityki
  ma wyższy priorytet: `GetLocationRank` w
  [`manifest.cc`](https://chromium.googlesource.com/chromium/src/+/main/extensions/common/manifest.cc)
  daje `kExternalPolicyDownload` 6, a `kUnpacked` 4. Chrome podmienia więc
  rozpakowaną wersję na `.crx`. Niepotwierdzone: czy klucz NEXUSA
  w `chrome.storage.local` przetrwa podmianę. W najgorszym razie panel
  pokaże „Połącz wtyczkę z NEXUSEM”, a połączenie to jedno kliknięcie.
  Sprawdzić na pilocie, przed i po synchronizacji.
- **Wersja ze sklepu (`iaaj…`) to inne id.** Na laptopach z polityką blokuje
  ją blocklist (krok 2). Jeśli Google przyjmie wtyczkę, sklep zostaje dla
  osób spoza Intune. Wymuszenie przez Intune można wtedy przepiąć na id
  sklepu (sam wpis `iaaj…`, bez adresu), ale to osobna decyzja.
- **Osoby spoza Intune** (gdyby się pojawiły): ZIP z `/wtyczka` albo sklep.
  Polityka ich nie dotyczy.

## Do sprawdzenia na pilocie

- Instalacja `.crx` z polityki na prawdziwym laptopie z Intune. W tej sesji
  sprawdzone są format i podpis (`crx3.mjs` na pliku z Chrome), a nie
  instalacja.
- Czy Chrome pokazuje przy wtyczce ostrzeżenie „nie pochodzi z Chrome Web
  Store” i czy coś ono blokuje. W marcu 2024 zgłaszano takie ostrzeżenie dla
  wtyczek z własnym hostingiem
  ([chromium-extensions](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/wp4A-6NC2QY)).
- Czy klucz NEXUSA przetrwa podmianę wersji rozpakowanej (wyżej).
