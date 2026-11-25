# Arkusz rozmowy na dużej połowie ekranu (23.11.2026)

Decyzja Artura z 23.11.2026: rekomendacja 2 z analizy dnia rekrutera A–Z
(raport https://claude.ai/artifact/Bf7wiygZoxpTPq9G8oHgiL, Artur: „wszystkie
naraz”). Pomiar przed zmianą przy 1280 × 720 (staging, konto rekrutera,
rekrutacja 789230, osoba 73392 w Screeningu): formularz screeningu miał
ok. 3 500 px wysokości i przewijał się w oknie 287–355 px, a przyklejona
stopka zabierała z tego ok. 150 px. Lewą połowę (818 px) zajmowały wtedy
opisy wymagań. Na kopii produkcji 38% weryfikacji (128 z 338, 10–20.11)
wymagało 2+ zapisów arkusza, mediana od „Biorę” do „Zweryfikowany” 4,2 h.

- **„Tryb rozmowy”** (przycisk w pasku osoby po „Rozwiń”, od 1024 px okna)
  zamienia lewą strefę panelu na zakładki **„Arkusz rozmowy” · CV ·
  Wymagania · Po ludzku**. Arkusz jest pierwszy i otwarty na start; „Pokaż”
  historii w „Co już wiemy” przełącza na CV. Przy dwóch podglądach albo
  zwiniętym CV obok arkusza stoi jedna zakładka „CV i wymagania”. Po prawej
  zostaje reszta zakładki „Screening”: „Co już wiemy”, zgoda klienta,
  „Screening dla”. Bez trybu panel wygląda jak przed zmianą; poniżej 1024 px
  trybu nie ma.
- **Tylko układ.** Ten sam `ScreeningFullForm` z `layout="sheet"`: te same
  pola, walidacje, zapis (`PUT /api/screening-form`), ruch, odrzucenie,
  pamięć rozmowy i „Zapisz notatkę i wypełnij formularz” z pola notatki.
  Nie dokładaj osobnego formularza arkusza ani drugiej ścieżki zapisu.
- **Jeden egzemplarz formularza** (`person/MovableHost.tsx`): formularz
  renderuje się zawsze w tym samym miejscu drzewa, portalem do stałego
  elementu DOM, a ten element przenosimy między prawą kolumną a arkuszem.
  Zwykły portal do innego kontenera montuje treść od nowa i włączenie trybu
  w trakcie rozmowy kasowało niezapisane wpisy (RHF). Pilnuje test
  `ScreeningWorkbench` „tryb przenosi ten sam formularz…”.
- **Pasek nad arkuszem:** „Do „Zweryfikowany” brakuje N:” i chipy braków —
  ta sama reguła co stopka „Minimum dla Delivery Leada”
  (`minimumMissingForForward`; w rekrutacji bez pytań także „Dlaczego ten
  kandydat”), klik w chip stawia kursor w polu; obok „pytania X z Y ·
  sprawdź X z Y”. Liczy `lib/conversation-sheet.ts`. Linii minimum w stopce
  arkusza nie ma — nie powtarzaj braków w dwóch miejscach.
- **Dwie kolumny od ok. 700 px strefy** (`@[44rem]`, 2 : 3): lewa —
  „Warunki” (stawka bez stałego dopisku o przeliczeniu, krótkie pola
  z etykietą po lewej) i „Sprawdź w rozmowie” w jednej linii na wymaganie
  z ✓ / ✕ / ?; prawa — pytania z Profilu Championa („idealnie /
  deal-breaker · pokaż” obok „Odpowiedź narusza deal-breaker”), ocena jako
  trzy pigułki, „Dlaczego ten kandydat”, motywacja, red flags. Węższa strefa
  (okno 1024 px) układa to w jedną kolumnę.
- **Rzadkie pola pod „pokaż”:** narodowość i pola spoza wzoru działu (np.
  dołożone przez klienta). Na wierzchu zostaje każde pole wymagane, z zapisaną
  albo przeniesioną wartością i z prośbą DL o poprawkę. Podział liczy się ze
  stanu serwera, nie z wpisu — inaczej pole przeskakiwało w trakcie pisania
  i gubiło kursor.
  „Manager u Klienta” nie jest rzadki (uwaga rekruterki 25.11.2026): stoi
  zawsze zaraz pod „Czy pracował u Klienta”, w arkuszu i w zwykłym
  formularzu (`CARD_TERMS_ORDER`). Schowany pod „pokaż” był dopisywany
  w „Czy pracował u Klienta” — na kopii produkcji 179 kart.
- **Stopka na dole arkusza:** „Nie odebrał” (ta sama notatka-próba co
  w „Co już wiemy”, `useNoAnswerNote`), „Odrzuć”, stan zapisu, „Historia
  zmian”, „Zapisz”, „Zapisz i przekaż dalej → Zweryfikowany”. Rząd akcji
  etapu w głowie panelu („Inny etap”, „Odrzuć z powodem”, „Zrezygnował”)
  zostaje bez zmian.
- **Pomiar po zmianie** (ta sama osoba, staging): 1280 × 720 — arkusz
  1 088 px w oknie 625 px (jedno przewinięcie), 1440 × 900 — 1 052 px
  w 805 px, 1024 × 700 — jedna kolumna, 390 px — panel jak dotąd, bez
  poziomego przewijania.
