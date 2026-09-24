> **Zgodność z systemem sprawdzona:** 24.09.2026

Ta instrukcja opisuje, jak **dziś naprawdę działa** moduł Zamówienia — a nie jak
miał działać albo jak działał kiedyś. Zaczyna się od rzeczy wspólnych dla
wszystkich klientów, a dalej ma osobną sekcję dla każdego klienta, u którego coś
jest inaczej. Jeżeli szukasz konkretnego klienta, skorzystaj ze spisu treści na
górze.

Instrukcja jest utrzymywana razem z kodem: gdy ktoś zmienia sposób działania
zamówień, przed wdrożeniem musi ją przejrzeć i potwierdzić datą u góry. Szerzej
o tym na końcu, w sekcji **Skąd wiadomo, że ta instrukcja jest aktualna**.

---

## Gdzie są zamówienia

**Klienci → nazwa klienta → zakładka „Zamówienia"** (trzecia od lewej, po
„Profil" i „Projekty"). Powiadomienia o zamówieniach prowadzą prosto tutaj, więc
najczęściej trafisz na tę zakładkę jednym kliknięciem z dzwonka albo z pulpitu.

**Jest jedna zakładka „Zamówienia" dla wszystkich klientów.** Nie ma już dwóch
różnych ekranów — jeśli słyszałeś o „widoku wielokonsultanckim" i „widoku
jednoosobowym", to dziś jest to jedna lista, podzielona na sekcje według typu
zamówienia, w stałej kolejności od góry: **MD**, **Kosztowe**, **Okresowe**
(z liczbą pozycji w nawiasie). **Sekcja bez ani jednej pozycji w ogóle się nie
pokazuje**, więc u większości klientów zobaczysz tylko jedną albo dwie.

Sekcja **Okresowe** zawiera wyłącznie karty pojedynczych osób. Sekcje **MD**
i **Kosztowe** bywają mieszane: obok kart zamówień zbiorczych (z listą
konsultantów) potrafią stać karty pojedynczych osób, których zamówienie ma taki
typ.

Nad listą masz:

