# Podgląd na telefonie — `/podglad`, tylko odczyt liczb, praca zostaje na laptopie
<!-- indeks: decyzja Artura 05.11.2026, zakładki pod rolę, kwoty domyślnie ukryte, imię i litera w planie dnia, zakaz zapisów pilnuje test, wejście z pulpitu do 500 px, liczby tylko z tras Insights; od 14.11 „Szukaj” i karta kontaktu kandydata z zapisem otwarcia -->

Decyzja Artura z 05.11.2026 (makiety: https://claude.ai/artifact/DULXvaD1Xn4x2Rs9hiteBM).
Na telefonie nie pracujemy. Telefon służy do sprawdzenia w minutę, jak idą wyniki,
rekrutacje i zespół. Pierwsza propozycja z dzwonieniem, debriefem i wysyłką do klienta
została odrzucona; nie wracaj do niej bez nowej decyzji.

- **Tylko odczyt.** W `app/podglad` i `components/phone-preview` nie ma żadnego zapisu
  ani pobierania plików. Pilnuje `phone-preview-read-only.test.ts`. Akcja dopisana tutaj
  zrobiłaby z podglądu drugie miejsce pracy, więc wymaga decyzji Artura, a nie zmiany testu.
- **Szybki kontakt (decyzja Artura z 14.11.2026, makiety:
  https://claude.ai/artifact/92ANcv9qcsGyPfdu7HYzXH).** Ludzie muszą czasem na szybko
  znaleźć numer kandydata, a droga przez „Pełną wersję” miała ok. 7 kroków. Zakładka
  „Szukaj” (`/podglad/szukaj`) szuka kandydata po imieniu i nazwisku, mailu albo numerze
  (wklejony numer z nieodebranego połączenia mówi, kto dzwonił), do tego kontakty u
  klientów i rekrutacje; najwyżej 5 wyników na grupę, bez przeglądania listy. Karta
  (`/podglad/kandydat/[id]`) ma Zadzwoń, SMS, e-mail, kopiowanie, dostępność, „Stawkę od”,
  rekrutacje z etapem i dwie ostatnie notatki; bez CV, plików i zapisu wyniku rozmowy.
  - Linki `tel:`/`sms:`/`mailto:` są tylko w `components/phone-preview/contact.tsx`.
  - Karta czyta `quick-view?via=phone`, a serwer zapisuje wtedy otwarcie w historii
    kandydata (`candidate_contact_viewed_phone`, bez danych osobowych w `details`), bo
    zgubiony telefon z otwartą sesją daje dostęp do numerów. Bez `via` (laptop) nic się
    nie zapisuje. Samo przeglądanie, więc poza alarmem o pobieraniu (07.11.2026).
  - Zakładkę mają ci, którzy dzwonią do kandydatów (`seesSearch`: rekruter, DL, TCM,
    admin, HoR z sekcją kandydatów); Rada i Finanse nie.
  - Poza zakresem 14.11 (pokazane na makiecie, bez decyzji): „Do oddzwonienia” na Dziś,
    osoby i hiring manager na ekranie rekrutacji, wejście na rozmowę z planu dnia.
- **Zakładki zależą od roli** (`components/phone-preview/access.ts`):
  - Wyniki: Firma (admin, „Wyniki firmy”, Rada), Mój portfel (DL), Mój miesiąc (rekruter).
    Bez tych ról zakładki nie ma i start jest na Zespole (Finanse, HoR bez „Wyniki firmy”).
  - Rekrutacje: swoje dla rekrutera, DL i TCM, wszystkie otwarte dla pozostałych. Rada nie ma.
  - Zespół: cele, tygodnie, w toku; „Do uwagi” tylko z `view_team_kpi` albo dla admina.
  - Dziś: plan dnia, cały zespół dla admina i HoR. Rada i Finanse nie mają.
- **Kwoty firmy ukryte po każdym otwarciu** (oko je pokazuje), bo ekran telefonu bywa
  widoczny dla innych. Stan celowo nie trafia do pamięci przeglądarki. Procenty i liczby
  sztuk są widoczne od razu; zdanie „Jak idzie firma” pomija wtedy kwotę.
- **W planie dnia imię i litera nazwiska** („Piotr K.”), jak w Outlooku przy umówionych
  telefonach. To jedyny ekran z danymi osób; Rekrutacje pokazują same liczby etapów.
- **Liczby wyłącznie z istniejących tras**, bez przeliczania na froncie. Makieta, która
  dodała rezygnacje do odejść, pokazała −16 przy netto +36: `ends` już je zawiera. Reguły
  liczenia są w `finanse-insights/insights-insights-parytet-z-dynareporterem-na.md`.
  Nie dokładaj tu sumy firmy bez `BoardReader` (`uprawnienia/wyniki-firmy-tylko-rada-i-admin.md`).
- **Każda sekcja ładuje się osobno i ma własny stan awarii** (`Loaded`), żeby wolniejsza
  trasa nie trzymała całego ekranu. Awaria nie wygląda jak zero ani pusta lista.
- **Wejście:** `PhonePreviewRedirect` w powłoce przenosi z ekranu startowego (`/dashboard`,
  a Radę z `/insights`) przy szerokości do 500 px. Link z maila otwiera swój ekran, nie
  podgląd. „Pełna wersja NEXUSA” wyłącza przeniesienie do końca sesji przeglądarki.
  Laptop nie zmienia się w niczym. `/podglad` na szerokim ekranie to wąska kolumna.
- **Adres `/podglad`, nie `/m`.** `resolveAccessRule` w `middleware.ts` dopasowuje trasę
  przez `startsWith`, więc reguła `/m` objęłaby `/my-time`, `/marketplace` i `/microsoft365`.
- **Start w NEXUSIE nie blokuje podglądu** (`START_FREE_PREFIXES`): to sam odczyt, a
  przeklikania i tak robi się na laptopie.
- **Bez powłoki aplikacji i bez push.** Pasek górny, dymek Jarvisa i okna „Zmiana w procesie”
  zajmowały telefonowi pół ekranu. Rada ma wpis w `isBoardAllowedPath`.
- **Poza telefonem świadomie:** „Aktywność w NEXUSIE” (imienne dane godzinowe, sygnał do
  rozmowy, nie do zerkania), 17 raportów, Źródła, tabela Finansów ze stawkami, pełne
  profile, Tablica, CV.