- **Formularz wspólny** („Screening dla” z drugą rekrutacją, 23.11.2026)
  w trybie rozmowy ma ten sam układ: `JointScreeningForm` z `layout="sheet"`
  (przekazuje `ScreeningWorkbench`), te same pola, zapis per para, pamięć
  rozmowy i karta wyniku co w kolumnie.
  - Pasek: „Do „Zweryfikowany” brakuje:”, wiersz „Wspólne” (pole wspólne,
    np. dostępność, raz — nie w każdej rekrutacji) i wiersz na rekrutację
    z jej własnymi brakami („N pytania bez odpowiedzi”, tryb pracy, „Dlaczego
    ten kandydat”); obok „pytania X z Y” (grupy pytań tej rozmowy). Liczy
    `forwardGaps` z `lib/joint-screening.ts` na tym samym rzucie stanu co
    „Zapisz i przekaż dalej w N” — `forwardBlockers` to ten sam wynik jako
    tekst, nie druga reguła. Klik w brak stawia kursor w polu
    (`jointGapTarget`), a pole oceny innej rekrutacji najpierw otwiera jej
    zakładkę.
  - Dwie kolumny od `@[44rem]` (2 : 3): lewa — „Warunki” wspólne i per
    rekrutacja (kolumna jest swoim kontenerem, więc pola warunków stoją jedno
    pod drugim); prawa — pytania wspólne, „Tylko <rekrutacja>”, zakładki oceny.
    „Idealnie” i „Odpada, gdy” pod „idealnie / deal-breaker · pokaż”, jak
    w arkuszu pojedynczym. Formularz wspólny nie ma „Sprawdź w rozmowie”
    (sekcja 4 Championa), więc lewa kolumna jest krótsza; przeniesienie oceny
    na lewo skracało arkusz tylko o ok. 80 px, dlatego ocena stoi po prawej
    jak w arkuszu pojedynczym.
  - Stopka na dole arkusza: „Nie odebrał” (próba w rekrutacji kotwicy),
    „N rekrutacje · M pytań w rozmowie”, „Zapisz w N”, „Zapisz i przekaż dalej
    w N → Zweryfikowany”. Komunikat „Zanim przekażesz dalej…”, karta wyniku
    i ostrzeżenie pamięci stoją w stopce nad przyciskami, żeby było je widać
    bez przewijania arkusza.
  - Pomiar (staging, rekruter, osoba 665612 w rekrutacjach 789230 i 789216,
    5 grup pytań): 1280 × 720 — arkusz 2 899 → 2 056 px w oknie 625 px,
    pasek trzy linie; 1024 × 700 — jedna kolumna; bez poziomego przewijania.
- Jak zmierzymy: odsetek weryfikacji z 2+ zapisami arkusza (przed: 38%)
  i mediana od „Biorę” do „Zweryfikowany” (przed: 4,2 h), pomiar ok. 07.12.2026.

## Arkusz po prawej, CV po lewej (25.11.2026)

Zgłoszenie rekruterki z 25.11.2026: przy każdym kolejnym kandydacie trzeba
było przeklikać z arkusza na CV, a w trakcie zapisywania odpowiedzi CV nie
było widać. Makiety ze stagingu (konto zgłaszającej, rekrutacja 789154,
1280 × 720) w prywatnym artefakcie https://claude.ai/artifact/DbXWtbsU7SoK19awYnLsbA;
decyzja Artura: wariant „CV po lewej, arkusz po prawej, widoczny bez przewijania”.

- **Domyślnie arkusz po prawej** (`sheetSide: "right"` w układzie panelu,
  `lib/person-preview-layout.ts`): prawa kolumna dzieli panel po połowie
  (`lg:w-1/2`, przy CV niezwiniętym; przeciągnięta szerokość wygrywa), arkusz
  stoi na samej górze kolumny, przed „Co już wiemy”, zgodą i „Screening dla”.
  Lewa strefa to zwykły podgląd bez zakładki arkusza, otwarty na CV.
- **Wybór per osoba:** dwie ikony obok „Tryb rozmowy” w pasku osoby
  (`person-sheet-side`) przenoszą arkusz na lewą połowę (układ opisany wyżej)
  i z powrotem. Zapis razem z resztą układu (szerokość, Tryb rozmowy),
  w przeglądarce, per osoba. Wpis bez pola i nieznana wartość = po prawej.
- **CV na start zawsze:** w Trybie rozmowy podgląd otwiera się na CV także
  w etapie Screening (bez trybu — jak dotąd, wymagania), a w układzie
  „arkusz po lewej” zakładka arkusza nie jest na wierzchu przy kolejnej
  osobie.
- Formularz dalej jeden (`MovableHost`): przełączenie strony w trakcie
  rozmowy nie kasuje wpisów — pilnuje test `ScreeningWorkbench`
  „domyślnie arkusz stoi na górze prawej kolumny…”.
- Przy 1280 px prawa kolumna ma ok. 640 px, więc arkusz układa się w jedną
  kolumnę (dwie od `@[44rem]`, czyli przy szerszym oknie albo poszerzonej
  kolumnie).
