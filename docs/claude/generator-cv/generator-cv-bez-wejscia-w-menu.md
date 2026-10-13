# Generator CV bez wejścia w menu (13.10.2026)

Decyzja Artura z 13.10.2026: zespół pracuje już tylko w NEXUSIE i każdy
generuje CV w ścieżce rekrutacji, więc osobny moduł „Generator CV” nie jest
potrzebny jako wejście z nawigacji.

- **Zdjęte:** pozycja „Generator CV” z menu „Więcej” (grupa „Dokumenty”)
  i z palety ⌘K (`nav-registry.ts`: `inSidebar: false`, `inPalette: false`)
  oraz ekran `cv_generator` z narzędzia Jarvisa `open_screen` (Jarvis odsyła
  do rekrutacji albo profilu kandydata).
- **Gdzie się generuje CV:** karta „CV do klienta” w panelu osoby, profil
  kandydata („Generuj CV” przy podglądzie CV i zakładka „Rekrutacje”), dok
  kanbanu oraz okno QC CV. Wszędzie ten sam `CvGeneratorDialog` z osobą
  i rekrutacją wpisanymi z góry.
- **Okno QC CV** („Wygeneruj CV”, „otwórz generator” przy braku zrzutu
  zgody RODO) otwiera generator w oknie na miejscu, a nie link do
  `/cv-generator`. Nie wracaj do linku na stronę — to było ostatnie wejście
  na ukryty ekran z codziennej pracy.
- **Strona `/cv-generator` zostaje** pod adresem, razem z bramką
  w `middleware.ts`, okruszkiem, `/preview/cv-generator` i całym API
  `/api/cv-generator/*`: stare powiadomienia, zakładki i otwarte karty
  mają dokąd prowadzić. Dopiero ona ma „Moje CV (30 dni)” i ścieżkę „plik
  z dysku dla osoby spoza bazy” — gdyby ktoś o nie zapytał, to są jedyne
  rzeczy, których w ścieżce rekrutacji nie ma.
- Wzór ukrycia jest ten sam co przy Talentach, Targu i Zgłoszeniach:
  zdjęcie wejścia z nawigacji, strona i API działają dalej.