* siedem filtrów z licznikami: **Wszystkie**, **Aktywne**, **⚠️ Kończące się 30d**,
  **Zakończeni**, **Wyczerpane**, **Anulowane**, **📝 Draft (do uzupełnienia)**.
  **O tym, kto jest w „Zakończonych", decyduje wyłącznie umowa z modułu
  Kontrakty** — jej status i data zakończenia — nigdy sam upływ okresu
  zamówienia. Osoba z datą końca umowy 30.09 jest w „Aktywnych" do 30.09
  włącznie i od 1.10 sama przechodzi do „Zakończonych". Gdy skończył się tylko
  okres zamówienia, a umowa trwa i nikt nie dodał przedłużenia, osoba zostaje
  w „Aktywnych" z dopiskiem **„Brak aktywnego zamówienia"** — to sygnał dla
  Ciebie: dodaj przedłużenie albo poproś administrację o zakończenie umowy
  w Kontraktach. Data końca wpisana tam w umowie od razu staje się datą końca
  jej otwartego zamówienia (zamówienie zaczynające się później jest anulowane).
  **W „Kończących się 30d" są tylko zamówienia, które nie mają jeszcze
  kontynuacji.** Gdy do zamówienia kończącego się w ciągu 30 dni dodasz już
  przyszłe zamówienie (także szkic „do uzupełnienia"), to zamówienie znika
  z tej zakładki i z jej licznika — nie wymaga działania. Samo przyszłe
  zamówienie ocenia się tak samo: jeśli ono z kolei kończy się w ciągu 30 dni
  i nic nie ma po nim, karta zostaje w zakładce, a plakietka mówi „przyszłe
  zamówienie … kończy się za N dni". Przy zamówieniach MD/kosztowych
  kontynuacją jest przedłużenie tego zamówienia,
* wyszukiwarkę po numerze zamówienia albo imieniu i nazwisku konsultanta,
* **Filtry i sortowanie** (zakresy dat, „Bliskie wyczerpania budżetu (≥80%)",
  „Kończące się w ciągu N dni"),
* **Pobierz do Excela** — eksport tego, co aktualnie widzisz, **w stanie na
  dziś**: plik bierze wyłącznie zamówienia obowiązujące w dniu pobrania i każdy
  konsultant jest w nim **dokładnie raz**. Zamówienia zakończone i te, które
  jeszcze się nie zaczęły, do arkusza nie wchodzą; „kończące się" wchodzi, bo
  konsultant nadal pracuje,
* przycisk **Nowe zamówienie**.

**📝 Draft** pokazuje szkice pojedynczych konsultantów oraz nowe zbiorcze
zamówienia MD, które czekają na uzupełnienie i aktywację. **Wyczerpane**
pokazuje wyłącznie zamówienia zbiorcze.

**Imię i nazwisko konsultanta jest klikalne — otwiera jego umowę w module
Kontrakty.** Działa w każdym wierszu: na karcie pojedynczej osoby, na liście
konsultantów zamówienia zbiorczego (również w części „Zakończone") i na
wierszach przyszłych zamówień. Otwiera się **ta umowa, która stoi w tym
wierszu** — jeśli ktoś pracuje u kilku klientów i ma kilka umów, dostaniesz tę
u klienta, z którego profilu kliknąłeś, a nie listę wszystkich jego umów.
Wracasz przyciskiem **wstecz** przeglądarki; wrócisz na zakładkę „Zamówienia",
ale **filtr i wyszukiwarka wracają do ustawień domyślnych** — jeśli szukałeś
kogoś w długiej liście, wpisz frazę jeszcze raz.

Nieklikalne są dwie nazwy przy historii pozycji: **„zastąpił: …"** oraz nazwa
następcy przy osobie zastąpionej. System zna tam tylko numer zamówienia, nie
umowę — żeby do kogoś z nich przejść, kliknij jego własny wiersz na liście.

---

## Trzy typy zamówienia

Typ **zamówienia zbiorczego** (MD albo kosztowego) wybierasz raz, przy zakładaniu.
Po zapisie przełącznik jest widoczny, ale zablokowany — pod nim pojawia się napis
„Typu nie można zmienić po utworzeniu zamówienia". Pomyłka oznacza założenie
zamówienia od nowa, więc to jest moment, w którym warto się zatrzymać.

Przy zamówieniu **pojedynczej osoby** typ da się jeszcze zmienić, dopóki
zamówienie jest w statusie **Draft** — po awansie na „Aktywne" jest już zamknięty.

| Typ | Kiedy go używasz | Jak się rozlicza |
|---|---|---|
| **Okresowe** | jedna osoba = jedno zamówienie; klasyczny body-leasing | datami: zaczyna się i kończy w konkretnym dniu |
| **MD** | jeden numer zamówienia od klienta obejmuje kilku konsultantów, a rozliczasz się w osobodniach | budżetem MD: kończy się, gdy skończą się dni — nie gdy minie data |
| **Kosztowe** | jeden numer zamówienia, kilku konsultantów, jedna kwota w złotych z góry | kwotą: kończy się, gdy pula pieniędzy zejdzie do zera |

Każda pozycja na liście ma kolorową etykietę z typem, więc widzisz to od razu.

**W nowym zamówieniu MD wybierasz tryb budżetu u każdego klienta.** Domyślnie
checkbox **„Budżet MD na całe zamówienie”** jest odznaczony: każda osoba ma
własny budżet. Po zaznaczeniu wpisujesz jedną wspólną pulę na zamówieniu,
a konsultanci nie mają osobnych pól budżetu. Karta pokazuje **„Wspólna pula”**.

Tryb można zmienić tylko w **Draft**, dopóki nie ma żadnego wpisu zużycia MD.
Aktywacja albo pierwszy wpis zużycia trwale blokują przełącznik. Zmiana trybu
w szkicu usuwa dotychczasowy podział: po powrocie do budżetu per osoba uzupełnij
budżet każdej linii przed aktywacją.

**Istniejące zamówienia zachowują swój tryb.** Dotychczasowe budżety per osoba
nie są przeliczane ani łączone. Historyczne wspólne pule Lotte Wedel i Cyfrowego
Polsatu pozostają wspólne; nowych zamówień tych klientów dotyczy ten sam wybór
co u pozostałych klientów.

Przy wspólnej puli import z Finansów wymaga numeru zamówienia w kolumnie
„Uwagi” i sumuje zużycie wszystkich konsultantów. Karta oraz Excel pokazują
budżet, łączne zużycie i pozostałość raz na całe zamówienie. Przy budżecie
per osoba liczby i ostrzeżenia dotyczą poszczególnych konsultantów.

**Każdy klient ma wszystkie trzy typy do wyboru.** Okno „Nowe zamówienie"
**domyślnie zaznacza typ najczęstszy u danego klienta** (np. u BIK — MD), ale to
tylko podpowiedź: typ zmienisz jednym kliknięciem, także po odczycie PDF-a.
Dawnych blokad (BNP i BIK tylko MD, Polkomtel i Lotte Wedel bez okresowych) już
nie ma. Historyczne zamówienia tych czterech klientów zapisane bez typu nadal
widać w sekcji **MD**.

---

## Jak dodać zamówienie okresowe (jedna osoba)

Są **trzy drogi** i wybór między nimi zależy wyłącznie od tego, czy ta osoba jest
już w rejestrze klienta.

**1. Osoba jest już na liście (najczęstszy przypadek).** Bardzo często system
założył jej kartę sam — po przestawieniu kandydata na etap „zatrudniony" albo po
potwierdzeniu obustronnie podpisanej umowy. Powstaje wtedy **szkic umowy** i **szkic
zamówienia** ze stawką przepisaną z umowy i notatką „Uzupełnij stawkę klienta,
daty i wgraj PDF zamówienia". W rubryce **nr zam.** stoi wtedy wartość
zastępcza: **„(bez numeru)"** u klientów rozliczanych w MD lub kosztowo, a u
pozostałych **„Imię Nazwisko — Tytuł rekrutacji"**. Jedno i drugie trzeba
zastąpić prawdziwym numerem z dokumentu klienta. Szkic znajdziesz pod filtrem
**📝 Draft (do uzupełnienia)**.

Kliknij **Uzupełnij zamówienie** na karcie tej osoby i wypełnij dane z dokumentu
od klienta.

**2. Osoba jest na liście, ale chcesz poprawić jedno pole.** Numer zamówienia,
obie stawki i okres edytujesz **klikając wprost w tekst na karcie** — bez
otwierania okienka. Na każdej karcie stoją w stałym układzie trzech linii pod
nazwiskiem: najpierw **nr zam.**, niżej razem **koszt.** i **przych.**, a w
trzeciej linii **okres:**. Najechanie myszą na etykietę pokazuje jej pełne
brzmienie. Jeżeli ta osoba nie ma jeszcze żadnego zamówienia, pierwszy taki
zapis sam założy szkic.

**3. Osoby nie ma jeszcze w rejestrze.** Kliknij **Nowe zamówienie**, wybierz typ
**Okresowe** — otworzy się formularz **„Nowy kontraktor / zamówienie"**, który
zakłada **jednocześnie umowę i pierwsze zamówienie**. Pola:

* **Kandydat \*** — wyszukiwarka po imieniu, e-mailu, umiejętności
* **Rekrutacja (opcjonalnie)**
* **Numer zamówienia \*** — np. 45767
* **Początek umowy \*** — początek umowy z konsultantem. **Daty końca umowy
  tu nie ma:** umowa B2B jest bezterminowa, dopóki ktoś jej nie zakończy
  przyciskiem **„Zakończ współpracę"** (powód i data, także przyszła). Koniec
  zamówienia klienta wpisujesz w **Koniec zamówienia** — to on uruchamia ostrzeżenia
* **Początek zamówienia (PDF od klienta)** / **Koniec zamówienia** — okres zamówienia
* **Jednostka stawki** — Godzinowa / MD / Miesięczna
* **Klient płaci \*** — stawka przychodowa
* **My płacimy kontraktorowi \*** — stawka kosztowa
* **Godziny / mc** — aktywne tylko przy stawce **godzinowej**
* **Notatki**
* **PDF zamówienia od klienta** — `.pdf`, `.docx` albo `.doc`, z przyciskiem
  **Zczytaj dane z dokumentu** obok

Zapisujesz przyciskiem **Utwórz umowę i zamówienie**.

> **Jednostka stawki jest domyślnie „Miesięczna".** Ustaw ją **zanim** wpiszesz
> kwoty — przełączenie jednostki przelicza obie stawki, a stawka godzinowa
> zapisana jako miesięczna daje kwotę 168 razy za dużą (miesiąc roboczy to
> 168 godzin = 21 MD × 8 h). Nie zatwierdzaj formularza klawiszem Enter, dopóki jednostka nie jest
> ustawiona.

> **Umowa aktywuje się sama, gdy ma komplet:** datę startu umowy, stawkę kosztową
> i stawkę przychodową (tę bierze z zamówienia). Bez kompletu zostaje szkicem —
> dopóki jest szkicem, ta osoba nie liczy się do przychodów.
>
> **Jeżeli zapis zwróci błąd pliku, kontraktor i zamówienie i tak powstały.**
> Plik idzie osobnym żądaniem, więc komunikat mówi wprost, żeby wgrać go
> ponownie przez **Uzupełnij zamówienie** — a nie zakładać wszystkiego drugi raz.

### Kiedy zamówienie przestaje być szkicem

Szkic awansuje na **Aktywne sam, w chwili zapisu**, gdy ma komplet czterech
rzeczy: prawdziwy numer (nie „(bez numeru)"), datę rozpoczęcia, stawkę
przychodową i stawkę kosztową.

Jeżeli kompletny szkic okresowy dotyczy okresu, który już minął, zapisuje się
jako **Zakończone**. Zamówienie z początkiem w przyszłości trafia do zamówień
przyszłych.

Jeżeli szkic ma typ **MD** albo **kosztowy**, dochodzi piąty warunek: musi mieć
odpowiednio **liczbę MD** albo **kwotę zamówienia**. Bez tego zostaje w Drafcie,
mimo kompletu pozostałych pól.

**Data zakończenia NIE jest wymagana.** Umowa bezterminowa jest normalnym stanem
docelowym, a nie brakiem danych — nie wpisuj daty „na oko" tylko po to, żeby
zamówienie ruszyło.

> **Ale pusta data ma cenę: zamówienie bez daty zakończenia nie dostanie żadnego
> ostrzeżenia 30/14/7 dni.** Cały mechanizm liczy dni od konkretnej daty, więc
> puste pole znaczy „nie ostrzegaj nigdy". Jeżeli dokument od klienta podaje datę
> końca — wpisz ją. Zostaw puste pole tylko wtedy, gdy współpraca naprawdę jest
> bezterminowa, i wtedy pilnuj terminu sam.

### Zmiana okresu przelicza aktywność zamówienia

W **samodzielnym zamówieniu okresowym** zmiana dat przez **Uzupełnij
zamówienie** albo bezpośrednio na karcie od razu przelicza aktywność. Jeśli
nowy okres obejmuje dzisiaj, zamówienie **Zakończone** wraca do **Aktywne** —
również wtedy, gdy wcześniej zakończono je ręcznie. Po zapisie znika ostrzeżenie
**„Brak aktywnego zamówienia”**, bez odświeżania strony.

Obie daty graniczne liczą się do okresu; „dzisiaj” oznacza dzień w Polsce.
Brak daty końca oznacza okres bezterminowy. Okres już miniony zapisuje się jako
**Zakończone**, a okres zaczynający się później pokazuje się jako przyszły.
Te same zasady obowiązują przy nowym zamówieniu, przedłużeniu i imporcie
Nordea z CSV.

Samo ponowne zapisanie tych samych dat albo zmiana numeru, notatki, pliku czy
stawki **nie wznawia** zakończonego zamówienia. Zamówienia **Wstrzymane**
i **Anulowane** nie wznawiają się od zmiany okresu. Jawnie wybrany status ma
pierwszeństwo. Niekompletny szkic nadal wymaga uzupełnienia, a zamówienia MD,
kosztowe i zbiorcze zachowują własne zasady aktywności.

Jeśli dane zapiszą się poprawnie, ale wgranie PDF-a się nie powiedzie, karta
pokazuje już zapisany okres i status, a formularz zgłasza błąd pliku. Ponów
wgranie pliku przez **Uzupełnij zamówienie**.

### „Zakończ zamówienie" to co innego niż „Zakończ współpracę"

Na karcie pojedynczego konsultanta są **dwa** przyciski i różnica między nimi
jest istotna:

* **Zakończ zamówienie** — domyka **to jedno zamówienie**. Umowa zostaje
  aktywna, a wszystkie pozostałe zamówienia tej osoby (w tym linia na
  zamówieniu MD u tego samego klienta) zostają **nietknięte**. Tego użyj, gdy
  kończy się okres zamówienia, a współpraca trwa dalej.
* **Zakończ współpracę** — wypowiada **umowę**. Domyka wszystkie zamówienia tego
  kontraktu i — przy zamówieniach MD — otwiera decyzję o niewykorzystanych
  dniach. Tego użyj, gdy konsultant naprawdę odchodzi od klienta.
  Okno pyta o powód i **datę zakończenia projektu** — do tego dnia włącznie
  kontrakt jest „Kończący się", od następnego sam przechodzi do
  „Zakończonych" (data z przeszłości = „Zakończony" od razu). Zaznacz
  **„Rozwiązanie umowy"**, gdy razem z projektem kończy się umowa B2B
  (wypowiedzenie albo porozumienie stron, ostatni dzień umowy, skan pisma) —
  wtedy w Generatorze umowa trafia do „Zakończonych umów"; bez zaznaczenia
  czeka w „Umowach bez projektu". Innej drogi do „Zakończonego" nie ma: lista
  statusu i „Oznacz zakończone" otwierają to samo okno.
  Umowy **unieważnionej** nie da się zakończyć — system odmówi, bo to już
  stan końcowy. Szkic zakończony z datą w przyszłości zostaje szkicem do tej
  daty, a dzień po niej sam przechodzi do „Zakończonych".

Data w przyszłości w obu przypadkach zapisuje się od razu, ale **nie wyłącza
niczego dzisiaj** — zamówienie obowiązuje do jej nadejścia.

Trzecia akcja, **Usuń zamówienie** (kosz — przy bieżącym zamówieniu na karcie
i przy każdym zamówieniu przyszłym oraz historycznym), służy do wycofania
**pomyłki**: kasuje trwale **tylko to jedno zamówienie**. Status umowy
i pozostałe zamówienia tej osoby (także linia na zamówieniu MD lub kosztowym)
zostają nietknięte. Zamówienia z rozliczeniami (zaraportowane MD, zaimportowane
faktury) system nie usunie — odmówi i wskaże, co blokuje; wtedy właściwą akcją
jest **Zakończ zamówienie**.

**Jedna rzecz na umowie jednak się zmienia i okno powie Ci o tym wprost.**
Zamówienie, które wprowadziło stawkę klienta, niesie ze sobą **krok
w harmonogramie stawek** tej umowy. Razem z zamówieniem znika ten krok, więc
okres, który dotąd był po jego stawce, przechodzi na stawkę sąsiednią —
a to zmienia kwoty w **miesiącach już rozliczonych**. Zanim potwierdzisz,
okno usuwania wylicza to na serwerze i **wymienia konkretnie**: od kiedy do
kiedy obowiązywał znikający krok i jaka stawka wejdzie na jego miejsce.
Nic się nie zmieni **tylko wtedy**, gdy okno wprost to napisze — dopóki się
liczy, przycisk „Usuń" jest nieaktywny, bo „nie wiadomo" to nie to samo co
„nic się nie stanie". Jeśli lista skutków Cię zaskoczy, właściwą akcją jest
**Zakończ zamówienie**, nie usunięcie: zakończenie zostawia historię taką,
jaka była.

### Jedna osoba nie ma dwóch równoległych zamówień na to samo

Jeżeli konsultant jest już obsadzony na **zamówieniu MD** u tego klienta, system
**odmówi** założenia mu dodatkowego zamówienia okresowego i powie o tym wprost.
To nie jest ograniczenie na siłę: oba zapisy wiszą na tej samej umowie, więc
duplikat mylił liczby i przy zakończeniu jednego znikał drugi. Gdy trzeba zmienić
warunki — edytuj linię w zamówieniu zbiorczym.

Zamówienie **kosztowe** i okresowe u tej samej osoby mogą istnieć obok siebie —
to dwa różne modele rozliczenia i są od siebie niezależne.

---

## Jak dodać zamówienie MD albo kosztowe (kilku konsultantów, jeden numer)

**Wszystko dzieje się w jednym oknie „Nowe zamówienie"** — numer, data, typ,
wszyscy konsultanci, ich stawki i MD. Nie ma już pustego zamówienia, do którego
potem osobno dokładasz ludzi.

**Krok 1 — wgraj PDF i kliknij „Zczytaj i uzupełnij całe zamówienie".** Przycisk
**Nowe zamówienie** otwiera okno z typem najczęstszym u klienta. Wgraj PDF
zamówienia (`.pdf`, do 25 MB) i kliknij **Zczytaj i uzupełnij całe zamówienie**.
System jednym odczytem:

* wpisuje **numer zamówienia** i **daty** (jeżeli wpisałeś je wcześniej ręcznie
  i dokument mówi co innego — najpierw zapyta „Tak/Nie"),
* przy typie kosztowym wpisuje **kwotę zamówienia**, a przy wspólnej puli MD —
  **budżet w MD**,
* **rozpoznaje, ilu konsultantów jest w dokumencie, i dla każdego tworzy kartę**.

**System wymaga tylko tych pól, które są potrzebne dla wybranego typu.**
Zamówienie **kosztowe** rozlicza się kwotą — system szuka **kwoty łącznej**, a nie
liczby MD, i brak MD w dokumencie **nie jest błędem**. Przy zamówieniu **MD**
liczba MD bywa podana na dwa sposoby i oba są poprawne: **przy każdej osobie**
(osobny limit, jak u BIK) albo **jedną liczbą na całe zamówienie**. System
rozpoznaje wariant z dokumentu i sam ustawia **„Budżet MD na całe zamówienie"**
(albo budżet per osoba) — pod checkboxem zobaczysz, co przeczytał. O braku MD
usłyszysz dopiero wtedy, gdy przy typie MD dokument nie podaje ich w żadnym
z tych dwóch wariantów.

Na każdej karcie stoją trzy wartości, a pod każdą — **skąd pochodzi**:

* **Stawka kosztowa** — **„z kontraktu"** dopasowanej osoby (dokument klienta
  jej nie zawiera),
* **Stawka przychodowa** i **Liczba MD** — **„z PDF, poz. 10"** (numer pozycji
  z tabeli dokumentu; gdy go nie ma — „2. osoba w dokumencie").

Gdy u klienta działa reguła odczytu tabeli PDF-a (np. Credit Agricole, Erste,
Nordea), **stawka i MD na karcie pochodzą z tej tabeli**, a jeśli odczyt AI
podał co innego, karta mówi o tym wprost. Gdy dokument podaje stawkę **bez
jednostki**, obok kwoty świeci na czerwono **„jednostka?"** — wybierz ją, bo bez
tego zamówienia nie zapiszesz (stawka godzinowa zapisana jako „za MD" byłaby
ośmiokrotnie za niska). U **Orlenu** liczby MD z PDF-a nie są używane — wpisujesz
je ręcznie. Kwota zamówienia w obcej walucie nie trafia sama do „Budżet
całkowity (PLN)".

Każdą wartość możesz poprawić — opis źródła zmienia się wtedy na **„wpisano
ręcznie"**. Jednostkę stawki (zł/MD, zł/h, zł/mc) zmieniasz obok liczby, kwota
przelicza się sama. Waluta pochodzi z kontraktu i z dokumentu; gdy trzeba ją
zmienić, zrób to po zapisie w **Edytuj linię**. Na zamówieniu kosztowym i przy
wspólnej puli MD karta nie ma pola **Liczba MD** — budżet jest wtedy wspólny
dla całego zamówienia.

**Krok 2 — sprawdź odznaki na kartach.** System dopasowuje osobę z PDF-a do
kontraktu u tego klienta i oznacza wynik:

| Odznaka | Co znaczy | Co robisz |
|---|---|---|
| zielona **Dopasowano automatycznie** | zapis identyczny jak w kontrakcie; różnice tylko w polskich znakach („Pawel Laski" = „Paweł Łaski") lub wielkości liter | nic |
| żółta **Dopasowano — potwierdź** | rdzeń imienia i nazwiska się zgadza, ale w kontrakcie przed nim jest dopisek („Active", „UR –", „Projekt 2") albo imię i nazwisko stoją w odwrotnej kolejności | **To ta osoba — potwierdzam** albo **To nie ta osoba** |
| czerwona **Zakończył współpracę** | osoba jest w systemie, ale jej współpraca u tego klienta jest zakończona — karta mówi to wprost, z datą końca kontraktu | wybierasz jedno z czterech: **Zostaw jako historię**, **Wznów współpracę**, **Zastąp kimś innym** albo **Usuń z zamówienia** (patrz niżej) |
| czerwona **Kilka osób — wybierz ręcznie** | u tego klienta są dwie różne osoby o tym samym imieniu i nazwisku — także gdy jedna z nich ma już tylko zakończony kontrakt — albo ta sama osoba ma dwa aktywne kontrakty | wybierasz właściwy kontrakt po numerze i dacie rozpoczęcia. Wybór kontraktu **zakończonego** nie wznawia go po cichu: karta przechodzi w to samo pytanie co przy „Zakończył współpracę" (z niego wrócisz do listy przyciskiem **Wybierz inną pozycję z listy**) |
| czerwona **Wymaga ręcznego wskazania** | tej osoby nie ma w systemie („Nie znaleziono … w systemie") albo imię i nazwisko różni się czymś więcej niż polskie znaki | **Wskaż tę osobę ręcznie** z listy, **Zastąp kimś innym** albo **Usuń z zamówienia** |

**Osoba z PDF-a, która zakończyła współpracę.** Zamówienie nie utyka i nie
wznawia niczego po cichu — decydujesz Ty:

* **Zostaw jako historię** — osoba zostaje na zamówieniu **jako zakończona**
  (z datą końca kontraktu). Kontrakt się nie wznawia, osoba nie wchodzi do
  aktywnej obsady, a to, co zdążyła wykorzystać, zostaje przypisane do
  zamówienia.
* **Wznów współpracę** — to powrót tej osoby: zapis zamówienia wznowi jej kontrakt.
* **Zastąp kimś innym** — wybierasz inną osobę; karta zapamiętuje, za kogo jest
  zastępstwem.
* **Usuń z zamówienia** — karta znika.

**Ta sama reguła obowiązuje u każdego klienta rozliczanego w MD albo kwotą
budżetową i na każdej ścieżce odczytu PDF-a** — w oknie **Nowe zamówienie**,
w **Uzupełnij zamówienie** i przy zamówieniu, które przyszło **mailem** (patrz
„Zamówienia ze skrzynki"). Wszędzie widzisz ten sam komunikat i ten sam wybór.

Na zapisanym zamówieniu zobaczysz przy każdej osobie jej **okres udziału,
wykorzystaną kwotę/MD i status** (aktywna / zakończyła współpracę / usunięta),
a przy osobie **dodanej ręcznie** — spoza oryginalnego PDF-a, także jako
zastępstwo — **kto ją dodał i kiedy** (i za kogo), żeby dało się zapytać o powód.
PDF zamówienia jest podpinany do profilu **każdej** osoby, która kiedykolwiek była
na zamówieniu, także dodanej później.

**Rdzeń** to dwa ostatnie wyrazy pisane wielką literą w nazwie kontraktora —
wszystko przed nimi to dopisek. **System nigdy nie poprawia literówek i nie
zgaduje podobieństwa**: „Jan Kowalczyk" w kontrakcie nie zostanie dopasowany do
„Jan Kowalski" z PDF-a, nawet gdy to jedyny podobny zapis. Taki zapis zobaczysz
najwyżej jako podpowiedź „Najbliższy zapis w kontraktach", ale wskazać musisz go
sam.

Pod listą kart widzisz **„X z Y pozycji gotowe do zapisania"** i łączną wartość
zamówienia. Kartę możesz **usunąć** (kosz) albo **dodać kolejną** przyciskiem
**Dodaj konsultanta** — wtedy wybierasz osobę z listy.

**Krok 3 — Utwórz zamówienie.** Przycisk jest aktywny, gdy każda karta ma
wskazaną osobę, potwierdzone dopasowanie i obie stawki (a przy MD per osoba —
liczbę MD). Jednym kliknięciem powstaje zamówienie razem ze wszystkimi
konsultantami. **Status** nowego zamówienia MD to domyślnie **„Aktywne — od razu
po zapisaniu"**; jeżeli czegoś jeszcze nie wiesz, wybierz **„Draft — do
uzupełnienia"** (zamówienie trafi do **📝 Draft**). Aktywne zamówienie MD
z budżetem per osoba musi mieć co najmniej jednego konsultanta.

Wybór typu **Okresowe** w tym oknie przenosi Cię do formularza „Nowy kontraktor
/ zamówienie" (jedna osoba) — wgrany PDF przechodzi razem z Tobą.

> **Jeżeli plik nie wejdzie, zamówienie i tak zostało zapisane.** Zapis
> zamówienia i wysłanie pliku to dwie osobne operacje. System powie Ci wprost, że
> masz wgrać plik ponownie przez edycję — **nie zakładaj zamówienia drugi raz**.

Wgrany PDF pojawia się nie tylko na karcie zamówienia: znajdziesz go też
w sekcji **„Dokumenty zamówień"** w dokumentach umowy konsultanta i w jego
plikach. Rola bez dostępu do zamówień tego klienta tej sekcji po prostu nie
zobaczy — bez żadnego komunikatu.

**Dokładanie konsultanta do istniejącego zamówienia.** Na karcie zamówienia
kliknij **Dodaj konsultanta do zamówienia**. Tak samo działa ręczny wybór osoby
na karcie w oknie „Nowe zamówienie". Wyszukiwarka pokazuje dwa źródła:

* **Rekrutacja u klienta** — osoby, które mają u tego klienta umowę,
* **Baza Nexus** — dowolny aktywny konsultant z całej firmy.

Wybranie osoby z **Bazy Nexus** jest w porządku i tak ma być: system założy jej
u tego klienta **szkic umowy**, żeby było do czego przypiąć zamówienie. Umowę
trzeba potem domknąć osobno — szkic nie wchodzi do przychodów ani do alertów
o wygasaniu.

Każdy konsultant to osobna **linia** — tak nazywają wiersz jednej osoby na
zamówieniu przyciski w aplikacji („Edytuj linię"). Linia ma **obie stawki i obie
są wymagane**. Bezpośrednio pod każdą stawką wybierasz jej walutę — kosztową
po lewej, przychodową po prawej, zarówno dla MD, jak i zamówień kosztowych.
Edycja pokazuje zapisane waluty. Zmiana samej waluty zachowuje wpisaną liczbę;
nie przelicza jej automatycznie na nową walutę.
Na zamówieniu **MD per osoba** podajesz przy każdej osobie jej **budżet dni**; przełącznik
daje wybór **„Liczba MD"** albo **„Kwota zamówienia"** — tę kwotę system dzieli
przez stawkę przychodową i sam wylicza liczbę dni. Kwota budżetu jest w PLN;
przy stawce zagranicznej wynik zostanie obliczony przy zapisie według kursu.
Pola budżetu przy osobie **nie ma** na zamówieniu **kosztowym** ani na zamówieniu
MD ze **wspólną pulą**, niezależnie od klienta.

Przycisk **Dodaj konsultanta** jest wyszarzony tylko przy zamówieniu
**zakończonym** albo **wyczerpanym**. Do zamówienia **przyszłego** (z datą startu
w przód) konsultantów dodajesz normalnie — czekają razem z nim na dzień startu.

**Aktywacja zamówienia MD zapisanego jako Draft.** Otwórz **Uzupełnij
zamówienie**, wybierz status **Aktywne** i zapisz. Wymagana jest przynajmniej
jedna linia oraz dodatnie budżety osób albo wspólny budżet. Od tej chwili tryb
budżetu jest zablokowany. Jeśli data startu jest przyszła, zamówienie czeka na tę
datę; samo pozostawienie kompletnego szkicu nie aktywuje go.

### Co jeszcze możesz zrobić na karcie zamówienia zbiorczego

| Przycisk | Co robi |
|---|---|
| **Uzupełnij zamówienie** | edycja numeru, budżetu, dat, notatek, podmiana PDF-a; w nowym szkicu MD także wybór trybu i aktywacja, a przy aktywnej wspólnej puli — miesięczne zużycie. **Zczytaj dane z dokumentu** czyta tu PDF tak samo jak w „Nowe zamówienie": osoby z dokumentu, których **nie ma jeszcze na zamówieniu**, dostają karty do dopisania (z tymi samymi odznakami i decyzjami — także osoba bez aktywnej współpracy albo nieznaleziona), a osoby, które **już są**, wypisane są w ramce „Już na zamówieniu" bez drugiej karty (gdy dokument podaje dla niej inne MD albo stawkę, ramka to mówi — zmieniasz je w „Edytuj linię"). Osoby, która już pracuje na tym zamówieniu, nie dopiszesz drugi raz — także wskazanej ręcznie. **Zapisz** dopisuje wszystkie karty naraz albo żadnej; przy aktywacji szkicu najpierw dopisuje osoby, potem aktywuje |
| **Dodaj przedłużenie** | zakłada **nowe** zamówienie podpięte pod obecne (patrz niżej) |
| **Zakończ** | okienko „Zakończ zamówienie": obowiązkowa data + opcjonalny powód |
| **Przywróć** | cofa zakończenie — pokazuje się przy **każdym** zamówieniu ze statusem „Zakończone", także takim, które system domknął sam; przy zamówieniu MD z budżetem przy osobie wskrzesza też konsultantów, którym zostały dni i nie minęła data. Zamówienia **wyczerpanego** nie przywrócisz — tam trzeba podnieść budżet |
| **Anuluj zamówienie** | dla zamówienia, które **nie doszło do skutku** albo zostało założone omyłkowo, a chcesz zachować jego historię. Zamówienie i jego konsultanci dostają status „Anulowane”, znikają z aktywnych zamówień, sum, alertów i rozliczeń, ale zostają w rejestrze (filtr **Anulowane**). **Zamówienia z rozliczeniami (zaraportowane MD, faktury) nie anulujesz** — system odmówi i wskaże, co blokuje; wtedy właściwą akcją jest **Zakończ**. Anulowanego zamówienia nie edytujesz, nie kończysz ani nie przedłużasz |
| **Przywróć anulowane** | cofa anulowanie: zamówienie wraca do stanu sprzed niego (np. „Aktywne”), a konsultanci — do swoich statusów; osoba, której okres w międzyczasie minął, wraca jako zakończona |
| **Usuń całe zamówienie** | służy do wycofania **pomyłki** i jest nieodwracalne: zamówienie znika razem ze swoją historią. **Zamówienia z rozliczeniami system nie usunie** — odmówi i wskaże, co je blokuje (rozliczone MD, zaimportowane faktury). Wtedy właściwą akcją jest **Zakończ**. Razem z zamówieniem znikają jego linie — **nie powstają z nich osobne zamówienia okresowe**. Okno usuwania pokazuje skutki dla umów: jeśli zamówienie niosło jedyną stawkę klienta na umowie, umowa zostaje **bez przychodu** (stawka klienta i marża znikają), a gdy są inne zamówienia — okres, którego dotyczyło, przejdzie na ich stawkę |
| **Historia zamówienia** | rozwijana lista zdarzeń z datą, wykonawcą (wpis bez osoby = zmiana automatyczna) i opisem: utworzenie, dodania i zamiany konsultantów, importy, decyzje o MD, zakończenia. Zapis nowego szkicu MD, zmiana jego trybu, aktywacja i zapis miesięcznego zużycia wspólnej puli również zostawiają wpis |

Przy każdym konsultancie masz osobno: **Edytuj linię**, **Zamień kontraktora**
(tylko przy aktywnej linii) i **Usuń konsultanta z zamówienia**.

### Kto stoi w „Aktywnej obsadzie", a kto w „Zakończonych"

Obsada zamówienia dzieli się na dwie sekcje. **O przejściu do „Zakończonych"
decyduje data zakończenia współpracy wpisana przy osobie** — wystarczy wpisać ją
w **Edytuj linię** i zapisać; nie trzeba nic więcej klikać. Od dnia po tej dacie
osoba schodzi z aktywnej obsady, znika z awatarów w nagłówku i z licznika
aktywnych konsultantów, a jej wiersz przenosi się niżej, do **„Zakończonych"** —
z całą historią: okresem udziału, wykorzystanymi MD i kwotami oraz informacją,
kogo zastąpiła i kto zastąpił ją. **„Zakończeni" są ułożeni datą zejścia,
od najnowszego.** Osoba, która kogoś zastąpiła, zostaje w aktywnej obsadzie —
dla niej nic się nie zmienia.

**Decyzja o pozostałych MD czeka w „Zakończonych", nie w obsadzie.** Osoba,
której współpraca się skończyła, a Ty nie rozstrzygnąłeś jeszcze, co zrobić z jej
niewykorzystanym limitem, stoi od razu w dolnej sekcji — „Aktywna obsada" ma mówić
wyłącznie o tym, kto dziś pracuje. Żeby decyzja nie zginęła, nagłówek sekcji mówi,
ile ich czeka: **„Zakończone · 2 wymagają decyzji"**, a przyciski
**Zostaw jako historię / Zastąp kimś innym / Usuń z zamówienia** stoją przy
wierszu tak samo jak wcześniej.

Dwie rzeczy, które celowo działają inaczej, niż mógłbyś się spodziewać:

* **Upływ okresu CAŁEGO zamówienia nikogo nie przenosi.** Jeśli zamówienie
  skończyło się 30.09, a Ty czekasz na przedłużenie, wszyscy zostają w aktywnej
  obsadzie — o tym, że zamówienie się skończyło, mówi jego własny status i data.
  Do „Zakończonych" schodzi tylko ten, kto zszedł **wcześniej** niż zamówienie.
* **Przejście do „Zakończonych" nie zamyka rozliczeń tej osoby.** Raport zużycia
  za miesiąc, w którym jeszcze pracowała, zaimportowany później — na przykład
  sierpniowy wrzucony w połowie września — nadal dolicza się do jej historii
  i do sumy wykorzystania zamówienia. Sumy „Wykorzystano X / Y MD" i
  „Wykorzystano wartości umowy" liczą się dokładnie tak samo jak przed jej
  zejściem: wykorzystane MD i kwoty osób zakończonych zawsze się w nich mieszczą.
  O tym, czy wiersz z arkusza trafi w daną osobę, decyduje **okres jej udziału
  w zamówieniu**, a nie to, w której sekcji stoi — nie musisz niczego odblokowywać
  ani wznawiać jej współpracy. Gdy import nie dopasuje wiersza sam, przypiszesz go
  ręcznie do tej samej osoby, także zakończonej. Jedyny wyjątek to osoba **usunięta
  z zamówienia** — tam system przyjmuje, że jej tam nie było.
* **Gdy ta sama osoba w jednym miesiącu zeszła z jednego zamówienia i weszła na
  drugie**, rozliczenie za ten miesiąc idzie na zamówienie, na którym **nadal
  pracuje**. Jeśli chcesz rozbić je między oba, wpisz miesięczne zużycie ręcznie
  przy każdej z linii.

**Usunięcie konsultanta usuwa tylko jego miejsce na tym zamówieniu.** Nie
powstaje z niego nowe zamówienie okresowe, a pozostałe zamówienia tej osoby nie
zmieniają się. Stawka klienta zapisana z tej linii znika jednak z umowy —
okno usuwania (już nie zwykłe „OK / Anuluj”) mówi, czy umowa przejdzie na
stawkę innego zamówienia, czy zostanie **bez przychodu**. Osoby, która ma już
zafakturowaną kwotę albo zaraportowane MD, **nie usuniesz** (kosz jest
wyszarzony, a system odmówi): usunięcie skasowałoby jej rozliczenia. Gdy
współpraca się skończyła, użyj **Zostaw jako historię**, **Zastąp kimś innym**
albo **Zakończ**.

**Zastąpienie nie zwraca zużycia do puli — u każdego klienta.** Pod osobą, która nie jest już na aktywnej obsadzie, stoi zdanie w rodzaju
**„Jan Kowalski wykorzystał(a) 12 000,00 zł / 12 MD na tym zamówieniu przed
zakończeniem współpracy — ta kwota nie wraca do puli dostępnej dla innych
konsultantów"** (na zamówieniu kosztowym — kwota faktur; na zamówieniu MD —
liczba MD, a przy dostępie do kwot także ich wartość). Zastępca dostaje własny
budżet — MD i kwota wykorzystane przez poprzednika zostają przy poprzedniku.

**Każde usunięcie trafia do Historii zdarzeń.** Usunięcie całego zamówienia,
konsultanta z zamówienia albo zamówienia okresowego — a także próba, której
system odmówił — jest zapisywane w **Ustawienia → Historia zdarzeń** (widok dla
Admina i Finansów): kto, kiedy, czego dotyczyło i z jakim wynikiem. Ten zapis
zostaje także wtedy, gdy historia samego zamówienia znika razem z nim.

Przy osobie, która **zakończyła współpracę**, a została na zamówieniu, karta
pokazuje: „Ta osoba nie ma już aktywnej współpracy…" i trzy przyciski:
**Zostaw jako historię** (zapisuje, kto i kiedy zdecydował), **Zastąp kimś
innym** (na zamówieniu MD z pulą przy osobie nowa osoba **przejmuje pozostałe MD**
odchodzącej — zasady w „Przejęcie pozostałych MD" niżej; na zamówieniu
kosztowym i przy wspólnej puli dołącza **obok**, a historia zapisze, za kogo jest
zastępstwem) i **Usuń z zamówienia** (tylko gdy osoba
nie ma rozliczeń — inaczej przycisk jest wyszarzony). Przy zamówieniu MD
z czekającą decyzją o pozostałych MD najpierw obowiązuje przycisk „Podejmij
decyzję" (niżej).

Gdy po
zakończeniu współpracy czeka decyzja o pozostałych MD, **ikonki znikają, a na ich
miejscu stoi czerwony przycisk „Podejmij decyzję"**. Dopóki go nie klikniesz,
zablokowana jest nie tylko ta osoba, ale **całe zamówienie**: nie zadziała ani
„Uzupełnij zamówienie", ani „Zakończ", „Przywróć" i „Usuń całe zamówienie".
Jeżeli któryś z tych przycisków odmawia bez wyraźnego powodu — poszukaj na
karcie osoby z czekającą decyzją.

### Przedłużenie tworzy nowe zamówienie, nie edytuje starego

To jest celowe: na podstawie poprzedniego zamówienia wystawiono już faktury,
więc jego treść musi zostać taka, jaka była. Nowe zamówienie ma **ten sam typ
rozliczenia** co poprzednie i uruchamia się samo w dniu startu; jeżeli ta data już minęła,
staje się aktywne od razu przy zapisie. Jeżeli w samodzielnym zamówieniu
okresowym minęła również data końca, zapisuje się ono jako zakończone.

**Przy zamówieniach MD jest inaczej: przedłużenie czeka, aż poprzednikowi skończą
się dni** — nawet gdy jego własna data startu dawno minęła. Dopóki w poprzednim
zamówieniu zostają MD, nowe figuruje jako przyszłe. To celowe: niewykorzystane
dni nie mogą przepaść tylko dlatego, że zaczął się nowy okres.

### Zamiana kontraktora

Tworzy **nową linię** i domyka starą datą zamiany. Na zamówieniu **MD
z budżetem przy osobie** pozostałe dni przechodzą na nową osobę według zasad
z „Przejęcie pozostałych MD" (pula w MD — 1:1, pula w kwocie — wybierasz stawkę).
Przy
zamówieniu **kosztowym** i przy **wspólnej puli MD** nie rusza budżetu w ogóle —
zmienia się tylko osoba i jej stawki.

Gdy raport Finansów za **miesiąc zamiany** przyjdzie już po zamianie, system
zdejmuje te MD z poprzednika i **sam koryguje budżet następcy** (wpis
„Korekta budżetu następcy po rozliczeniu miesiąca zamiany” w historii) —
inaczej te same dni byłyby rozdane dwa razy. Korekta nie rusza budżetu, który
ktoś zmienił ręcznie, ani zamian sprzed 23.09.2026.

Data zamiany w przyszłości **nie wyłącza od razu** osoby, która dziś pracuje —
poprzednik dostaje datę zakończenia od razu, ale status „zakończony" dopiero gdy
ten dzień nadejdzie.

Do **Historii zamówienia** trafiają zawsze obie stawki (stara i nowa) oraz data
zamiany. Liczby MD wpisują się tam tylko przy budżecie przypisanym
osobie — przy wspólnej puli i przy zamówieniu kosztowym nie ma czego zapisać.

### Przejęcie pozostałych MD (wszyscy klienci MD)

Dotyczy każdego przeniesienia pozostałych MD na inną osobę: „Wejdź za
konsultanta", decyzji o MD, „Zastąp kimś innym" i „Zamień kontraktora".

* **Pula w MD** (budżet osoby wpisany jako liczba dni) — pozostałe MD przechodzą
  **1:1**. Pola „Przelicz po stawce" nie ma; okno mówi „Zamówienie ma pulę w MD —
  [osoba] przejmuje X MD 1:1".
* **Pula w kwocie** — okno pokazuje „Pozostało X MD × stawka osoby odchodzącej =
  kwota" i dwie opcje z gotowym wynikiem: **po stawce osoby odchodzącej** (X MD)
  albo **po stawce osoby przychodzącej** (kwota ÷ stawka przychodząca, zaokrąglone
  do 0,1 MD). Żadna nie jest zaznaczona — zapis jest nieaktywny, dopóki jej nie
  wybierzesz.

Przeniesione MD **nie są już „pozostało" u osoby odchodzącej** — jej pasek
pokazuje 0, a przy nazwisku stoi „Zastąpiony przez: [osoba] od [data]". Nowa
osoba ma plakietkę **Zastępstwo** i linię „Przejęła po: [osoba] · X MD
([sposób])". Suma zamówienia liczy te dni raz. Każde przeniesienie trafia do
**Historii zamówienia**: kto, kiedy, z kogo na kogo, od jakiej daty, ile MD
i jakim sposobem. Gdy raport Finansów za ostatni miesiąc odchodzącego przyjdzie
później, system sam koryguje przejętą pulę (wpis „Korekta przeniesionej puli
MD…").

### Karta szkicu: „Przypisz do zamówienia" i „Usuń szkic"

Osoba bez zamówienia (albo tylko ze szkicem zamówienia) stoi w pigułce
**Draft** z dopiskiem „Brak aktywnego zamówienia" — to **karta szkicu**.

**Usuń szkic** (u każdego klienta) chowa taką kartę razem ze szkicem zamówienia.
Kontrakt i dane rekrutacji zostają; karta wraca, gdy dla tej osoby powstanie
nowe zamówienie. Karty z zamówieniem innym niż szkic nie da się tak usunąć.

**Przypisz do zamówienia** (tylko Centrum e-Zdrowia) daje trzy drogi:

* **Dołącz do aktywnego zamówienia** — wybierasz zamówienie (numer, umowa
  wykonawcza, obsada), datę od, MD podstawy i opcji oraz stawki. Gdy MD
  przekraczają **wolną pulę** zamówienia (MD osób z zakończoną współpracą, o
  których nikt jeszcze nie zdecydował), okno pokazuje, o ile — zapis nadal jest
  możliwy. Osoba dostaje plakietkę **Dołączona**.
* **Wejdź za konsultanta** — wybierasz, za kogo osoba wchodzi: kogoś z zakończoną
  współpracą albo kogoś, kto ma już **przyszłą datę zakończenia** (przy każdej
  osobie widać pozostałe MD). Data wejścia to domyślnie dzień po zakończeniu.
  Jeśli osoba odchodząca jeszcze pracuje, powstaje **Zaplanowane zastępstwo od
  [data]**: odchodzący pracuje do swojego końca, a w dniu wejścia system sam
  aktywuje nową osobę i przenosi pozostałe na ten dzień MD (do tego czasu decyzja
  o MD odchodzącego jest zablokowana — żeby nie rozdać tej samej puli dwa razy).
* **Nowe zamówienie** — dotychczasowe „Uzupełnij zamówienie": osobne zamówienie
  z własną umową wykonawczą, zapisywane jako szkic.

Stawka koszt podpowiada się z kontraktu: kontrakt godzinowy × 8 („Z kontraktu:
85 PLN/h × 8"). Pole zostaje edytowalne.

---

## „Zczytaj dane z dokumentu" — co system odczyta z PDF-a

W formularzach zamówienia jest przycisk **Zczytaj dane z dokumentu**, a w oknie
**„Nowe zamówienie"** — **Zczytaj i uzupełnij całe zamówienie**, który czyta
dokument raz dla wszystkich osób naraz (opis kart i odznak — w sekcji wyżej).

> **Samo dodanie pliku niczego nie wypełnia.** Odczyt to osobne, świadome
> kliknięcie. Odczyt **nie tworzy zamówienia i nie zapisuje wgranego pliku** —
> podstawia wartości do formularza, a Ty możesz je poprawić przed zapisem. Plik
> trafia na zamówienie dopiero przy zapisie.

**System próbuje odczytać osiem rzeczy:** numer zamówienia, datę od, datę do,
stawkę przychodową (tę, którą płaci klient), jednostkę tej stawki
(godzina/dzień/miesiąc), wartość całkowitą, walutę i liczbę MD.

**Czego nie odczyta nigdy:**

* **stawki kosztowej** — tej, którą płacimy kontraktorowi. Dokument klienta jej
  nie zawiera. Zawsze wpisujesz ją sam.
* **umowy wykonawczej** (dotyczy tylko Centrum e-Zdrowia) — numery „do umowy
  ramowej" na dokumentach bywają zamienione, więc wybierasz ją sam z listy.

**Skany działają, ale w ograniczonym zakresie.** Gdy w pliku nie ma warstwy
tekstowej, system rozpoznaje pismo — ale tylko z **pierwszych 10 stron** i wolno
(kilka sekund na stronę). Zamówienie ze stawkami na 11. stronie skanu nie
zostanie odczytane.

**Co zobaczysz po odczycie:**

* pomarańczowy baner **„Sprawdź dane!"** — pojawia się wtedy, gdy system sam nie
  jest pewien tego, co odczytał (nieczytelne pole, jednostka stawki inna niż
  w formularzu, brak dat okresu, odczyt bez AI). **Wypunktowane powody widzi tylko ten, kto
  ma dostęp do kwot** — pozostali dostają jedno ogólne zdanie „Sprawdź odczytane
  dane przed zapisem.",
* **osobne, czerwone ostrzeżenie przy polu numeru** — to inne miejsce niż baner,
  więc brak banera nie znaczy, że numer jest w porządku. Sprawdź oba,
* **informację, która reguła klienta zadziałała** — „Zastosowano reguły odczytu:
  …" albo „Dla tego klienta nie ma jeszcze własnych reguł odczytu PDF — pola
  wypełnił odczyt ogólny". To jest odpowiedź na pytanie „czy u tego klienta
  reguła w ogóle jest włączona": jeżeli spodziewasz się reguły z sekcji poniżej,
  a ten komunikat mówi „nie ma", zgłoś to administratorowi.

**Uwaga na różnicę w nadpisywaniu:**

* **Karta pojedynczego konsultanta (Okresowe):** odczyt **nadpisuje bez pytania**
  to, co już wpisałeś — ale tylko te pola, które dokument faktycznie dostarczył.
  Do tego dochodzi **stawka kosztowa**: jeżeli odczyt zmieni jednostkę stawki,
  Twoja kwota zostanie przeliczona na nową jednostkę, choć w dokumencie jej nie
  było. Po odczycie sprawdź oba pola ze stawkami.
* **Zamówienia MD i kosztowe:** system **pyta „Tak/Nie"** i wymienia różnice pole
  po polu, zanim cokolwiek zmieni. Wypełnienie pustego pola nie jest
  rozbieżnością i odbywa się bez pytania.
  Wartość, którą wpisał poprzedni odczyt innego PDF-a, też nie jest Twoim
  wpisem: kolejny odczyt zastępuje ją bez pytania, także pustą, gdy nowy
  dokument danego pola nie ma.

**Przy dodawaniu konsultanta do istniejącego zamówienia najpierw wybierz osobę** — bez tego
przycisk odczytu jest nieaktywny. System wiąże wtedy stawkę i liczbę MD
z wierszem **tej konkretnej osoby** w dokumencie, a gdy nie potrafi tego zrobić
jednoznacznie, **zostawia oba pola puste zamiast zgadywać**. Puste pole po
odczycie to nie awaria — to odmowa zgadywania.

> Plik dołożony w okienku **Dodaj konsultanta do zamówienia** służy **wyłącznie**
> do odczytu i **nie jest nigdzie zapisywany**. PDF zamówienia wgrywasz w
> **Uzupełnij zamówienie**.

**Limity i formaty.** Plik do 25 MB. Okno wyboru pliku bywa węższe niż to, co
system obsługuje: w zamówieniach zbiorczych i w edycji zamówienia przyjmowany
jest wyłącznie `.pdf`, a przy dodawaniu konsultanta i przy przedłużeniu
pojedynczego zamówienia także `.docx`. O formacie decyduje treść pliku, nie
jego nazwa: PDF zapisany jako `.docx` zostanie przeczytany jak PDF. Odczyt
korzysta z modułu AI — jeżeli
administrator go wyłączy albo ustawi miesięczny limit i ten się wyczerpie,
zobaczysz komunikat „Odczyt AI jest chwilowo niedostępny (…). Wpisz dane
ręcznie." Domyślnie limitu nie ma, więc w praktyce oznacza to świadome
wyłączenie funkcji przez administratora.

**Gdy AI nie zadziała, włącza się odczyt awaryjny** — zgrubny: bierze pierwsze
dwie daty i pierwszą kwotę z dokumentu, a **numeru zamówienia sam nie znajduje**
(wyjątkiem są klienci z własną regułą numeru, np. Nordea i Bank Pocztowy — tam
numer wyszukiwany jest po etykiecie i działa też w trybie awaryjnym). Poznasz go
po powodzie „Odczyt awaryjny (bez AI) — zweryfikuj wszystkie pola" w banerze.

**W interfejsie przycisk „Zczytaj dane z dokumentu" jest dostępny administratorowi
i Delivery Leadowi przypisanemu do tego klienta.** Nieprzypisany Delivery Lead
widzi klienta i jego dane operacyjne, ale bez formularzy zawierających stawki
i bez pliku źródłowego PO. Pozostałe role — w tym Finanse, Talent Community
Manager i Head of Recruitment — nie wykonują tego odczytu.

**Kwoty z odczytu widzi tylko administrator i przypisany Delivery Lead.** Liczba
MD jest wielkością operacyjną, nie finansową.

---

## Zamówienia ze skrzynki — „Osoby i plan zapisu"

Kolejka dokumentów z maila jest w **Kontrakty → „Skrzynka zamówień"**. Liczba
przy „Kontraktach" w menu to dokumenty czekające na sprawdzenie. Do 22.09.2026
kolejka miała w menu własną pozycję „Zamówienia z maila", a stare linki
z powiadomień nadal do niej prowadzą.

Automatyczny odczyt załączników ze skrzynki **zamowienia@b2bnetwork.pl**
przygotowuje plan dla osób rozpoznanych w dokumencie. Trzy sytuacje zawsze
czekają na Ciebie w kolejce: **waluta inna niż PLN** (zapis bierze walutę
z dokumentu), **okres niepotwierdzony regułą klienta** u BIK, Polkomtela, BNP,
PFRON i Credit Agricole (tam liczy się wyłącznie okres z dokumentu) oraz
**powrót po przerwie osoby, która ma w bazie imiennika**. Wartość całego
dokumentu trafia na zamówienie tylko wtedy, gdy dokument dotyczy jednej osoby. Przy dopasowaniu osoby
sprawdza **pełną, aktualną listę konsultantów przypisanych umową do tego
klienta**, także z dawniej zakończonymi umowami. Nie szuka wśród osób innego
klienta.

**Spacje, wielkość liter, polskie znaki i kolejność imienia oraz nazwiska
nie wymagają ręcznego potwierdzenia**, jeśli pasuje dokładnie jedna osoba
u klienta. Dotyczy to także niewidocznych znaków formatowania z PDF-a
oraz różnych znaków łącznika w nazwisku dwuczłonowym. System porównuje
następnie osobę wraz z jej stawką i jednostką z polami dokumentu. Sama zgodność
kwot bez potwierdzenia nazwiska nie wystarcza do automatycznego zapisu.

**Drobna literówka albo odmiana imienia i nazwiska nie wyklucza dopasowania.**
Na przykład „Konrada Korcza" może zostać powiązany z „Konrad Korcz".
Takie dopasowanie wymaga potwierdzenia osoby przed zapisem. Gdy pasuje kilka
osób, system pokazuje ich imiona i nazwiska, identyfikatory rekordów oraz
numery kontraktów do ręcznego rozstrzygnięcia.

**Żadne zamówienie na osobę spoza listy konsultantów klienta nie zapisze się
samo — u żadnego klienta i na żadnym typie zamówienia.** Na zamówieniu MD albo
kosztowym dotyczy to także osoby z zakończoną współpracą. Automat nie wznowi
zakończonego kontraktu i nie założy nowej osoby: plan pokazuje przy niej
**„Decyzja o osobie — w oknie zamówienia"** z tym samym komunikatem co karta
w oknie zamówienia („… nie ma już aktywnej współpracy …" albo „Nie znaleziono …
w systemie"), a **„Zastosuj" jest wtedy wyłączone**. Kliknij **Rozstrzygnij
w oknie zamówienia**: otworzy się zakładka „Zamówienia" klienta z PDF-em z maila,
już odczytanym — jako **Uzupełnij zamówienie**, gdy zamówienie o tym numerze
już jest, inaczej jako **Nowe zamówienie**. Tam decydujesz o osobie (zostaw jako
historię / wznów / zastąp / usuń) i zapisujesz. **Po zapisie dokument sam schodzi
z kolejki** (zakładka „Zapisane ręcznie", z numerem zamówienia). Zamknięcie okna
bez zapisu zostawia dokument w kolejce.

**Na zamówieniu okresowym brak osoby u klienta przygotowuje nowy draft
z numerem, okresem i stawką przychodową z maila — ale go NIE zapisuje.**
Kontraktor powstaje z podpisanej umowy, nie z zamówienia klienta, więc wpis
czeka w „Do weryfikacji” z powodem „… nie ma jej wśród konsultantów tego klienta
ani w bazie — zamówienie czeka na podpisaną umowę B2B”. Zapisze się sam
w ciągu godziny od chwili, gdy umowa zostanie oznaczona jako **podpisana
obustronnie**. Jeśli konsultant pracuje na innej podstawie (umowa o pracę,
zlecenie) i umowy B2B nie będzie, zapisz wpis ręcznie przyciskiem
**„Zastosuj”**. Po zapisie DL otrzymuje raz
powiadomienie „Nowy kontraktor [osoba] w [klient] — uzupełnij dane: stawka kosztowa”;
kliknięcie otwiera zakładkę „Zamówienia” tego klienta.
Aktualizacje tego draftu nie powtarzają powiadomienia. Jeśli klient nie miał
w tej chwili przypisanego Delivery Leada, powiadomienie nie przepada: przychodzi
raz, przy najbliższym dobowym przebiegu po przypisaniu, o ile zamówienie jest
nadal draftem.

**Gdy osoby nie ma u klienta, ale w bazie jest dokładnie jedna osoba o tym
imieniu i nazwisku** (także zapisanym w PDF-ie bez polskich znaków, np.
„Lukasz Gradzki” = „Łukasz Grądzki”), **automat jej nie dopina** — samo nazwisko
nie dowodzi, że to ta sama osoba. Wpis czeka w weryfikacji z powodem
„W bazie jest już osoba … (#numer) … zastosuj ręcznie”. Sprawdź, że to ta sama
osoba, i kliknij **„Zastosuj”**: system dopina istniejącą kartę, bez zakładania
drugiej. Kilka takich osób w bazie nadal wymaga wskazania właściwej.

System uzupełnia istniejący draft, także opisany nazwą rekrutacji. Aktywne lub
kończące się zamówienie ma pierwszeństwo przed draftem: kolejny okres tworzy
przedłużenie przy dotychczasowym kontrakcie. Na zamówieniu okresowym **powrót po przerwie** (poprzednie
zamówienie tej osoby jest już zakończone) **tworzy nowe zamówienie na nowy
okres. Zakończone zamówienie zostaje bez żadnej zmiany** — na nim rozliczono już
faktury. Nowe zamówienie ma w historii odnośnik do poprzedniego i faktyczny
odstęp w dniach, a z poprzedniego zamówienia przejmuje to, czego PDF nie niesie:
umowę wykonawczą i część umowy (e-Zdrowie), umowę ramową, rekrutację, liczbę
godzin rozliczeniowych i opis. Linia zamówienia zbiorczego (MD) nie jest traktowana jako
„poprzednie zamówienie”. Rzeczywisty konflikt okresów albo kilka możliwych osób
lub kontraktów nadal wymaga decyzji. Draft uzupełniony już
PDF-em z maila **albo z dołączonym plikiem zamówienia** nie jest nadpisywany
zamówieniem tej samej osoby na **inny, rozłączny okres** (np. wrzesień, a potem
październik–grudzień) — kolejny dokument zakłada osobne zamówienie. Ten sam
numer albo nachodzący okres (poprawiony dokument) nadal uzupełnia ten sam draft.
Draft wypełniony ręcznie, **bez pliku zamówienia**, system traktuje jak pusty —
dołącz do niego PDF, jeśli ma zostać nietknięty. Draft na linii zamówienia MD
zostaje przy linii: osobnego zamówienia obok niej system sam nie założy.

**Mail nie cofa wypowiedzenia umowy.** Jeżeli umowa tej osoby została
wypowiedziana („Zakończ współpracę”, także z datą w przyszłości), zamówienie
z maila, które **wychodzi poza datę końca umowy**, zapisuje się jako **draft**
i nie aktywuje się samo — ani przy odczycie maila, ani po podpisie umowy.
Wypowiedziana umowa nie wraca przez to do aktywnych; o powrocie do współpracy
decydujesz Ty. Zamówienie mieszczące się w całości przed datą końca umowy (np.
za ostatnie miesiące przed zakończeniem) aktywuje się normalnie. Jeśli po
wypowiedzeniu przedłużysz umowę aneksem albo przywrócisz ją bezterminowo,
kolejne zamówienia z maila w nowym okresie też aktywują się normalnie.

**„Automat: pewne” uruchamia zapis bez przycisku „Zastosuj”, dopóki automat jest
włączony.** Wynik jest w zakładce **„Zapisane automatycznie”**. **Nie dotyczy to
pierwszego zamówienia na osobę spoza listy konsultantów klienta** — takie czeka
na podpisaną umowę (patrz niżej). Administrator może automat **wyłączyć bez
wdrożenia** — wtedy pewny plan czeka w **„Do weryfikacji”** z powodem
„Automatyczny zapis jest wyłączony…” i zapisujesz go przyciskiem „Zastosuj”.
Wyłącznik obejmuje także „Przelicz plan”.
W zamówieniu okresowym brak niewykorzystywanej wartości całkowitej nie blokuje
zapisu z powodu technicznej niejasności nazwy tego pola. Rzeczywiste sprzeczności
stawek oraz budżety zamówień kosztowych i MD nadal wymagają kontroli.
Cały dokument zapisuje się wspólnie: błąd jednej osoby wycofuje
zapis dokumentu i pozostawia konkretny powód weryfikacji.

**Automatycznie zakładany jest tylko kontraktor, którego w bazie NIE MA.**
Jeżeli osoby nie ma wśród konsultantów tego klienta, ale ktoś o dokładnie tym
imieniu i nazwisku jest już w bazie, dokument czeka w **„Do weryfikacji”**,
a kolejka pisze wprost, kogo znalazła — na przykład „Piotr Michałowski (#11)
ma kontrakt #456 u klienta „Powszechna Kasa Oszczędności Bank Polski S.A””.
Sprawdź wtedy dwie rzeczy: czy dokument nie dotyczy **tego samego klienta
zapisanego pod drugim rekordem** (wtedy zamówienie należy do istniejącej
współpracy, a nie do nowego kontraktora), i czy to na pewno ta sama osoba,
a nie imiennik. Dopiero potem „Zastosuj” — zapis dopnie istniejącą kartotekę
zamiast zakładać drugą. Kilku różnych ludzi o tym samym imieniu i nazwisku
system wypisuje z numerami i **nie wybiera żadnego**.

**Numer NIP prowadzi do klienta kanonicznego.** Scalenie zdublowanego rekordu
klienta („Scal z…”) działa też na pocztę zamówień: kolejne dokumenty z tym
numerem trafiają do rekordu, który po scaleniu został, razem z jego listą
konsultantów. Jeżeli ten sam numer widnieje przy **dwóch osobnych** klientach,
system nie zgaduje — dokument trafia do „Do weryfikacji” jako nierozpoznany
klient, dopóki duplikat nie zostanie scalony.

Gdy mail przychodzi przed umową, draft czeka na koszt i podpis. Po obustronnym
podpisaniu umowy system pobiera koszt z umowy i aktywuje kompletny draft.
Jeśli podpisana umowa była pierwsza, koszt jest uzupełniany już przy odczycie maila.

**Brutto/netto jest sprawdzane dla każdej odczytanej stawki na podstawie
dokumentu.** Przy oznaczeniu brutto system dzieli kwotę przez **1,23** przed
wpisaniem jej do planu. Na przykład **100,08 zł/h brutto → 81,37 zł/h netto**;
obok stawki netto widać oryginalną kwotę brutto. Jawne netto pozostaje bez
przeliczenia. Brak jednoznacznego oznaczenia oznacza niepewny odczyt do
weryfikacji. **Wyjątkiem jest Nordea: stawka jest zawsze netto za godzinę,
bez dzielenia przez 1,23. U Aliora stawka jest domyślnie netto: brak oznaczenia
nie jest wątpliwością, a jawne „brutto” w tabeli Konsultantów kieruje zamówienie
do weryfikacji bez przeliczenia. W PFRON stawka z pola „Stawka za jedną Roboczogodzinę”
jest brutto i zawsze jest dzielona przez 1,23. Kolumna „Quantity (max Xh/month)” nie określa
liczby godzin ani MD w planie. Summary jest pomijane przed odczytem danych.**

**„Przelicz plan"** odświeża oczekujący wpis z zachowanego PDF-a i aktualnej
listy konsultantów. Użyj go po poprawieniu przypisania osoby albo zasad odczytu.
Dla PFRON ponownie wybiera aktywny rekord klienta, odczytuje numer z nazwy PDF
i datę końca z pola „Termin wykonania Prac”. Dla Nordei i Aliora ponownie stosuje
regułę odczytu klienta do zachowanego PDF-a — wpis zatrzymany przed poprawką
reguły przelicza się według aktualnej. Dla pozostałych klientów zachowuje
rozpoznanego klienta, numer i okres. Ponownie sprawdza stawki oraz dopasowanie osób.
**Pewny plan zapisuje się automatycznie (gdy automat jest włączony); plan
z konkretną wątpliwością pozostaje w weryfikacji.** Przycisk jest dostępny administratorowi albo
Delivery Leadowi przypisanemu do klienta, jeśli wpis ma plik źródłowy.
Przeliczenie jest możliwe tylko przed zapisaniem pierwszego zamówienia
z danego wpisu.

**Każdy wstrzymany wpis przelicza się sam co godzinę, w godzinach 8:00–18:00.**
Przy każdym sprawdzeniu skrzynki w tych godzinach system bierze wszystko, co
czeka w „Do weryfikacji" i w „Nierozpoznane", i robi z tym dokładnie to, co
„Przelicz plan": pewny plan zapisuje się automatycznie, plan z wątpliwością
zostaje w weryfikacji już z aktualnymi powodami. Nie trzeba przesyłać zamówienia
ponownie — ten sam PDF wysłany drugi raz system i tak rozpoznaje jako duplikat
i pomija.

**Pocztę system sprawdza dalej całą dobę** — nowe zamówienie przysłane
wieczorem pojawia się w kolejce tego samego dnia. Ograniczenie do godzin pracy
dotyczy wyłącznie ponownego przeliczania tego, co już w kolejce wisi. Przycisk
**„Pobierz zamówienia z maila"** działa o każdej porze i przelicza wstrzymane
wpisy od razu, także po 18:00.

Najczęstsza przyczyna wstrzymania znika **gdzie indziej niż w kolejce**:
podpisanie umowy B2B nowego kontraktora albo uzupełnienie NIP-u na karcie
klienta. Dlatego wpis wraca w każdym biegu, a nie tylko po zmianie reguły
odczytu.

**Co się dzieje, gdy przyczyna nadal trwa,** zależy od tego, na co wpis czeka:

* **Nowy kontraktor bez umowy w systemie** (dokument wymienia osobę, której nie
  ma jeszcze na liście konsultantów klienta i która nigdzie nie ma trwającej
  współpracy) — wpis czeka **bez limitu czasu i bez powiadamiania**. Podpisanie
  umowy trwa zwykle dłużej niż kilka godzin, więc wcześniejsza karta byłaby
  przedwczesna. Zamówienie zapisze się samo w ciągu godziny od chwili, gdy
  umowa pojawi się w systemie.
* **Każda inna przyczyna** (niedopasowana osoba, stawka poza pasmem, niepewny
  odczyt, błąd danych) — po **trzech nieudanych próbach z rzędu** do Delivery
  Leada klienta idzie karta „Sprawdź zamówienie z maila" ze wskazaniem
  zamówienia i przyczyny. Wpis jest sprawdzany dalej. Próby liczą się tylko
  w godzinach pracy, więc zamówienie wstrzymane o 17:30 dobija do trzeciej
  próby następnego przedpołudnia, a nie w nocy.

Zmiana przyczyny zaczyna liczenie od nowa — trzy próby dotyczą **tego samego**
problemu. **Automatyczne dokończenie zamówienia nie wysyła powiadomienia**:
widać je w historii poniżej.

**„Historia automatycznej weryfikacji"** na dole widoku pokazuje **tylko te
sprawdzenia, które coś zmieniły**: zapisały zamówienie, zmieniły powód
wstrzymania albo wysłały kartę Delivery Leadowi. Wiersz niesie datę i godzinę,
liczbę wpisów sprawdzonych, zaakceptowanych i wstrzymanych, a rozwija się do
konkretnych dokumentów — każdy z powodem i linkiem do wpisu. Delivery Lead widzi
w niej wpisy swojego portfela klientów.

Nad tabelą stoi zdanie **„Sprawdzone ostatnio: [data, godzina]"**. To ono mówi,
czy mechanizm działa — sprawdzenie, po którym nic się nie zmieniło, przesuwa
tylko ten znacznik i nie dopisuje wiersza. Pusta tabela pod aktualnym
znacznikiem znaczy „nic nie wymagało zmiany", a nie „nie działa". Wpisy sprzed
wdrożenia tej zasady zostają w historii i znikają same po 30 dniach.

**Wpis z odczytem awaryjnym (AI było chwilowo niedostępne przy odczycie maila)
system próbuje przeczytać AI ponownie sam** — przy kolejnych sprawdzeniach
skrzynki, najwyżej 3 razy. Gdy się uda, wpis przechodzi zwykłą ścieżkę: pewny
plan zapisuje się automatycznie, plan z wątpliwością zostaje w weryfikacji z
aktualnymi powodami. Powód awarii AI widać w banerze, np. „Odczyt awaryjny (AI:
przekroczony czas odpowiedzi AI) — sprawdź zgodność pól z PDF". Po trzech
nieudanych próbach dochodzi komunikat „Ponowny odczyt AI nie powiódł się 3×" —
wtedy sprawdź pola z PDF i zastosuj ręcznie albo odrzuć.

**Gdy odczyt AI jest wyłączony albo wyczerpał miesięczny limit** (Ustawienia →
AI), poczta działa dalej: mail dostaje odczyt awaryjny z powodem „Odczyt
awaryjny (AI: odczyt AI zablokowany w ustawieniach AI …)" i czeka w weryfikacji.
Taka odmowa **nie zużywa** żadnej z trzech prób ponownego odczytu — system
spróbuje znowu, gdy limit pozwoli. Od 09.2026 odczyty z poczty są też liczone
w telemetrii AI (Ustawienia → AI pokazuje je jako `order_parser`); wcześniej
widać tam było wyłącznie odczyty uruchamiane ręcznie w formularzach.

## Co system robi sam

* **Zakłada umowę i szkic zamówienia** po potwierdzeniu obustronnie podpisanej
  umowy w Generatorze umów B2B — umowa jest od razu **Aktywna**: okres od daty
  startu z umowy, bezterminowo, stawka kosztowa godzinowa z umowy. Po samym
  przejściu kandydata na etap „zatrudniony" (bez podpisanej umowy) umowa powstaje
  jako **szkic**. U Polkomtela szkicu zamówienia nie ma — patrz sekcja tego
  klienta.
* **Przenosi dane zamówienia do umowy tej osoby** przy każdym zapisie zamówienia.
  Z najnowszego uzupełnionego zamówienia (data rozpoczęcia + stawka przychodowa)
  do umowy trafiają: **okres zamówienia** — osobne pole, okres umowy się nie
  zmienia; kolejne zamówienie nadpisuje poprzedni okres — oraz **stawka
  przychodowa**. Stawka z zamówienia zaczynającego się w przyszłości obowiązuje
  w umowie dopiero od jego daty startu. Szkic umowy, który dzięki temu ma
  komplet danych, sam przechodzi na **Aktywny**.
* **Uzupełnia brakujący okres zamówienia raz na dobę.** Umowa, której
  zamówienia nikt nie zapisał od wdrożenia synchronizacji, dostaje w nocy sam
  **okres zamówienia** z najnowszego uzupełnionego zamówienia. Stawki, jednostki
  i waluty ten przebieg nie zmienia — przeniesie je dopiero najbliższy zapis
  zamówienia.
* **Prowadzi stawki umowy w zł/h** (1 MD = 8 godzin). W module Kontrakty
  stawki są godzinowe: zamówienie w MD **zostaje w MD**, a do umowy trafia jego
  stawka przeliczona na godzinę (1340 zł/MD → 167,50 zł/h). Umowa z generatora
  jest godzinowa i taka zostaje; umowa ryczałtowa (zł/mc) przechodzi na zł/h
  przy pierwszym zamówieniu w MD. Kwoty miesięczne się nie zmieniają — umowa
  liczy standardowy miesiąc roboczy 168 godzin (21 MD × 8 h), tym samym
  miesiącem system liczy MRR i marżę każdej umowy. Stawka kosztowa wraca do
  zamówienia w MD pomnożona przez 8, więc ta sama kwota.
* **Ustawia stawkę kosztową zamówienia z umowy.** Umowa jest jej jedynym
  źródłem: pole w zamówieniu jest tylko do odczytu (dopisek „z kontraktu"),
  a zaplanowane w umowie zmiany stawki — także kilka naraz, np. od 01.10 i od
  01.12 — wchodzą do zamówienia każda w swoim dniu, w jednostce zamówienia.
  Zamówień zakończonych nie przepisuje. **Nie dotyczy konsultantów na
  zamówieniach zbiorczych MD i kosztowych** — tam stawkę kosztową nadal
  ustawiasz przy konsultancie.
* **Awansuje szkic pojedynczej osoby na Aktywne** w chwili zapisu, gdy komplet
  danych jest na miejscu. Nowe zbiorcze MD z wyborem trybu budżetu aktywujesz
  sam w edycji zamówienia.
* **Uruchamia zamówienia przyszłe** w dniu ich startu — z jednym wyjątkiem: przy
  zamówieniach MD następca czeka dodatkowo, aż poprzednikowi skończą się dni,
  więc mimo minionej daty startu potrafi jeszcze przez jakiś czas figurować jako
  przyszły.
* **Domyka po dacie zakończenia poszczególne zamówienia** — zarówno okresowe,
  jak i konsultantów na zamówieniach kosztowych i na zamówieniach MD ze wspólną
  pulą. Domknięte zamówienie NIE przenosi osoby do „Zakończonych" — o tym
  decyduje umowa (patrz opis filtrów wyżej); osoba bez kolejnego zamówienia
  dostaje dopisek „Brak aktywnego zamówienia".
  **Jedynym wyjątkiem są konsultanci z własnym budżetem MD** — tam o końcu
  decyduje budżet, nie kalendarz, więc osoba z niewykorzystanymi dniami pracuje
  dalej.
* **Samego zamówienia zbiorczego data nie zamyka.** Numer zostaje „Aktywny",
  dopóki nie klikniesz **Zakończ** albo dopóki nie wyczerpie się budżet — więc
  można do niego dopisywać kolejne osoby także po dacie z dokumentu, mimo że
  wcześniej dodani zostali już domknięci.
* **U BIK i Polkomtela kończy zamówienie MD ostatnia osoba, która wyczerpie
  swój limit MD.** Zamówienie zostaje „Aktywne", dopóki choć jeden konsultant na
  obsadzie ma niewykorzystane dni; gdy wszyscy zejdą do zera, przechodzi na
  **„Zakończone"** samo (patrz sekcja BIK). Osoba, która **zakończyła
  współpracę** i została na zamówieniu jako historia, **jest przy tym pomijana** —
  jej niewykorzystane dni nie trzymają zamówienia otwartego.
* **Po każdej zmianie przelicza budżet na nowo**, dzięki czemu powtórny import
  tego samego miesiąca nie odejmuje dni drugi raz. Przy budżecie przypisanym
  osobie możesz mimo to wpisać właściwą pozostałość ręcznie — system potraktuje
  to jako korektę i nie skasuje jej przy kolejnym imporcie.
* **Przestawia zamówienie na „Wyczerpane"**, gdy pula zejdzie do zera; od tej
  chwili nie przyjmuje ono nowych konsultantów.
* **Przelicza stawkę przy zmianie jednostki** — gdy odczyt z dokumentu zmieni
  jednostkę (np. z miesięcznej na dzienną), obie wpisane stawki są przeliczane
  i dostajesz o tym komunikat.
* **Wysyła powiadomienia** — patrz następna sekcja.

Automaty chodzą **raz na dobę**, licząc od ostatniego restartu aplikacji — nie ma
stałej godziny. Wejście na zakładkę „Zamówienia" dodatkowo uruchamia zamówienia
przyszłe, którym minął dzień startu, i kończy zamówienia BIK, w których wszyscy
wyczerpali limit MD, ale **niczego nie zamyka po dacie** — na to trzeba poczekać
na nocny przebieg.

## Co zawsze robisz ręcznie

* **Stawkę kosztową** — nie ma jej w żadnym dokumencie klienta. Wpisujesz ją
  (i planujesz podwyżki) **w umowie**, nie w zamówieniu — zamówienie przejmie ją
  samo. Pole w zamówieniu jest edytowalne tylko wtedy, gdy umowa stawki
  kosztowej jeszcze nie ma. Wyjątek: przy konsultancie na zamówieniu zbiorczym
  MD albo kosztowym stawkę kosztową wpisujesz jak dotąd — w jego linii.
* **Sprawdzenie tego, co odczytał PDF.** Odczyt jest podpowiedzią, nie źródłem
  prawdy — zwłaszcza gdy zapalił się baner „Sprawdź dane!".
* **Jednostkę stawki** (godzina / dzień / miesiąc) — ustawiasz sam, ale odczyt
  z dokumentu potrafi ją nadpisać, a każda zmiana jednostki od razu przelicza
  obie wpisane stawki. Po każdej zmianie sprawdź kwoty w obu polach.
* **Wgranie pliku zamówienia** przy zamówieniach okresowych — formularz
  zakładania nie ma pola na plik.
* **Stawkę kosztową w umowie** konsultanta wziętego z „Bazy Nexus" — umowa
  powstaje jako szkic bez stawki kosztowej; gdy ją uzupełnisz, przejdzie na
  Aktywną sama (okres i stawkę przychodową dostanie z zamówienia).
* **Decyzję o niewykorzystanych MD** po zakończeniu współpracy (patrz niżej).

---

## Powiadomienia — co przyjdzie, kiedy i gdzie

Sprawy zamówień i kontraktów Twoich klientów mają **własny panel „Moi klienci"**
na pulpicie Delivery Leada, zaraz pod „Moje zadania". W „Moje zadania →
Powiadomienia" zostają wyłącznie zdarzenia rekrutacyjne (np. nowy kandydat).

Maile wymienione poniżej wychodzą tylko wtedy, gdy administrator włączy
automatyczną wysyłkę oraz typ „Alerty klientów i umów" w **Ustawienia → System →
Powiadomienia**. Karty w panelu powstają niezależnie od tych przełączników.
Po włączeniu mail przychodzi wyłącznie dla nowych zdarzeń; wcześniejsze karty
i sprawy z okresu wyłączenia nie uruchamiają zaległej wysyłki.

### Panel „Moi klienci" — co w nim jest

Każda karta to **jedna sprawa**: nazwa klienta, pigułka (ile dni zostało albo
czego brakuje), treść z imieniem i nazwiskiem kontraktora, **checkbox „zrobione"**
i przycisk, który otwiera **konkretne** zamówienie, kontrakt albo dokument —
nie samą zakładkę. Karty są pogrupowane:

| Sekcja | Sprawa | Kiedy powstaje | Przypomnienia |
|---|---|---|---|
| Kończące się zamówienia i umowy | **Zamówienie okresowe** kończy się (a u klientów z rozszerzonymi alertami — także **zamówienie MD/kosztowe**, osobno dla każdego konsultanta) | 30 dni przed datą końca — **pierwsza karta od razu z mailem**. **Nie powstaje, gdy do zamówienia dodano już przyszłe zamówienie** (także szkic) — wtedy nic nie trzeba robić, a otwarta karta zamyka się sama; to samo dotyczy powiadomienia w dzwonku. Samo przyszłe zamówienie dostaje kartę na tych samych zasadach | co 7 dni bez maila; **14 dni przed — mail**; **7 dni przed — wysoki priorytet (czerwona karta) + mail** |
| | **Umowa ramowa** klienta wygasa | 30 dni przed wygaśnięciem | jak wyżej |
| | **Kontrakt** konsultanta kończy się (umowa B2B ma datę końca dopiero po „Zakończ współpracę") | 30 dni przed końcem | jak wyżej |
| | **[Klient] — wygasł konflikt z kandydatem** (NDA / cooling-off, czarna lista klienta albo konkurencja z datą wygaśnięcia) | data wygaśnięcia wpisu w „Konflikty" na profilu kandydata minęła — kandydata znów można proponować temu klientowi; przycisk otwiera profil kandydata | raz; bez maila |
| | **Mało MD** — konsultantowi (budżet przy osobie) albo całemu zamówieniu (wspólna pula) | zostało **21 MD lub mniej** | co 7 dni; **wysoki priorytet + mail**, gdy zostało MD na ok. **7 dni roboczych** pracy przy dotychczasowym tempie tego zamówienia |
| | **Wysokie zużycie podstawy MD** — tylko u klientów z rozszerzonymi alertami, osobno dla każdego konsultanta | zużyto **80% lub więcej** podstawy MD (zakres opcjonalny nie wchodzi do rachunku) | co 7 dni; bez eskalacji — pilny sygnał daje wiersz wyżej |
| | **Kończy się budżet zamówienia kosztowego** | zostało **10 000 zł lub mniej** | co 7 dni; **wysoki priorytet + mail**, gdy budżet wystarczy na ok. **7 dni roboczych** przy dotychczasowym tempie faktur |
| | Zamówienie **wyczerpane** (kosztowe albo wspólna pula MD) | budżet zszedł do zera | raz |
| Nowi kontraktorzy — draft zamówienia | **Nowy kontraktor u [klient] — uzupełnij zamówienie** | umowa oznaczona w Generatorze umów jako **podpisana obustronnie** (powstaje draft kontraktu i zamówienia); karta wypunktowuje braki: stawka przychodowa, okres zamówienia, numer zamówienia | co 7 dni, dopóki czegoś brakuje |
| | **[Klient] — [kto] bez zamówienia** | zamówienie konsultanta wisi w statusie **Draft** (z innego źródła niż podpis umowy); pierwszy draft z maila ma osobne jednorazowe powiadomienie | co 7 dni |
| | **Brak stawki przychodowej** | aktywne zamówienie bez stawki, którą płaci klient | co 7 dni |
| Zamówienia z maila do weryfikacji | **Sprawdź zamówienie z maila: [numer]** — „Zamówienie dla [kto] do [klient] czeka na ręczną weryfikację”, z powodem | **trzy nieudane próby automatycznego dokończenia z rzędu** (czyli po ok. 3 godzinach pracy, licząc tylko 8:00–18:00). Zamówienie czekające na podpis umowy nowego kontraktora **nie wysyła karty nigdy**; wpis bez rozpoznanego klienta też nie — nie ma komu | co 7 dni |
| Decyzje po zakończeniu współpracy | **Decyzja MD po zakończeniu współpracy** | konsultant zakończył pracę na zamówieniu MD — **zawsze**, także gdy nie zostało ani jedno MD | raz; **nie da się jej odhaczyć** — zamyka ją decyzja w zamówieniu |
| | **[Klient] — brak kolejnego zamówienia** | dzień po końcu zamówienia osoba nie ma u tego klienta następnego zamówienia — aktywnego, przyszłego ani szkicu | co 7 dni, do dodania zamówienia |

**Tempo zużycia** liczone jest z raportów tego zamówienia: suma zaraportowanych
MD (albo faktur) podzielona przez dni robocze od startu zamówienia do końca
ostatniego raportowanego miesiąca. Zamówienie MD bez żadnego raportu przyjmuje
szacunek 1 MD dziennie na osobę. Zamówienie kosztowe bez faktur nie ma tempa —
dostaje przypomnienie standardowe, a na końcu alert o wyczerpaniu.

**Klienci z rozszerzonymi alertami (dziś BNP)** dostają o tym samym zamówieniu
**dwa niezależne sygnały i nigdy nie są one łączone w jedną kartę**:

* **koniec okresu** — 30 dni przed datą końca, potem co 7 dni, aż sprawa się
  rozwiąże (skolejkujesz następne zamówienie albo zakończysz obecne). U
  pozostałych klientów tę kartę dostają wyłącznie zamówienia okresowe, bo tam
  zamówienie MD kończy zwykle wyczerpanie budżetu, nie kalendarz;
* **zużycie podstawy MD** — gdy konsultant zejdzie **80% swojej podstawy**,
  niezależnie od tego, ile czasu zostało do końca okresu. To wczesne
  ostrzeżenie: przy zamówieniu na 220 MD alert „mało MD" (21 MD pozostałych)
  wypada dopiero przy ~90% zużycia, za późno na wynegocjowanie i wystawienie
  nowego dokumentu PO.

Gdy oba warunki są spełnione naraz, w panelu stoją **dwie karty** i każdą
odhaczasz osobno. Listę klientów objętych tymi alertami ustawia administrator
(zmienna `EXTENDED_ORDER_ALERT_CLIENT_IDS`); dopóki jest pusta, **nic się nie
zmienia dla nikogo**.

**Checkbox „zrobione"** zdejmuje kartę od razu, **zatrzymuje dalsze przypomnienia
tej sprawy** (także wtedy, gdy problem nadal trwa) i zapisuje w historii, kto
i kiedy odhaczył sprawę oraz którego zamówienia albo kontraktora dotyczyła
(wpis trafia też do historii zamówienia). Historię i eksport do Excela z czasem
reakcji otwiera przycisk **„Historia i eksport"** na dole panelu.

**Karta znika sama, gdy przyczyna ustąpi** — np. zamówienie zostało przedłużone,
draft uzupełniony, a dokument z maila zweryfikowany. Takie zamknięcie jest
w historii osobno („Zamknięte automatycznie") i nie liczy się jako Twoje
odhaczenie. Przedłużenie z nową datą końca to nowa sprawa: przypomnienia ruszą
znowu 30 dni przed nową datą.

**Brak kolejnego zamówienia widzi też dział finansowy** (Finanse → Zmiany
w zamówieniach → Braki). Nie powstaje, gdy koniec był świadomy: wypowiedziana
umowa („Zakończ współpracę"), zamiana kontraktora, decyzja o MD po zakończeniu
współpracy albo „Zostaw jako historię". Jeśli zakończysz współpracę **już po**
wykryciu braku, osoba przechodzi do Zejść, znika z Braków, a karta zamyka się
przy najbliższym przeglądzie alertów. Zamówienie dodane do końca dnia
następującego po końcu obecnego liczy się jako terminowe i w Brakach nie
zostaje. Dodanie go później zamyka kartę od razu, ale **wpis w Brakach zostaje**
jako „Uzupełnione z opóźnieniem" z liczbą dni po terminie — dział finansowy
widzi, że temat nie był dopilnowany na czas. Najbezpieczniej dodaj następne
zamówienie (wystarczy szkic) **najpóźniej w dniu końca obecnego**.

> **Uwaga na dziurę:** alert o drafcie przypomina o zamówieniach w statusie
> **Draft**, a nie o osobach, które zamówienia **w ogóle nie mają**. Konsultant
> z umową, ale bez żadnego zamówienia — tak jak u Polkomtela, gdzie zamówienie
> zakładasz ręcznie — nie wywoła żadnego powiadomienia. Takich osób musisz
> pilnować sam.

**Warunek, bez którego nie dostaniesz nic z tego panelu:** musisz mieć aktywne
konto, rolę i dostęp do sekcji Delivery oraz być **przypisany do klienta jako
Delivery Lead** (profil klienta → zakładka „Delivery Lead"). Bez przypisania sprawy
dla tego klienta **nie powstają — dla nikogo** (wyjątek: zamówienie z maila do
weryfikacji trafia wtedy do administratorów). To pierwsza rzecz do sprawdzenia,
gdy „system nic nie przysyła". Jednorazowe powiadomienia — o pierwszym drafcie
z maila i o wyczerpaniu budżetu — przyjdą przy najbliższym dobowym przebiegu
po przypisaniu, jeśli sprawa nadal trwa.

Panel pokazuje wyłącznie **Twoje** sprawy — nawet administratorowi — i jest
widoczny w widoku pulpitu „Delivery Lead".

### Maile

O kończącym się zamówieniu, umowie ramowej i kontrakcie mail przychodzi
**trzy razy**: przy **pierwszej karcie sprawy** — czyli zwykle **miesiąc przed
datą końca** — potem **14 dni przed** i **7 dni przed**. Powtórki co 7 dni
między tymi progami idą tylko na kartę, bez maila. Poza tym mail wychodzi przy
wysokim priorytecie MD i budżetu kosztowego.

Pierwszy mail jest liczony od **wejścia sprawy do panelu**, nie od równości
z dniem T-30: zamówienie wpisane albo przedłużone na mniej niż miesiąc
(np. 20 dni przed końcem) dostaje ten mail od razu, zamiast czekać do progu
14-dniowego. Przedłużenie zamówienia to nowa sprawa, więc uprzedzenie
przychodzi znowu.

Każdy próg wysyła mail raz. Odhaczona sprawa nie dostaje już maili.

### Dzwonek w prawym górnym rogu

Dzwonek działa jak dotąd i nadal pokazuje także powiadomienia o końcu zamówień,
umów ramowych i kontraktów (30, 14 i 7 dni przed datą; kontrakty dodatkowo 90
i 60 dni), o nowym drafcie kontraktu i zamówienia po zatrudnieniu oraz o braku
kolejnego zamówienia (raz na brak). Panel
„Moi klienci" jest miejscem, w którym te sprawy **załatwiasz i odhaczasz**;
dzwonek — tylko informacją.

Progi dzwonka liczą się z **przedziału** dni do końca, więc dzień bez biegu
skanera już ich nie gubi, a zamówienie wpisane później niż miesiąc przed końcem
dostaje najbliższy pasujący próg zamiast nieprawdziwego „za 30 dni". Tytuł
powiadomienia podaje **faktyczną** liczbę dni („kończy się za 22 dni"), a nie
numer progu.

Skanery chodzą **raz na dobę, licząc od ostatniego restartu aplikacji** — nie ma
stałej godziny wysyłki.

Poza aplikację idą: maile z progów opisane wyżej oraz zbiorcze podsumowanie
wygasających umów z konsultantami na Slacka, gdy administrator skonfigurował
integrację.

### Zakończenie współpracy na zamówieniu MD

To jedyny moment, w którym system **zatrzymuje się i czeka na Twoją decyzję**.
Przy zamówieniu okresowym i kosztowym rozliczy zakończenie sam; przy MD zostaje
niewykorzystana pula i ktoś musi powiedzieć, co z nią zrobić. Do czasu decyzji
system blokuje inne zmiany na tym zamówieniu.

Okienko **„Zakończenie współpracy — decyzja o MD"** daje trzy opcje:
**Usuń z zamówienia**, **Przelicz na innego konsultanta** albo **Przywróć jako
aktywne**. Przy przeliczeniu lista „Konsultant przejmujący" ma dwie grupy:
**Na tym zamówieniu** (aktywne osoby z zamówienia) i **Nowe osoby u klienta**
(osoby ze szkiców). Wybór nowej osoby działa jak „Wejdź za konsultanta" —
podajesz datę wejścia i stawki, a osoba dochodzi do obsady z przejętymi MD.
Sposób przeliczenia opisuje „Przejęcie pozostałych MD" niżej.

Przy **wspólnej puli MD** decyzja tylko zdejmuje osobę z obsady — pula nie jest
pomniejszana ani nikomu przypisywana, bo i tak była wspólna.

---

## Kto co może

Uprawnienia rozkładają się na **trzy niezależne poziomy** i to tłumaczy większość
pytań „dlaczego nie widzę przycisku".

| Poziom | Kto |
|---|---|
| **Bezpieczny odczyt zamówień** | administrator i Finanse — wszyscy klienci; każdy Delivery Lead — wszyscy klienci, ale poza przypisanym portfelem bez kwot i plików PO; Talent Community Manager — wszyscy klienci, ale bez kwot, plików PO i eksportu |
| **Cykl życia** (zakończ, przywróć, usuń — także usunięcie konsultanta) | administrator i każdy Delivery Lead; Finanse dodatkowo przy zamówieniach zbiorczych |
| **Stawki, budżety, pliki PO i obsada** (dodanie/edycja konsultanta, finansowa edycja zamówienia) | administrator i Delivery Lead przypisany do klienta; **Finanse — same kwoty** (stawki i wartości), bez obsady i plików PO |

**Finanse przechodzą bramkę odczytu u wszystkich klientów bez przypisania**
i widzą kwoty. Od 22.09.2026 zmieniają też **same kwoty** — stawki kontraktu,
zamówienia i linii MD. Próba zmiany czegokolwiek innego (obsada, daty, numer,
plik PO) kończy się odmową „Finanse zmieniają tutaj wyłącznie kwoty". Delivery Lead nie potrzebuje
przypisania, aby widzieć i obsługiwać klienta operacyjnie; przypisanie nadal
wyznacza jego dostęp do stawek, budżetów, plików PO i operacji, które je zapisują.

**Talent Community Manager ma globalny, bezpieczny odczyt Delivery.** Widzi
dane operacyjne, ale nie widzi kwot, marż, przychodów, plików źródłowych PO ani
eksportów mogących zawierać stawki; nie może też wykonywać żadnych zmian.

**Head of Recruitment, TAC, Rekruter i Sourcer nie mają dostępu do sekcji
Delivery**, więc nie widzą zamówień ani tych akcji.

**Odebranie dostępu do sekcji Delivery (roli albo konkretnej osobie) działa
w całości** — także wąski wyjątek, w którym Talent Community Manager zmienia
status umowy, przestaje wtedy działać.

**Przedłużenie zamówienia zbiorczego** może rozpocząć administrator, przypisany
Delivery Lead albo Finanse. Jeżeli przedłużenie od razu zawiera konsultantów ze
stawkami, wymaga administratora albo przypisanego Delivery Leada. Talent
Community Manager nie otworzy formularza i nie zapisze przedłużenia.

Talent Community Manager widzi na zamówieniach zbiorczych **myślnik „—"** — nie
zero i nie komunikat o błędzie — a na kartach pojedynczych konsultantów wiersze
z pieniędzmi w ogóle się nie pokazują.

**Importu zużycia MD nie robi Delivery Lead.** Moduł Finanse jest dostępny tylko
dla ról administrator i Finanse — ale wynik tego importu natychmiast zmienia to,
co widzisz w zakładce „Zamówienia", i uruchamia powiadomienia o budżecie.

---

## Skąd biorą się liczby zużycia

Zużycie — dni albo złotówek — wpisuje **miesięczny import raportu z Finansów**.
Przy aktywnej lub wyczerpanej wspólnej puli MD osoba uprawniona do edycji
finansowych pól zamówienia może też w **Uzupełnij zamówienie** podać miesiąc
i łączne zużycie MD za ten miesiąc. To suma wszystkich konsultantów:
**kolejny zapis zastępuje sumę danego miesiąca, także pochodzącą z importu**,
a nie dodaje kolejnej pozycji. Suma miesięcy pomniejsza jedną wspólną pulę.
Korekta pozostałości to osobna operacja opisana na końcu tej sekcji.

* Import robi rola Finanse albo administrator, w **Finanse → Import zużycia MD**.
* Jeden plik obejmuje wszystkich klientów naraz. Miesiąc raportu **wybiera
  operator** — system nigdy nie zgaduje go z nazwy pliku.
* Wiersze dopasowywane są do zamówień **po imieniu i nazwisku**. Jedno trafienie
  → zaktualizowane; zero → „Brak pasującego zamówienia"; **więcej niż jedno →
  „Wymaga przypisania"** i system czeka, aż człowiek wskaże właściwe zamówienie.
  Nie zgaduje, bo trafienie w złe zamówienie odejmuje dni nie temu klientowi
  i wychodzi dopiero na fakturze.
* **Numer zamówienia w „Uwagach" jest wiążący u każdego klienta.** Wiersz
  z numerem trafia **wyłącznie** na zamówienie o tym numerze — także gdy ta
  sama osoba ma w tym miesiącu dwa zamówienia (stare kończy się 14.08, nowe
  zaczyna 15.08: dwa wiersze, każdy na swoje zamówienie, bez nadpisywania).
  Nadwyżka ponad budżet zostaje wtedy na wskazanym zamówieniu (widać ją na
  czerwono), a nie przechodzi na przedłużenie. Gdy tej osoby nie ma na
  wskazanym zamówieniu w tym miesiącu (numer z literówką, zamówienia nie ma
  w NEXUSIE, okres go nie obejmuje), wiersz zostaje **„Brak pasującego
  zamówienia" z opisem przyczyny** i nie zmienia żadnego zamówienia. Za
  numer uznawany jest ciąg cyfr znany jako numer zamówienia **klienta tej
  osoby**, a u klientów z numerami z samych cyfr (BIK, Polkomtel) także każdy
  ciąg dłuższy niż 6 cyfr. Dopisek „w tym delegacja 318", rok, NIP czy numer
  zamówienia innego klienta nie blokuje dopasowania po nazwisku. Ponowny
  import miesiąca z numerem cofa nadwyżkę przeniesioną wcześniej na
  przedłużenie — te same MD nie liczą się dwa razy.
* **Zakończenie współpracy konsultanta nie wyklucza go z importu.** Liczy się
  okres, w którym obsadzał zamówienie — raport za sierpień wgrany we wrześniu
  trafi w osobę, która zeszła 31 sierpnia, i doliczy jej MD. Gdy ta sama osoba
  w jednym miesiącu zeszła z jednego zamówienia i weszła na drugie, wiersz
  idzie na to, na którym **nadal pracuje**. Pominięta jest wyłącznie osoba
  **usunięta z zamówienia**.
* **Zamówienie zakończone z datą w przyszłości nadal przyjmuje import** za
  miesiące, które nie leżą po dacie zakończenia — konsultant pracuje do tej
  daty, choć zamówienie od razu figuruje w „Zakończonych”. Dotyczy MD przy
  osobie, wspólnej puli MD i zamówień kosztowych. Za miesiąc po dacie
  zakończenia wiersz zostanie „Brak pasującego zamówienia”. Zamówienie
  **wyczerpane** importu nie przyjmuje.
* **Przy wspólnej puli MD u dowolnego klienta samo nazwisko nie
  wystarcza** — wiersz musi mieć dodatkowo **numer tego zamówienia w kolumnie
  „Uwagi"**. Bez numeru (albo gdy numer pasuje do kilku zamówień) **z puli nie
  schodzi ani jeden dzień**, a wiersz zostaje niedopasowany. To najczęstsza
  przyczyna „import przeszedł, a budżet stoi w miejscu".
* **U Polkomtela każdy ciąg cyfr z „Uwag" jest rozstrzygający** (także krótki).
  Jeżeli pasuje do zamówienia Polkomtela — decyduje numer, nie nazwisko; jeżeli
  nie pasuje, system **nie wraca do dopasowania po nazwisku**, tylko zostawia
  wiersz niedopasowany.
* **Wiersz z liczbą MD ujemną, większą niż 1000 albo nieliczbową („NaN”)
  jest odrzucany** i trafia do pominiętych wierszy z numerem i powodem — nie
  zmienia żadnego budżetu. To samo dotyczy nieczytelnej kwoty faktury
  (nieskończonej albo powyżej miliarda złotych). Popraw plik i wgraj miesiąc
  ponownie.
* **Powtórny import tego samego miesiąca nadpisuje** poprzednie zużycie — MD nie
  odejmą się drugi raz.
* **Ręczne przypisanie też musi zgadzać się z numerem z „Uwag"** — wiersz
  z numerem 4500029903 nie da się przypisać do innego zamówienia. Dwa wiersze
  tej samej paczki przypisane do dwóch kolejnych zamówień tej osoby nie
  nadpisują się nawzajem.
* **Ale błędne przypisanie wiersza jest nieodwracalne.** Wiersz raz rozstrzygnięty
  nie da się przypisać ponownie, a ponowny import miesiąca tego nie naprawia — MD
  wpisane omyłkowo na złą linię tam zostają. Jeżeli operator z Finansów pyta,
  które zamówienie wskazać, sprawdź to, zanim odpowiesz.
* **Ręczne rozstrzygnięcie niejednoznaczności działa tam, gdzie budżet MD jest
  przypisany osobie.** Przy zamówieniu kosztowym i przy wspólnej puli MD nie ma
  w interfejsie sposobu, żeby wskazać właściwe zamówienie — wiersz zostaje
  nierozliczony i trzeba poprawić plik po stronie Finansów.
* Przy zamówieniach **kosztowych** wiersz musi mieć numer zamówienia w kolumnie
  „Uwagi" **oraz kwotę faktury**. Bez numeru wiersz zostanie oznaczony na czerwono;
  **bez kwoty jest pomijany zupełnie po cichu**, bez śladu w podsumowaniu importu.

**Pozostałość MD przy konkretnej osobie może zejść poniżej zera** (przekroczenie
widać na czerwono) — chyba że ta osoba ma linię w przedłużeniu tego zamówienia:
wtedy nadwyżkowe dni system **przenosi na przedłużenie**, więc poprzednik
zatrzymuje się na zerze, a nowe zamówienie startuje już częściowo zużyte.
**Przy wspólnej puli — kosztowej i MD — licznik „pozostało" nie schodzi poniżej
zera.** Przekroczenie poznasz po tym, że „wykorzystano" jest większe niż budżet.
Przy zamówieniu **kosztowym** nadwyżka jest dodatkowo pokazana przy konkretnej
osobie jako nierozliczona; przy **wspólnej puli MD** system nikogo nie wskazuje. Przekroczenie
budżetu nie jest nigdzie blokowane: to fakt handlowy, o którym system informuje,
a nie błąd, przed którym broni.

**Zwiększenie budżetu przelicza wszystko od zera** i potrafi zdjąć status
„Wyczerpane" — zamówienie samo wraca na „Aktywne".

**Ręczna korekta pozostałych MD przy konkretnej osobie** jest dostępna tam, gdzie
budżet jest przypisany osobie. Przy zamówieniu kosztowym i przy wspólnej puli MD
tego pola nie ma — tam korygujesz kwotę albo pulę na poziomie całego zamówienia.

---

## Klienci — czym różni się każdy

Poniżej tylko to, co u danego klienta jest **inne niż w opisie powyżej**.
Jeżeli Twojego klienta tu nie ma, obowiązuje wyłącznie część ogólna — i to jest
normalne, nie brak w instrukcji.

Reguły odczytu dokumentu włącza administrator osobno dla każdego klienta.
Jeżeli u Ciebie odczyt zachowuje się inaczej, niż opisano poniżej, **zgłoś to
administratorowi** zamiast obchodzić regułę ręcznie — z wyjątkiem Orlenu, PFRON,
BIK, Polkomtela i Cyfrowego Polsatu, które działają zawsze.

Skrót **„Powiadomienia: standardowe"** znaczy: alerty o końcu zamówienia
**30, 14 i 7 dni** przed datą (dzwonek) oraz sprawy **„bez zamówienia"** i
**„brak stawki przychodowej"** co 7 dni (pulpit Delivery Leada).

### BNP Paribas

* **Domyślnie podpowiadany typ to MD**, ale okresowe i kosztowe też są
  dostępne.
* Jeden numer, kilku konsultantów, **budżet dni przy każdej osobie**. Zużycie
  schodzi z miesięcznego importu z Finansów, dopasowywanego po imieniu
  i nazwisku.
* **BNP ma własną regułę odczytu dokumentu.** Dokument jest jednoosobowy, więc
  wszystko, co w nim stoi, dotyczy osoby, z której karty uruchamiasz odczyt
  (w oknie „Nowe zamówienie" powstaje jedna karta **„Wymaga ręcznego
  wskazania"** z odczytaną stawką i MD — osobę wskazujesz sam):
  * **okres** czytany jest z zapisu **MM-RRRR do MM-RRRR** i rozwijany na
    pierwszy i ostatni dzień miesiąca,
  * **stawka** wchodzi z pola **„Cena netto"** i jest traktowana jako kwota
    **za 1 MD** — jednostka zostaje ustawiona na MD niezależnie od tego, co
    odczytał model,
  * **liczba MD** wchodzi z pola **„Szt."**,
  * **konsultanta dokument identyfikuje NUMEREM ID**, nie imieniem i nazwiskiem
    — system go odczytuje, ale nie ma jak sam sprawdzić, czy to ta osoba.
    **Potwierdzenie należy do Ciebie.**
* Gdy któregoś z tych pól w dokumencie nie ma, system o tym powie i zostawi
  pole do ręcznego wpisania. Zgłosi też **nietypową stawkę za 1 MD** poza
  spodziewanym zakresem — to sygnał, że kwotę odczytano z innej kolumny.
* **Powiadomienia:** BNP jest klientem z **rozszerzonymi alertami** — poza
  standardowymi dostajesz dwa niezależne sygnały o każdym zamówieniu (patrz
  „Powiadomienia — co przyjdzie, kiedy i gdzie"): **koniec okresu** 30 dni
  przed datą końca, z powtórką co tydzień, oraz **zużycie 80% podstawy MD**,
  niezależnie od tego, ile czasu zostało. Do tego nadal alert **„mało MD"**,
  gdy konsultantowi zostanie 21 MD lub mniej.

### BIK

* **Domyślnie podpowiadany typ to MD**; okresowe i kosztowe też są dostępne.
* Przykład z tabeli zamówienia BIK: pozycje **10** i **20** stają się dwiema
  kartami konsultantów, a opis źródła mówi „z PDF, poz. 10" / „z PDF, poz. 20".
* Budżet dni przy każdej osobie; import dopasowuje wiersze po imieniu
  i nazwisku.
* **BIK ma własną regułę odczytu dokumentu** — działa zawsze, bez włączania
  przez administratora, i tak samo w każdej ścieżce: w odczycie maila,
  w **Nowe zamówienie**, w **Uzupełnij zamówienie**, w **Dodaj przedłużenie**
  i przy dodawaniu konsultanta. Dokument ma dwie części:
  * **wspólne dla zamówienia** — z pola **„Numer/data zamówienia"**: część
    **przed ukośnikiem** to numer zamówienia (np. „4500012345"), część **po
    ukośniku** (RRRRMMDD, np. „20260903") to **data rozpoczęcia**
    (03.09.2026). **Data zakończenia jest zawsze „bezterminowo"** — odczyt
    czyści wpisaną wcześniej datę „do" (przy rozbieżności zapyta). Pole
    **„Termin dostawy" jest pomijane**;
  * **per konsultant — każda pozycja tabeli („Poz." 10, 20, …) to jedna
    osoba.** Liczba z kolumny **„Ilość zamów."** (jednostka SZT) jest
    **limitem MD tej osoby**, a **„Cena jednostk."** jej **stawką przychodową
    za 1 MD**. Imię i nazwisko system znajduje w treści pozycji (zwykle
    w linii „Profil UR - Imię Nazwisko") — **z myślnikiem albo bez niego**,
    także gdy PDF skleił wyrazy („ProfilUR-JanKowalski").
* **Nie są brane pod uwagę:** „Wart.netto" pozycji, „Łącz. wart. netto bez
  VAT", adresy, osoba do kontaktów, NIP, warunki płatności. Iloczyn „ilość ×
  cena" jest porównywany z „Wart.netto" wyłącznie jako kontrola — gdy się nie
  zgadza, dostaniesz „Sprawdź dane!" z numerem pozycji.
* **Gdy imienia i nazwiska nie da się jednoznacznie odczytać** (brak osoby
  w pozycji, dwie możliwe osoby, inicjał w opisie niezgodny z osobą z profilu),
  system **zostawia nazwisko puste i podaje powód z numerem pozycji**. Mail
  z takim dokumentem trafia do weryfikacji, a nie zakłada błędnego wpisu.
* W **Nowe zamówienie** każda pozycja staje się **kartą konsultanta** z limitem
  MD i stawką tej osoby (opis kart — w części ogólnej). W **Uzupełnij
  zamówienie** i **Dodaj przedłużenie** pod plikiem zobaczysz listę
  konsultantów odczytanych z PDF-a (limit MD i stawka każdej osoby). Przy przedłużeniu system sam wpisuje limit MD
  i stawkę przychodową **przenoszonym osobom o tym samym imieniu i nazwisku**.
* **Zamówienie kończy wyczerpanie limitów, nie data.** Zamówienie pozostaje
  **„Aktywne"**, dopóki choć jedna przypisana osoba ma niewykorzystane dni;
  gdy **wszystkie** osoby wyczerpią swój limit (według importu z Finansów),
  przechodzi na **„Zakończone"** samo — ostatnia osoba kończy całe
  zamówienie. Osoba bez wpisanego limitu MD trzyma zamówienie otwarte.
  **„Przywróć" nie zadziała** na tak zakończonym zamówieniu — zwiększ budżet
  MD konsultanta albo skoryguj zużycie, a zamówienie wróci do „Aktywnych"
  samo; nowy limit to przedłużenie.
* **Powiadomienia:** jak u BNP — standardowe plus „mało MD" przy 21 dniach.

### Polkomtel

* **Wszystkie trzy typy są dostępne**; domyślnie podpowiadany jest typ
  najczęstszy w historii klienta.
* **Polkomtel ma własną regułę odczytu „Zlecenia wykonawczego"** (działa zawsze,
  także dla poczty zamówień):
  * **numer** — skrót i numer z linii „ZLECENIE WYKONAWCZE nr …", bez części po
    ukośniku: „nr SAP 4500123456 / 2026 rok" → **SAP 4500123456**;
  * **data rozpoczęcia** — z frazy **„zawarte w dniu …"**; **data zakończenia
    zawsze bezterminowo** — zamówienie kosztowe kończy wyczerpanie kwoty,
    a zamówienie MD wyczerpanie MD (per osoba albo wspólnej puli);
  * **tabela konsultantów** — każda osoba z kolumny „Konsultant" dostaje stawkę
    ze **swojego wiersza** kolumny „Cena netto 1MD po upuście [PLN]", zawsze
    jako **netto za MD**; kolumna „Cena total [PLN]" i „na kwotę … PLN" to
    **kwota całego zamówienia**, nie per osoba;
  * **brak liczby MD w zleceniu kosztowym jest poprawny** i nie jest zgłaszany;
  * reguła działa **tylko na „Zleceniu wykonawczym"** — inny dokument Polkomtela
    (np. aneks) czyta odczyt ogólny i dostaje uwagę „sprawdź wszystkie pola";
  * gdy wiersza tabeli nie da się jednoznacznie odczytać (np. nazwisko złamane
    na dwie linie), karta tej osoby **nie dostaje stawki** i czeka na Ciebie —
    system nigdy nie przesuwa stawki na sąsiednią osobę.
* **System NIE zakłada tu automatycznie zamówienia po zatrudnieniu konsultanta.**
  U pozostałych klientów po przejściu kandydata na „zatrudniony" pojawia się
  szkic zamówienia do uzupełnienia — u Polkomtela musisz założyć zamówienie sam.
  To najważniejsza różnica praktyczna dla tego klienta.
* Przy zamówieniu kosztowym kwota jest **wspólna dla całego zamówienia**; przy
  konsultancie nie ma pola budżetu, są tylko obie stawki.
* Nowe zamówienie MD domyślnie ma budżet **per osoba**; możesz wybrać wspólną
  pulę, jak u pozostałych klientów.
* **W imporcie z Finansów numer zamówienia z kolumny „Uwagi" jest u Polkomtela
  rozstrzygający.** Gdy wiersz go niesie, decyduje numer, a nie nazwisko — i gdy
  numer nie pasuje do żadnego zamówienia Polkomtela, system **nie próbuje już
  dopasować po nazwisku**, tylko zostawia wiersz niedopasowany.
* **Powiadomienia:** standardowe, plus alert **„mało MD"** przy 21 dniach na
  zamówieniach MD. Przy zamówieniu **kosztowym** karta w panelu „Moi klienci"
  przychodzi, gdy w budżecie zostanie 10 000 zł lub mniej, a na końcu
  jednorazowy alert o wyczerpaniu.

### Lotte Wedel

* **Wszystkie trzy typy są dostępne**; domyślnie podpowiadany jest typ
  najczęstszy w historii klienta.
* Historyczne zamówienia MD zachowują **wspólną pulę dni**. Przy nowym MD
  domyślny jest budżet per osoba; wspólną pulę wybierasz checkboxem.
* Przy wspólnej puli import wymaga **jednocześnie nazwiska i numeru zamówienia**
  w kolumnie „Uwagi”. Konsultant nie dostaje wtedy osobnego budżetu.
* Wybór trybu budżetu nowych MD jest taki sam jak u wszystkich klientów.
  Lotte Wedel nie ma własnej reguły PDF.
* **Powiadomienia:** standardowe, a dla wspólnej puli MD dwa własne: **„mało MD"**,
  gdy w puli zostanie 21 dni lub mniej, oraz jednorazowy alert **o wyczerpaniu**,
  gdy zejdzie do zera i zamówienie przestanie przyjmować konsultantów. Przy
  zamówieniu **kosztowym** karta przychodzi przy 10 000 zł w budżecie, a potem
  alert o wyczerpaniu.

### Cyfrowy Polsat

* **Wszystkie trzy typy do wyboru** — Okresowe, Kosztowe i MD.
* Historyczne MD zachowują **wspólną pulę dni**, tak samo jak u Lotte Wedel.
  W nowych MD domyślny jest budżet per osoba, z możliwością wybrania wspólnej puli.
* **Reguła odczytu PDF-a obejmuje tylko numer**: z linii „ZLECENIE WYKONAWCZE
  nr CP 1234 / 2026 rok" system bierze **CP 1234** (ta sama reguła co u
  Polkomtela). Daty i stawki czyta odczyt ogólny — Cyfrowy Polsat ma też
  zamówienia okresowe.
* Zamówienie okresowe zakładasz tu tak jak u każdego innego klienta —
  formularzem „Nowy kontraktor / zamówienie".
* **Powiadomienia:** standardowe, a poza tym jak u Lotte Wedel: wspólna pula MD
  ostrzega przy 15 pozostałych dniach i alarmuje o wyczerpaniu, a zamówienie
  kosztowe — tylko o wyczerpaniu.

### Nordea

Dwa mechanizmy, które łatwo pomylić.

**1. Reguła numeru zamówienia przy odczycie PDF-a.** Po odczycie system nadpisuje
numer twardą regułą: bierze **wyłącznie** wartość spod etykiety **„Call Off
Agreement"** (rozpoznaje też pisownię „Call-Off" i „Calloff" oraz zakończenia
„number", „no.", „nr" i „#"). Wartość może stać **w tym samym wierszu co
etykieta albo w następnym** i **musi zawierać cyfrę** — słowo stojące za
etykietą (drugi nagłówek kolumny, „nr", nazwa pola) ani sama data nie zostaną
wzięte za numer. **Numeru umowy ramowej („Frame Agreement number") nie weźmie
nigdy**, nawet gdy stoi w dokumencie wyżej — to była przyczyna zgłoszenia
„system wpisuje zły numer". Gdy dokument ma **dwa nagłówki obok siebie, a
wartości pod nimi**, system woli zostawić pole puste, niż wpisać numer
z sąsiedniej kolumny. Jeżeli tej etykiety w dokumencie nie ma, **system nie poda
żadnego numeru** — nigdy nie podstawi numeru oferty ani projektu. Dostaniesz
o tym komunikat w banerze — ale **pole numeru nie zostanie wyczyszczone**: jeżeli
coś już w nim stało (numer z poprzedniego zamówienia albo wartość zastępcza ze
szkicu), zostanie tam nietknięte i zapisze się razem z zamówieniem. Po odczycie
u Nordei **zawsze przeczytaj pole numeru** i wpisz właściwy ręcznie.
**Stawka z PDF-a jest zawsze netto za godzinę (zł/h)**, niezależnie od
nagłówka Rate i oznaczenia brutto/netto. System nie dzieli jej przez 1,23
ani nie przelicza z dni lub miesięcy. **Quantity (max Xh/month) jest
ignorowane**: nie uzupełnia godzin ani MD i nie służy do kontroli
„ilość × stawka = subtotal”. Przy odczycie załącznika brane jest właściwe
zamówienie, bez sekcji/strony **summary** i bez powielania jej osób.
Osobne certyfikaty DocuSign („Certificate of Completion”, „Record Tracking”,
„Signer Events”) są pomijane niezależnie od nazwy pliku i nie trafiają na listy
zamówień. Załącznik bez cech zamówienia także jest pomijany. Właściwy dokument
z tego samego maila oraz PDF łączący zamówienie z certyfikatem są odczytywane.
Te trzy reguły nie powodują „odczytu niepewnego”; inne błędy, np. niejasna
osoba lub okres, nadal wymagają weryfikacji. „Przelicz plan” ponownie
odczytuje osoby z właściwej tabeli zapisanego PDF-a Nordea.

**2. Import zamówień z CSV — nie dla Ciebie.** W zakładce „Zamówienia" jest
zwijany panel **„Import zamówień Nordea z CSV"**, ale **widzi go wyłącznie
administrator**. Aktualizuje naraz wielu konsultantów z pliku od Finansów
(średnik jako separator; numer zamówienia, kontraktor, line manager, start,
koniec, stawka przychodowa, stawka z umowy ramowej). Przebieg jest dwuetapowy:
**Sprawdź import** (podgląd, nic się nie zapisuje), potem **Zastosuj import**
z potwierdzeniem. Import nadpisuje numer, obie daty i stawkę przychodową.
Przy zmianie okresu przelicza status według zasad opisanych wyżej; nie wznawia
zamówień wstrzymanych ani anulowanych. Samo ponowienie tego samego okresu
nie wznawia zamówienia zakończonego. Import
a dodatkowo **zapisuje stawkę z umowy ramowej** — w umowie konsultanta jako
stawkę obowiązującą od podanej daty; jeśli wpis z tą samą datą już istnieje,
nadpisuje go.
**Stawki kosztowej nie rusza nigdy.** Powtórzenie tego samego pliku niczego nie
duplikuje.

* Nordea, jak każdy klient, ma do wyboru wszystkie trzy typy. W praktyce
  jej zamówienia prowadzi się jako **okresowe** (jedna osoba, jedno zamówienie)
  i takie właśnie tworzy import CSV.
* **Powiadomienia:** koniec zamówienia 30/14/7 dni przed datą, plus sprawy
  „bez zamówienia" i „brak stawki przychodowej" co 7 dni.

### Bank Pocztowy

Reguła odczytu zmienia liczby, więc warto znać ją w całości:

* **Numer zamówienia** bierze wyłącznie z pola **„Numer pisma"**, a gdy go nie
  ma — z **„Zamówienie nr"**.
* **Stawka z dokumentu jest zawsze traktowana jako kwota netto za 1 MD i dzielona
  przez 8**, z zaokrągleniem **w górę do dwóch miejsc po przecinku**. Jednostka
  stawki przeskakuje na **godzinową**, a system przelicza przy okazji stawkę
  kosztową, którą już wpisałeś. Pod polem zobaczysz „Z dokumentu: … /MD →
  przeliczono na stawkę godzinową (÷ 8)".
* **Jeżeli przeliczona stawka wypadnie poniżej 80 zł/h albo powyżej 300 zł/h**,
  w banerze pojawi się ostrzeżenie o nietypowej stawce. To sygnał, że w dokumencie
  odczytano prawdopodobnie inną liczbę niż stawkę — sprawdź, zanim zapiszesz.
* **Liczba MD z dokumentu jest zawsze pomijana** — nie trafi do formularza.
* **Powiadomienia:** standardowe — koniec zamówienia 30/14/7 dni, sprawy „bez
  zamówienia" i „brak stawki przychodowej".

### Credit Agricole

* **Stawka wchodzi wyłącznie** spod napisu **„Wynagrodzenie za 1MD"** — system
  bierze pierwszą liczbę, która za nim stoi. Sama kwota **nie jest przeliczana**,
  ale **jednostka stawki zostaje ustawiona na MD (dzień)**. Jeżeli w formularzu
  miałeś jednostkę godzinową albo miesięczną, system przy okazji przeliczy Twoją
  **stawkę kosztową** — sprawdź ją przed zapisem.
* **Liczba dni** jest brana z pola **„Szacowana ilość MD"**, gdy takie w dokumencie
  jest. Gdy go nie ma, **zostaje liczba zaproponowana przez odczyt AI** — to
  jedyne pole, którego ta reguła nie czyści, więc sprawdź je szczególnie.
* **System odmawia odczytu stawki**, gdy obie etykiety stoją w jednym wierszu
  (nagłówek tabeli) albo gdy pod obiema stoi ta sama liczba. Dostaniesz wtedy
  komunikat „Nie znaleziono pola »Wynagrodzenie za 1MD (8h) (PLN netto)« — wpisz
  stawkę ręcznie". To celowe: przy nierównych kolumnach „pierwsza liczba za
  etykietą" trafiałaby w liczbę porządkową, a zła stawka zapisana jako pewna
  wychodzi dopiero na fakturze.
* **Uwaga:** przy odmowie system nie czyści pola w formularzu — jeśli coś tam już
  było (np. stawka z poprzedniego zamówienia), zostanie. Wpisz właściwą ręcznie.
* **Powiadomienia:** standardowe.

### Erste Bank Polska

* **Rodzaj stawki wynika z dokumentu.** Przy oznaczeniu brutto system dzieli
  kwotę przez **1,23** i pokazuje oryginał obok; netto pozostawia bez zmian.
  Brak jednoznacznego oznaczenia wymaga weryfikacji.
* **Jednostka stawki jest ustawiana na MD (dzień)** — kwota pochodzi ze wzoru
  „dni roboczych × stawka". Dotyczy to sytuacji, w której stawkę udało się odczytać.
* Ta reguła działa **na końcu**, czyli na wyniku pozostałych reguł.
* **Wartość całkowita zamówienia nie jest przeliczana** — jeśli dokument ją
  podaje, sprawdź ją samodzielnie.
* **Powiadomienia:** standardowe.

### Orlen

* Reguła dotyczy **tylko stawki**: jeżeli ta sama osoba ma w dokumencie kilka
  pozycji (np. on-site i off-site) i wszystkie mają **identyczną** stawkę
  i jednostkę — system ją wpisze. Jeżeli stawki się różnią albo nazwisko nie
  zgadza się dokładnie, **system nie poda żadnej stawki** i poprosi o ręczne
  wpisanie.
* **Uwaga — to nie znaczy, że pole będzie puste.** System nie czyści formularza:
  zostaje w nim to, co było wcześniej (np. stawka z poprzedniego zamówienia albo
  z umowy). Przy komunikacie o ręcznym wpisaniu **zawsze sprawdź wartość
  w polu**, zamiast zakładać, że odczyt ją podmienił.
* **Cała reguła Orlena włącza się tylko wtedy, gdy odczyt dotyczy konkretnej
  osoby** — czyli na karcie pojedynczego konsultanta, przy przedłużeniu jego
  zamówienia i przy dodawaniu go do zamówienia zbiorczego. **Liczba MD jest wtedy
  pomijana.** W formularzu zamówienia zbiorczego, gdzie osoby się nie wskazuje,
  reguła w ogóle nie działa: do pola budżetu wpadnie liczba MD odczytana przez AI,
  a system nie sprawdzi, czy wszystkie pozycje tej osoby mają tę samą kwotę.
  Sprawdź oba pola.
* Ta reguła **działa zawsze**, bez żadnej konfiguracji.
* **Powiadomienia:** standardowe.

### PFRON

* **Osoba i jej stawka są niezależnie potwierdzane z pól „Imię i nazwisko”
  oraz „Stawka za jedną Roboczogodzinę” w tym samym bloku specjalisty.
  Dopisek stanowiska po oddzielonym spacjami myślniku nie jest częścią nazwiska.**
  Brak kompletnego potwierdzenia wymaga weryfikacji dokumentu, nawet gdy
  konsultant istnieje w bazie. Informacyjna liczba RBH nie tworzy budżetu MD
  ani ostrzeżenia o jednostce pomijanej liczby MD.

* **Klient**: zamówienia trafiają do aktywnego rekordu „Państwowy Fundusz
  Rehabilitacji Osób Niepełnosprawnych”, a osoby są szukane w jego liście
  konsultantów. Nieaktywny duplikat „PFRON” nie jest wybierany. Jednoznaczny
  marker lub domena PFRON nie wymagają dodatkowego numeru rejestrowego.
* **Numer zamówienia** pochodzi z tytułu „Zlecenie nr …” w dokumencie lub
  nazwie PDF i zachowuje pełny zapis, np. **Zlecenie nr 22**. Imię i nazwisko,
  daty oraz numer umowy i zapotrzebowania nie wchodzą do numeru. Historyczne
  „22” i „Zlecenie nr 22” są rozpoznawane jako to samo zamówienie.
* **Liczba MD z dokumentu jest zawsze pomijana** — bezwarunkowo, szerzej niż
  u Orlena.
* **Data początku** pochodzi wyłącznie z pola **„Data rozpoczęcia wykonywania
  Prac przez Specjalistę”**. Pole „Okres realizacji Prac” (np. do 160 RBH
  miesięcznie) jest pomijane.
* **Data zakończenia** pochodzi wyłącznie z pola **„Termin wykonania Prac”**.
  Opcja przedłużenia i pozostałe daty w treści nie zmieniają daty końca — ani
  dokumentu, ani wiersza osoby. Brak lub niejednoznaczność tego pola wymaga
  sprawdzenia przez operatora. W formularzu sprawdź też wcześniejszą wartość.
* Oczekujący wpis z błędnym klientem, numerem lub datą popraw przyciskiem
  **„Przelicz plan”**. Kompletny i pewny wynik jest od razu zapisywany.
* **Stawka z pola „Stawka za jedną Roboczogodzinę (zgodna z Ofertą Wykonawcy)”
  jest brutto i zawsze jest dzielona przez 1,23**, z jednostką godzinową.
  Przykład: 172,20 zł brutto/h daje **140,00 zł netto/h**. To przeliczenie nie
  powoduje niepewności odczytu; oryginalna kwota brutto pozostaje widoczna.
* Przy wdrożeniu jednorazowo poprawiane są oczekujące wpisy z tymi błędami.
  Dokumenty z innymi, nierozstrzygniętymi wątpliwościami pozostają bez zmian.
* **Wartość całkowita zamówienia nie jest przeliczana** — sprawdź ją sam.
* Ta reguła **działa zawsze**, bez żadnej konfiguracji.
* **Powiadomienia:** standardowe.

### PKO BP

* **PKO BP ma własną regułę odczytu dokumentu.**
  * **Numer** bierze z pola **„Zamówienie nr"**; numeru umowy ramowej
    („Umowa ramowa numer …") za numer zamówienia nie weźmie.
  * Dokument ma **tabelę Wykonawców** (nazwisko, profil, dwie daty, liczba MD,
    stawka). Gdy w tabeli jest **jedna osoba**, system wpisuje jej **okres,
    stawkę dzienną i liczbę MD**. Gdy osób jest **więcej**, stawkę i MD
    **zostawia puste** — bo są różne dla każdego wiersza; wtedy uzupełniasz je
    przy dodawaniu konsultantów.
  * Wiersz bez kompletu (dwie daty + dwie liczby) nie jest brany za wiersz
    osoby — lepiej puste pole niż zła liczba.
  * **Stawka od 1 000 zł zapisana ze spacją („58 1 240,00") jest czytana jako
    stawka, a nie jako część liczby MD.** Do 09.2026 wychodziło z tego 581 MD
    po 240,00 zł — i to bez żadnego ostrzeżenia. Gdy tę samą treść da się
    przeczytać na dwa sposoby („2 500 900,00" to 2 MD po 500 900 zł albo
    2500 MD po 900 zł), wiersz zostaje **bez liczb** i trafia do sprawdzenia
    z tym powodem. Liczba MD zapisana ze spacją („1 200") wchodzi, ale
    z ostrzeżeniem — porównaj ją z PDF-em.
  * **Imię i nazwisko** bierze wyłącznie z kolumny „Imię i nazwisko
    Wykonawców" — nazwa profilu z sąsiedniej kolumny („Tester Middle") nie jest
    doklejana, więc system rozpoznaje istniejącego konsultanta i proponuje
    przedłużenie. Gdy granicy między nazwiskiem a profilem nie da się ustalić
    pewnie, osoba trafia do sprawdzenia z tym powodem.
  * **Stawka z kolumny „Stawka PLN/MD netto" jest zawsze netto** — system nie
    pyta, czy to brutto, i nie dzieli jej przez 1,23 („brutto" przy łącznej
    wartości zamówienia nie ma na to wpływu). Gwiazdka przy kwocie („stawka
    negocjowana") jest pomijana. Tylko gdy kolumna stawki byłaby oznaczona
    „brutto", wpis trafi do sprawdzenia.
  * Wpisy PKO BP czekające w kolejce przeliczają się same po wdrożeniu tej
    reguły.
* Gdy nie znajdzie numeru albo tabeli, powie o tym w banerze i zostawi pola do
  ręcznego wpisania.
* **Powiadomienia:** standardowe.

### KIR

* **KIR ma własną regułę odczytu dokumentu.**
  * **Numer** bierze z **„L.dz. KIR/…"**.
  * **Stawka jest GODZINOWA** — z zapisu „stawka … zł netto/h". Przelicznik na
    osobodzień podany w dokumencie („= … zł netto/1 MD") **jest ignorowany**:
    zapisujemy stawkę tak, jak klient rozlicza, czyli za godzinę.
  * **Okres** czytany z zakresu „od – do".
  * **Liczba MD z dokumentu jest pomijana** — to przeliczenie stawki, nie budżet.
* Gdy nie rozpozna numeru, okresu albo jednej stawki przy nazwisku, powie o tym
  i zostawi pole do ręcznego wpisania.
* **Powiadomienia:** standardowe.

### mLeasing

* **mLeasing ma własną regułę odczytu dokumentu.**
  * **Numer** bierze z **„Numer zamówienia DO/…"**.
  * **Stawka i jej jednostka** czytane są z komórki pozycji (np. „225,00 dzień
    869,92 PLN") — jednostka może być dzienna, godzinowa albo miesięczna,
    zależnie od tego, co stoi w dokumencie.
  * **Okres** z „Okres zatrudnienia od … do …".
  * **Liczba MD jest pomijana.**
* Gdy nie znajdzie numeru, okresu albo ceny jednostkowej pozycji, powie o tym
  i zostawi pole do ręcznego wpisania.
* **Powiadomienia:** standardowe.

### VeloBank

* **VeloBank ma własną regułę odczytu dokumentu.**
  * **Numer** z **„Zamówienie nr"**.
  * Dokument ma tabelę **„Dane wykonawców"**, w której **każda osoba ma własny
    okres i własną stawkę** (dzienną). W VeloBanku **każdy konsultant dostaje
    osobne zamówienie**, więc gdy w tabeli jest kilka osób, system zostawia
    stawkę i MD puste — wypełniasz je per osoba; okres wpisuje z dokumentu tylko
    wtedy, gdy wszyscy mają ten sam.
  * System sprawdza rachunek: **suma (MD × stawka) musi zgadzać się z „Wartość
    zlecenia NETTO"** — rozbieżność to sygnał źle odczytanego wiersza i dostaniesz
    o niej ostrzeżenie.
* **Powiadomienia:** standardowe.

### Cardif (BNP Paribas Cardif)

* **To osobny klient niż „BNP Paribas" powyżej** — inny dokument i inna reguła.
  Nie pomyl obu przy odczycie.
* **Cardif ma własną regułę odczytu dokumentu.**
  * **Dokument nie ma numeru** — identyfikatorem jest **data z „Zamówienie
    z dnia …"** i to ona trafia w pole numeru.
  * **Stawka** to liczba w nawiasie **„(… PLN/MD net.)"**, traktowana jako kwota
    za osobodzień.
  * **Zamówienie jest OKRESOWE** — liczba MD z tabeli jest tylko informacją,
    **nie budżetem** (system nie pilnuje jej jako puli).
  * **Okres** z wiersza specjalisty (gdy w tabeli jest jedna osoba).
* Gdy nie znajdzie identyfikatora, tabeli albo stawki, powie o tym i zostawi
  pola do ręcznego wpisania.
* **Powiadomienia:** standardowe.

### Centrum e-Zdrowia

* Jedyny klient z polem **„Umowa wykonawcza \*"** — i jest ono **obowiązkowe**
  przy nowym zamówieniu oraz przy przedłużeniu. Lista jest **pogrupowana po
  części umowy ramowej** (**cz.1, cz.2, cz.4, cz.5, cz.6** — część 3. nie
  istnieje i to jest poprawne); część zamówienia wynika z wybranej umowy
  wykonawczej, nie wybierasz jej osobno.
* **Część bez umowy wykonawczej nie przyjmuje konsultanta.** Nowe umowy
  wykonawcze dodajesz na profilu klienta w sekcji **Struktura umów** (numer
  + część ramowa; nowa umowa jest od razu aktywna). Umowę zakończysz dopiero
  wtedy, gdy nikt nie jest do niej przypisany.
* System **nie odczyta** umowy wykonawczej z dokumentu — numery „do umowy
  ramowej" na dokumentach bywają zamienione, więc wybierasz ją sam.
* Ekran **„Przypisania do przeglądu"** (profil klienta → Struktura umów)
  pokazuje obecnych i planowanych konsultantów bez umowy wykonawczej. Każdego
  przypisujesz **ręcznie** — ekran podświetla tylko nagłówek części z
  dotychczasowego pola, **bez domyślnego wyboru umowy**. Konsultant bez
  żadnego zamówienia dostaje przy przypisaniu szkic zamówienia do uzupełnienia.
* **Karta konsultanta na zamówieniu MD** (tylko u tego klienta) ma trzy części:
  u góry imię i nazwisko z ikonami akcji (rozliczenia miesięczne, edycja,
  zamiana kontraktora, usunięcie z zamówienia); pośrodku stawka oraz bloki
  **Podstawa** i **Opcja** — każdy z „wykorzystano / limit MD", procentem
  i **„Pozostało N MD"**; na dole pasek **„Łącznie"**. Gdy umowa nie ma opcji,
  zamiast bloku stoi **„Brak opcji w umowie"**, a „Łącznie" liczy wyłącznie
  podstawę. „Pozostało" w „Łącznie" uwzględnia ręczną korektę budżetu — wtedy
  obok stoi **„w tym korekta ±N MD"**, dlatego suma z bloków może się różnić.
  Przekroczony zakres pokazuje na czerwono **„Przekroczono o N MD"**.
  Akcje całego zamówienia (uzupełnienie, przedłużenie, zakończenie) zostają
  pod listą konsultantów.
* **Powiadomienia:** standardowe.

### Alior

* **Alior ma własną regułę odczytu dokumentu — tę samą przy mailu, „Zczytaj
  dane z dokumentu", uzupełnianiu i przedłużaniu zamówienia.** Z PDF-a czyta
  wyłącznie cztery pola:
  * **Numer** z **„Zamówienie nr: OIT/…"** (a nie z „Do Umowy Ramowej:
    OIT/…").
  * **Imię i nazwisko** z kolumny **„Imię i Nazwisko Konsultanta / członków
    Zespołu"**.
  * **Okres**: najpierw zakres w nawiasie pod nazwiskiem, np.
    „(05.10.2026-28.10.2026)"; gdy go nie ma — początek z „Moment wejścia
    w życie Zamówienia", koniec z „czas oznaczony" w „Okresie obowiązywania".
  * **Stawka** z kolumny **„Razem stawka dla Banku [PLN netto]"**, za dzień (MD)
    — nie „Stawka bazowa za MD" ani „Total". Kwota bywa zapisana bez groszy
    albo z jedną cyfrą po przecinku („1265,5") — to nadal ta sama stawka.
* **Rodzaj kompetencji, Liczba Roboczodni, Stawka bazowa, Marża, Total
  i warunki szczególne są pomijane.** Nie trafiają do zamówienia i nie są
  powodem do weryfikacji — także ich zgodność z „Maksymalną wartością
  Zamówienia" nie jest już sprawdzana.
* **Stawka jest domyślnie netto.** Brak słowa „netto" przy kwocie nie zatrzymuje
  zamówienia i nic nie jest przeliczane. Gdy w tabeli Konsultantów stoi jawnie
  „brutto" (nagłówek kolumny albo sama kwota), zamówienie trafia do weryfikacji
  z powodem **„Stawka oznaczona w dokumencie jako brutto, mimo że dla Alior Bank
  domyślnie jest netto — zweryfikuj"**; kwota nie jest wtedy dzielona przez
  1,23 — decyzja należy do Ciebie. „Brutto" przy sumie „Razem PLN" pod tabelą
  dotyczy pomijanego Totalu, nie stawki, i niczego nie zatrzymuje.
* **Osoba z PDF-a jest dopasowywana do konsultantów Aliora** po imieniu
  i nazwisku. Gdy ma szkic zamówienia (📝 Draft), zamówienie z maila **samo go
  uzupełnia** numerem, okresem i stawką — bez przycisku „Zastosuj". Imię
  i nazwisko z tabeli musi zgadzać się z niezależnym odczytem modelu; każda
  rozbieżność (osoba, stawka, okres) trafia do weryfikacji z konkretnym powodem
  — także wtedy, gdy model stawki albo okresu nie potwierdził.
* **Żadna pozycja nie znika po cichu.** Osoba z odczytu, której wiersza system
  nie odczytał z tabeli (np. druga pozycja tej samej osoby z inną stawką albo
  wiersz w nietypowym układzie na kolejnej stronie), zatrzymuje cały dokument
  do weryfikacji. Pomijane jest wyłącznie dokładne powtórzenie tej samej osoby
  z tą samą stawką i okresem. Okres odwrócony (początek po końcu) też zawsze
  trafia do weryfikacji.
* **W formularzu („Zczytaj dane z dokumentu", uzupełnienie, przedłużenie)
  stawka pochodzi wyłącznie z wiersza tej samej osoby.** Podobne nazwisko to
  inna osoba — np. dla „Anna Nowak" wiersz „Anna Nowak-Kowalska" nie daje
  stawki i pole zostaje puste do wpisania.
* **Wpisy Aliora czekające w kolejce sprzed zmiany reguły przeliczają się
  same** przy najbliższym sprawdzeniu skrzynki (patrz „Przelicz plan" wyżej).
  Dokument w starszym układzie tabeli (kwoty z groszami, marża z przecinkiem)
  zostaje przy tym w weryfikacji z powodem „odczyt zapisany przed zmianą
  reguły Aliora nie potwierdza osób z tabeli" — sprawdź osobę, okres i stawkę
  i zapisz ręcznie.
* Warto też wiedzieć (to działa u każdego klienta, nie tylko tutaj):
  **stawki godzinowe zapisują się z dokładnością do trzech miejsc po przecinku**
  — np. 164,375 zł/h. System niczego nie zaokrągla, więc wpisuj wartość
  z dokumentu co do trzeciego miejsca.
* **Powiadomienia:** standardowe.

### Pozostali klienci

* Do wyboru **wszystkie trzy typy** zamówienia. Zamówienia MD i kosztowe nie są
  już zarezerwowane dla wybranych firm — jeśli klient przysłał jeden numer
  obejmujący kilka osób, załóż je również tutaj.
* W nowym MD budżet dni jest domyślnie **przypisany każdej osobie**. Checkbox
  **„Budżet MD na całe zamówienie”** pozwala wybrać wspólną pulę także tutaj.
* Odczyt PDF-a działa w wersji ogólnej — bez przeliczeń specyficznych dla
  klienta, **poza jednym: brutto/netto** (patrz niżej).
* **Rodzaj stawki (brutto/netto) system czyta z OZNACZENIA w dokumencie, dla
  każdego zamówienia z osobna — nie z ustawienia klienta.** Gdy przy kwocie
  stawki stoi „brutto", stawka jest dzielona przez **1,23** (obok pola widać
  kwotę brutto z dokumentu do porównania); gdy stoi „netto" albo nie ma żadnego
  oznaczenia, kwota zostaje bez zmian; **brak oznaczenia albo konflikt
  brutto/netto wymaga weryfikacji**. Dotyczy to **klientów poza Nordeą, Aliorem i wskazanym polem PFRON**, także
  spoza listy wyżej — jeżeli więc dokument nowego klienta ma stawkę brutto,
  system ją przeliczy. U Erste dokumenty są zwykle brutto, ale także tam
  decyduje zapis w dokumencie: jawne „netto" przy stawce **wygrywa** i wtedy
  przeliczenia nie ma. Zawsze zerknij na kwotę brutto pokazaną obok pola.
* **Powiadomienia:** standardowe, a na zamówieniach MD dodatkowo alert
  **„mało MD"**, gdy konsultantowi zostanie 21 dni lub mniej.

---

## Najczęstsze pułapki

1. **„Widzę klienta, ale nie dostaję o nim powiadomień."** Globalny dostęp do
   klienta nie zmienia routingu alertów. Sprawdź aktywność konta, rolę, dostęp
   do sekcji Delivery oraz przypisanie na zakładce „Delivery Lead" w profilu
   klienta. Bez przypisania nie powstaną dla Ciebie **sprawy z pulpitu** — i nie
   trafią wtedy do nikogo. Powiadomienia o **końcu
   zamówienia** (30/14/7 dni) dostaje globalnie także aktywny administrator,
   ale nie Head of Recruitment; Delivery Lead dostaje je tylko dla przypisanych
   klientów.
2. **„Zamówienie utknęło w Draft."** Zbiorcze MD zapisane świadomie jako
   „Draft" trzeba po uzupełnieniu aktywować przez **Uzupełnij zamówienie →
   Aktywne** (w oknie „Nowe zamówienie" domyślny jest status „Aktywne").
   Przy szkicu pojedynczej osoby brakuje zwykle jednej z czterech rzeczy: numeru,
   daty rozpoczęcia, stawki przychodowej albo kosztowej. **Jeżeli szkic ma typ MD
   albo Kosztowy, potrzebny jest jeszcze budżet** — bez niego cztery pozostałe
   pola nie wystarczą. **Data zakończenia nie jest wymagana** — nie wpisuj jej
   „żeby ruszyło".
3. **„Odczyt zostawił puste stawki."** Przy zamówieniach z wieloma osobami to
   zwykle znaczy, że system nie potrafił jednoznacznie znaleźć wiersza wybranej
   osoby — i celowo nie zgadywał. Sprawdź, czy wybrałeś właściwego konsultanta,
   i wpisz stawkę ręcznie. Pusta **stawka kosztowa** na karcie w oknie „Nowe
   zamówienie" znaczy, że osoba nie ma jeszcze wskazanego kontraktu albo kontrakt
   nie ma stawki — wskaż osobę albo wpisz stawkę.
4. **„Wybrałem zły typ zamówienia."** Zamówienie **zbiorcze** ma typ zablokowany
   od razu po zapisie. Zamówienie **pojedynczej osoby, dopóki jest w Draft**,
   poprawisz bez zakładania nowego: otwórz „Uzupełnij zamówienie" i przełącz typ.
   Po aktywacji typ jest już zamknięty — wtedy zakładasz zamówienie od nowa,
   a błędne usuwasz.
5. **„Zapis zamówienia zwrócił błąd pliku."** Zamówienie **zostało zapisane** —
   wgraj plik ponownie przez „Uzupełnij zamówienie". Nie zakładaj zamówienia
   drugi raz.
6. **„Kliknąłem Oznacz jako obsłużone, a problem trwa."** Ta sprawa już nie
   wróci. Trzymaj to kliknięcie na moment, w którym naprawdę ją zamykasz.
7. **„Kwoty pokazują myślnik."** Jeżeli nie jesteś przypisany do klienta, to
   oczekiwany bezpieczny widok: widzisz dane operacyjne, ale nie stawki ani
   budżety. Jako Delivery Lead przypisany do klienta stawki widzisz — wtedy
   myślnik oznacza **brak wpisanej stawki** i trzeba ją uzupełnić. Przy brakującej
   stawce przychodowej na aktywnym zamówieniu przyjdzie o tym osobne
   powiadomienie.
8. **„Osoba wzięta z Bazy Nexus nie liczy się do przychodów."** Powstał jej
   **szkic umowy** — trzeba go domknąć osobno.

---

## Skąd wiadomo, że ta instrukcja jest aktualna

Data u góry (**Zgodność z systemem sprawdzona**) to dzień, w którym treść ostatni
raz porównano z działającym systemem.

**Zmiana w module zamówień nie może trafić na produkcję, dopóki ktoś nie
przejrzy tej instrukcji i nie potwierdzi jej nową datą.** Pilnuje tego sama
aplikacja przy wypuszczaniu zmian — także liczb, które tu padają wprost, jak
próg „21 MD" i powtórka „co 7 dni". Dzięki temu data u góry nie jest
deklaracją, tylko warunkiem wypuszczenia zmiany.

Jeżeli mimo to zauważysz, że system zachowuje się inaczej, niż tu napisano —
zgłoś to. To znaczy, że jakaś zmiana ominęła ten przegląd.

Treść jest odświeżana przy każdym wdrożeniu. **Jeżeli poprawisz ją ręcznie
w edytorze procedur, przestanie być odświeżana** — od tego momentu utrzymujesz ją
sam. Dopisanie praktyki zespołu jest jak najbardziej w porządku; opisu działania
systemu lepiej nie poprawiać na własną rękę — zgłoś rozbieżność, żeby poprawka
weszła po obu stronach.

### Nordea — wspólny odczyt PDF

Mail, nowe zamówienie oraz uzupełnienie i przedłużenie używają tej samej reguły. Odczyt obejmuje wyłącznie numer „Call Off Agreement number”, daty „Start date” i „End date” z „Initial Term” oraz każdą osobę i jej stawkę z tabeli „Consultant(s)”. Formularz wskazanej osoby wybiera jej stawkę z tej samej pełnej listy. Odczytani konsultanci są widoczni przy formularzu.

„Total, excl. VAT”, „Subtotal” i Quantity nie trafiają do modelu ani do budżetu zamówienia. Nie zatrzymują odczytu ani automatycznego zapisu. Nieznalezione pola wymagane, niejednoznaczna osoba i rzeczywiste konflikty nadal wymagają kontroli. Rozpoznanie klienta numerem rejestrowym pozostaje bez zmian.
