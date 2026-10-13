# Otwarta karta sama przechodzi na nową wersję frontu (12.10.2026)

12.10.2026 Delivery Leadzi tworzyli rekrutacje na ekranie sprzed weekendu,
choć nowy `/jobs/new` był na produkcji od dwóch dni — admin, który odświeżył
stronę, widział już nowy. Serwer miał jedną wersję (jeden kontener frontu),
a ekran nie zależy od roli. Przyczyna leżała w przeglądarce:

- pliki `/_next/static/*` mają `immutable` na rok w przeglądarce i w Cloudflare,
  więc karta otwarta przed wdrożeniem nie dostaje błędu ładowania —
  `lib/chunk-reload.ts` reaguje tylko na brakujący plik i tu nigdy się nie włącza;
- dokument strony nie miał zakazu przechowywania, więc karta przywrócona przez
  Chrome po uruchomieniu brała go z pamięci razem ze starymi plikami;
- aplikacja nie sprawdzała, czy wyszła nowa wersja.

Decyzja Artura z tego dnia: ma się to dziać samo, bez klikania („będą
zapominali, że mają coś kliknąć”).

- **`AppVersionGuard`** (`components/AppVersionGuard.tsx`, w `app/layout.tsx`)
  porównuje SHA wypalony w paczce (`NEXT_PUBLIC_GIT_SHA`) z `/version.json`
  (`lib/app-version.ts`): co minutę, po powrocie do karty i przy zmianie strony.
- **Kartę przeładowuje sam**, gdy nie ma czego stracić: zaraz po otwarciu,
  przy przejściu na inną stronę, gdy karta jest w tle albo po minucie bez
  myszy, klawiatury i przewijania.
- **Nie przeładowuje pod palcami.** Blokują: zmiana pola przez człowieka na tej
  stronie (`beforeinput` albo `input`/`change` do 2 s po geście — pola potrafią
  zmienić się same po doczytaniu danych), otwarte okno modalne
  (`data-scroll-locked` na `body`, `aria-modal`, `alertdialog`) i żądanie inne
  niż GET w toku (licznik na interceptorach `api`). Blokada schodzi przy
  przejściu na inną stronę — wtedy karta przeładowuje się bez pytania. Mały
  komunikat „Wyszła nowa wersja NEXUSA. Wczyta się sama…” jest tylko
  informacją; nikt nie musi go klikać.
- **Najwyżej jedno przeładowanie na wersję serwera** w karcie
  (`sessionStorage`, `reloadOnceForVersion`) — gdyby dokument jednak przyszedł
  stary, zostaje komunikat zamiast pętli.
- **Tylko zalogowani i nie na `/preview/*`.** Strony dla osób z zewnątrz
  (zgłoszenie z linku, podpis, kariera) żyją w tej samej aplikacji; paczka bez
  SHA (lokalnie, testy) nie pyta serwera wcale.
- **Dokument strony ma `Cache-Control: no-store`** (`DOCUMENT_PATHS`
  w `next.config.ts`): odświeżenie, nowa karta i karta przywrócona przez
  przeglądarkę zawsze dostają aktualny dokument. Reguła omija `/_next/` i pliki
  z rozszerzeniem — plikom statycznym roczne `immutable` ma zostać.
- **Poprawki po audycie 13.10.2026 (14.10.2026).** Pobieranie i zapis
  zwykłym `fetch` (poza `api`) też wstrzymują przeładowanie: owijaj je
  w `trackTransfer(() => …)` z `components/AppVersionGuard.tsx` (licznik
  modułu, schodzi także po błędzie; blokuje i spokojną chwilę, i zmianę
  strony). Używa go ZIP z CV (`lib/bulk-cv-download.ts`); audyt pokazał, że
  bez tego przeładowanie mogło przerwać plik. Gdy przeładowanie dla tej wersji
  już było (albo `sessionStorage` jest zablokowany), karta sama się nie
  wczyta — komunikat mówi wtedy „…ta karta nie wczytała jej sama — kliknij
  „Odśwież teraz””, a nie „Wczyta się sama…”, bo ta obietnica była fałszywa.

- Czego nie robić: nie przeładowywać strony, na której ktoś pisze (kasuje
  tekst); nie przechowywać `/version.json` (pytanie idzie z `no-store`
  i parametrem czasu); nie dokładać komunikatu, który wymaga kliknięcia.
- Znane ograniczenie: stan trzymany tylko w pamięci strony, który powstał bez
  żadnej zmiany pola (sam klik) i bez okna, przepadnie przy przeładowaniu po
  minucie spokoju. Nowy ekran z takim stanem powinien trzymać go w adresie
  albo zapisywać.
- Sprawdzenie po wdrożeniu: `curl -sI https://nexus.dynaminds.pl/login | grep -i cache-control`
  → `no-store`. Karty otwarte PRZED wdrożeniem tego mechanizmu nie mają go
  w sobie — potrzebują jednego ręcznego odświeżenia.
