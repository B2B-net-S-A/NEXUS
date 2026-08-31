> **Zgodność z systemem sprawdzona:** 2026-08-31

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

* sześć filtrów z licznikami: **Wszystkie**, **Aktywne**, **⚠️ Kończące się 30d**,
  **Zakończeni**, **Wyczerpane**, **📝 Draft (do uzupełnienia)**,
* wyszukiwarkę po numerze zamówienia albo imieniu i nazwisku konsultanta,
* **Filtry i sortowanie** (zakresy dat, „Bliskie wyczerpania budżetu (≥80%)",
  „Kończące się w ciągu N dni"),
* **Pobierz do Excela** — eksport tego, co aktualnie widzisz,
* przycisk **Nowe zamówienie**.

Dwa filtry działają węziej, niż sugeruje nazwa, i warto o tym wiedzieć:
**📝 Draft** pokazuje wyłącznie zamówienia z kart pojedynczych konsultantów
(zamówienia zbiorcze nigdy tam nie wpadną), a **Wyczerpane** — odwrotnie,
wyłącznie zamówienia zbiorcze.

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

**Budżet MD jest przypisany osobie — z dwoma wyjątkami.** Na zwykłym zamówieniu
MD **każdy konsultant ma własny budżet dni**, widoczny przy jego nazwisku, i to
jego podajesz przy dodawaniu osoby do zamówienia. Tylko u **Lotte Wedel**
i **Cyfrowego Polsatu** obowiązuje **wspólna pula dni dla całego zamówienia**:
karta pokazuje wtedy napis **„Wspólna pula"**, a przy dodawanym konsultancie
nie ma pola budżetu.

Różnica jest praktyczna, nie kosmetyczna — od niej zależy, **czego wymaga
miesięczny import z Finansów** (wspólna pula potrzebuje numeru zamówienia
w kolumnie „Uwagi", sam budżet przy osobie nie) i **czego dotyczą ostrzeżenia
o kończących się dniach**: przy budżecie przy osobie liczą się dni tej osoby,
przy wspólnej puli — dni całego zamówienia. Modelu nie da się przełączyć;
poznajesz go po tym, co widzisz na karcie.

**Nie u każdego klienta masz wszystkie trzy do wyboru.** Cztery firmy mają
zawężoną listę wpisaną na stałe w systemie (szczegóły w sekcjach per klient);
u wszystkich pozostałych przełącznik pokazuje wszystkie trzy typy.

---

## Jak dodać zamówienie okresowe (jedna osoba)

Są **trzy drogi** i wybór między nimi zależy wyłącznie od tego, czy ta osoba jest
już w rejestrze klienta.

**1. Osoba jest już na liście (najczęstszy przypadek).** Bardzo często system
założył jej kartę sam — po przestawieniu kandydata na etap „zatrudniony" albo po
potwierdzeniu obustronnie podpisanej umowy. Powstaje wtedy **szkic umowy** i **szkic
zamówienia** ze stawką przepisaną z umowy i notatką „Uzupełnij stawkę klienta,
daty i wgraj PDF zamówienia". W rubryce **Numer zamówienia** stoi wtedy wartość
zastępcza: **„(bez numeru)"** u klientów rozliczanych w MD lub kosztowo, a u
pozostałych **„Imię Nazwisko — Tytuł rekrutacji"**. Jedno i drugie trzeba
zastąpić prawdziwym numerem z dokumentu klienta. Szkic znajdziesz pod filtrem
**📝 Draft (do uzupełnienia)**.

Kliknij **Uzupełnij zamówienie** na karcie tej osoby i wypełnij dane z dokumentu
od klienta.

**2. Osoba jest na liście, ale chcesz poprawić jedno pole.** Numer zamówienia,
obie stawki i okres edytujesz **klikając wprost w tekst na karcie** — bez
otwierania okienka. Jeżeli ta osoba nie ma jeszcze żadnego zamówienia, pierwszy
taki zapis sam założy szkic.

**3. Osoby nie ma jeszcze w rejestrze.** Kliknij **Nowe zamówienie**, wybierz typ
**Okresowe** — otworzy się formularz **„Nowy kontraktor / zamówienie"**, który
zakłada **jednocześnie umowę i pierwsze zamówienie**. Pola:

* **Kandydat \*** — wyszukiwarka po imieniu, e-mailu, umiejętności
* **Rekrutacja (opcjonalnie)**
* **Numer zamówienia \*** — np. 45767
* **Contract start \*** / **Contract end** — okres umowy z konsultantem
* **Order start (PDF od klienta)** / **Order end** — okres zamówienia
* **Jednostka stawki** — Godzinowa / MD / Miesięczna
* **Klient płaci \*** — stawka przychodowa
* **My płacimy kontraktorowi \*** — stawka kosztowa
* **Godziny / mc** — aktywne tylko przy stawce **godzinowej**
* **Notatki**
* **PDF zamówienia od klienta** — `.pdf`, `.docx` albo `.doc`, z przyciskiem
  **Zczytaj dane z dokumentu** obok

Zapisujesz przyciskiem **Stwórz Contract + Order**.

> **Jednostka stawki jest domyślnie „Miesięczna".** Ustaw ją **zanim** wpiszesz
> kwoty — przełączenie jednostki przelicza obie stawki, a stawka godzinowa
> zapisana jako miesięczna daje kwotę mniej więcej sto sześćdziesiąt razy za
> dużą. Nie zatwierdzaj formularza klawiszem Enter, dopóki jednostka nie jest
> ustawiona.

> **Umowa powstaje jako szkic** i tym formularzem jej nie domkniesz — zrobisz to
> w rejestrze umów. Dopóki jest szkicem, ta osoba nie liczy się do przychodów.
>
> **Jeżeli zapis zwróci błąd pliku, kontraktor i zamówienie i tak powstały.**
> Plik idzie osobnym żądaniem, więc komunikat mówi wprost, żeby wgrać go
> ponownie przez **Uzupełnij zamówienie** — a nie zakładać wszystkiego drugi raz.

### Kiedy zamówienie przestaje być szkicem

Szkic awansuje na **Aktywne sam, w chwili zapisu**, gdy ma komplet czterech
rzeczy: prawdziwy numer (nie „(bez numeru)"), datę rozpoczęcia, stawkę
przychodową i stawkę kosztową.

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

---

## Jak dodać zamówienie MD albo kosztowe (kilku konsultantów, jeden numer)

Zakładanie jest **dwuetapowe** i to jest najczęstsze źródło nieporozumień:
najpierw powstaje samo zamówienie, a **dopiero potem dokładasz do niego ludzi**.

**Krok 1 — załóż zamówienie.** Przycisk **Nowe zamówienie**, typ **MD** albo
**Kosztowe**. W formularzu **„Nowe zamówienie"**:

* **Typ zamówienia** — wybierany raz, później zablokowany
* **Numer zamówienia \*** — ten, który nadał klient (np. „445")
* **Budżet w MD \*** (typ MD) albo **Budżet całkowity (PLN) \*** (typ kosztowy)
* **Obowiązuje od \*** i **Obowiązuje do** — puste „do" znaczy bezterminowo
* **Notatki**
* **PDF zamówienia od klienta** — tylko rozszerzenie `.pdf`, do 25 MB

Zapisujesz przyciskiem **Utwórz zamówienie**.

> **Jeżeli plik nie wejdzie, zamówienie i tak zostało zapisane.** Zapis
> zamówienia i wysłanie pliku to dwie osobne operacje. System powie Ci wprost, że
> masz wgrać plik ponownie przez edycję — **nie zakładaj zamówienia drugi raz**.

Wgrany PDF pojawia się nie tylko na karcie zamówienia: znajdziesz go też
w sekcji **„Dokumenty zamówień"** w dokumentach umowy konsultanta i w jego
plikach. Rola bez dostępu do zamówień tego klienta tej sekcji po prostu nie
zobaczy — bez żadnego komunikatu.

**Krok 2 — dodaj konsultantów.** Na karcie zamówienia kliknij **Dodaj konsultanta
do zamówienia**. Wyszukiwarka pokazuje dwa źródła:

* **Rekrutacja u klienta** — osoby, które mają u tego klienta umowę,
* **Baza Nexus** — dowolny aktywny konsultant z całej firmy.

Wybranie osoby z **Bazy Nexus** jest w porządku i tak ma być: system założy jej
u tego klienta **szkic umowy**, żeby było do czego przypiąć zamówienie. Umowę
trzeba potem domknąć osobno — szkic nie wchodzi do przychodów ani do alertów
o wygasaniu.

Każdy konsultant to osobna **linia** — tak nazywają wiersz jednej osoby na
zamówieniu przyciski w aplikacji („Edytuj linię"). Linia ma **obie stawki i obie
są wymagane**.
Na zamówieniu **MD** podajesz przy każdej osobie jej **budżet dni**; przełącznik
daje wybór **„Liczba MD"** albo **„Kwota zamówienia"** — tę kwotę system dzieli
przez stawkę przychodową i sam wylicza liczbę dni. Pola budżetu przy osobie
**nie ma** na zamówieniu **kosztowym** ani na zamówieniu MD ze **wspólną pulą**
(Lotte Wedel, Cyfrowy Polsat) — tam pula jest wspólna.

Przycisk **Dodaj konsultanta** jest wyszarzony tylko przy zamówieniu
**zakończonym** albo **wyczerpanym**. Do zamówienia **przyszłego** (z datą startu
w przód) konsultantów dodajesz normalnie — czekają razem z nim na dzień startu.

### Co jeszcze możesz zrobić na karcie zamówienia zbiorczego

| Przycisk | Co robi |
|---|---|
| **Uzupełnij zamówienie** | edycja numeru, budżetu, dat, notatek, podmiana PDF-a |
| **Dodaj przedłużenie** | zakłada **nowe** zamówienie podpięte pod obecne (patrz niżej) |
| **Zakończ** | okienko „Zakończ zamówienie": obowiązkowa data + opcjonalny powód |
| **Przywróć** | cofa zakończenie — pokazuje się przy **każdym** zamówieniu ze statusem „Zakończone", także takim, które system domknął sam; przy zamówieniu MD z budżetem przy osobie wskrzesza też konsultantów, którym zostały dni i nie minęła data. Zamówienia **wyczerpanego** nie przywrócisz — tam trzeba podnieść budżet |
| **Usuń całe zamówienie** | służy do wycofania **pomyłki** i jest nieodwracalne: zamówienie znika razem ze swoją historią. **Zamówienia z rozliczeniami system nie usunie** — odmówi i wskaże, co je blokuje (rozliczone MD, zaimportowane faktury). Wtedy właściwą akcją jest **Zakończ**. Konsultanci nie znikają nigdy: linia, po której coś zostało, jest **odpinana** od numeru i żyje dalej |
| **Historia zamówienia** | rozwijana lista zdarzeń z datami i opisem: utworzenie, dodania i zamiany konsultantów, importy, decyzje o MD, zakończenia. **Nie ma tu edycji zrobionych przez „Uzupełnij zamówienie"** — zmiana numeru, dat, notatek czy budżetu nie zostawia śladu |

Przy każdym konsultancie masz osobno: **Edytuj linię**, **Zamień kontraktora**
(tylko przy aktywnej linii) i **Usuń konsultanta z zamówienia**. Gdy po
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
staje się aktywne od razu przy zapisie.

**Przy zamówieniach MD jest inaczej: przedłużenie czeka, aż poprzednikowi skończą
się dni** — nawet gdy jego własna data startu dawno minęła. Dopóki w poprzednim
zamówieniu zostają MD, nowe figuruje jako przyszłe. To celowe: niewykorzystane
dni nie mogą przepaść tylko dlatego, że zaczął się nowy okres.

### Zamiana kontraktora

Tworzy **nową linię** i domyka starą datą zamiany. Na zamówieniu **MD
z budżetem przy osobie** system sam przelicza dni tak, żeby wartość w złotych
została ta sama (nowe MD × nowa stawka = pozostałe MD × stara stawka). Przy
zamówieniu **kosztowym** i przy **wspólnej puli MD** nie rusza budżetu w ogóle —
zmienia się tylko osoba i jej stawki.

Data zamiany w przyszłości **nie wyłącza od razu** osoby, która dziś pracuje —
poprzednik dostaje datę zakończenia od razu, ale status „zakończony" dopiero gdy
ten dzień nadejdzie.

Do **Historii zamówienia** trafiają zawsze obie stawki (stara i nowa) oraz data
zamiany. Liczby MD wpisują się tam tylko przy budżecie przypisanym
osobie — przy wspólnej puli i przy zamówieniu kosztowym nie ma czego zapisać.

---

## „Zczytaj dane z dokumentu" — co system odczyta z PDF-a

W formularzach zamówienia jest pomarańczowy przycisk **Zczytaj dane z dokumentu**.

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
* **części umowy** (dotyczy tylko Centrum e-Zdrowia).

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

**Przy dodawaniu konsultanta do zamówienia najpierw wybierz osobę** — bez tego
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
pojedynczego zamówienia także `.docx`. Odczyt korzysta z modułu AI — jeżeli
administrator go wyłączy albo ustawi miesięczny limit i ten się wyczerpie,
zobaczysz komunikat „Odczyt AI jest chwilowo niedostępny (…). Wpisz dane
ręcznie." Domyślnie limitu nie ma, więc w praktyce oznacza to świadome
wyłączenie funkcji przez administratora.

**Gdy AI nie zadziała, włącza się odczyt awaryjny** — zgrubny: bierze pierwsze
dwie daty i pierwszą kwotę z dokumentu, a **numeru zamówienia sam nie znajduje**
(wyjątkiem są klienci z własną regułą numeru, np. Nordea i Bank Pocztowy — tam
numer wyszukiwany jest po etykiecie i działa też w trybie awaryjnym). Poznasz go
po powodzie „Odczyt awaryjny (bez AI) — zweryfikuj wszystkie pola" w banerze.

**Przycisk „Zczytaj dane z dokumentu" kliknie administrator, Head of Recruitment
(u każdego klienta, bez przypisania) i Delivery Lead przypisany do tego klienta.**
Pozostałe role — w tym Finanse i nieprzypisany Delivery Lead — dostaną odmowę.
(To osobna sprawa od oglądania listy zamówień, opisanego w „Kto co może".)

**Kwoty z odczytu widzi tylko administrator i przypisany Delivery Lead.** Head of
Recruitment uruchomi odczyt, ale dostanie pusty komplet finansowy — to nie jest
błąd odczytu, tylko ukrycie danych. Liczba MD przychodzi normalnie: jest
wielkością operacyjną, nie finansową.

---

## Co system robi sam

* **Zakłada szkic umowy i szkic zamówienia** po przejściu kandydata na etap
  „zatrudniony" albo po potwierdzeniu obustronnie podpisanej umowy (u Polkomtela
  — nie, patrz sekcja tego klienta). Umowa powstaje jako **szkic**: dopóki jej
  nie domkniesz, ta osoba nie liczy się do przychodów.
* **Awansuje szkic na Aktywne** w chwili zapisu, gdy komplet danych jest na
  miejscu.
* **Uruchamia zamówienia przyszłe** w dniu ich startu — z jednym wyjątkiem: przy
  zamówieniach MD następca czeka dodatkowo, aż poprzednikowi skończą się dni,
  więc mimo minionej daty startu potrafi jeszcze przez jakiś czas figurować jako
  przyszły.
* **Domyka po dacie zakończenia poszczególne osoby** — zarówno zamówienia
  okresowe, jak i konsultantów na zamówieniach kosztowych i na zamówieniach MD
  ze wspólną pulą. Po minięciu daty ich linie same przechodzą do „Zakończeni".
  **Jedynym wyjątkiem są konsultanci z własnym budżetem MD** — tam o końcu
  decyduje budżet, nie kalendarz, więc osoba z niewykorzystanymi dniami pracuje
  dalej.
* **Samego zamówienia zbiorczego data nie zamyka.** Numer zostaje „Aktywny",
  dopóki nie klikniesz **Zakończ** albo dopóki nie wyczerpie się budżet — więc
  można do niego dopisywać kolejne osoby także po dacie z dokumentu, mimo że
  wcześniej dodani zostali już domknięci.
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
przyszłe, którym minął dzień startu, ale **niczego nie zamyka po dacie** — na to
trzeba poczekać na nocny przebieg.

## Co zawsze robisz ręcznie

* **Stawkę kosztową** — nie ma jej w żadnym dokumencie klienta.
* **Sprawdzenie tego, co odczytał PDF.** Odczyt jest podpowiedzią, nie źródłem
  prawdy — zwłaszcza gdy zapalił się baner „Sprawdź dane!".
* **Jednostkę stawki** (godzina / dzień / miesiąc) — ustawiasz sam, ale odczyt
  z dokumentu potrafi ją nadpisać, a każda zmiana jednostki od razu przelicza
  obie wpisane stawki. Po każdej zmianie sprawdź kwoty w obu polach.
* **Wgranie pliku zamówienia** przy zamówieniach okresowych — formularz
  zakładania nie ma pola na plik.
* **Domknięcie umowy** konsultanta wziętego z „Bazy Nexus" — powstaje jako szkic.
* **Decyzję o niewykorzystanych MD** po zakończeniu współpracy (patrz niżej).

---

## Powiadomienia — co przyjdzie, kiedy i gdzie

**Żadne z tych powiadomień nie przychodzi mailem.** Wszystko dzieje się
w aplikacji, w dwóch różnych miejscach.

### Miejsce 1: dzwonek w prawym górnym rogu

Trafiają tu powiadomienia o zbliżającym się końcu:

| Powiadomienie | Kiedy |
|---|---|
| **Zamówienie [nazwisko] kończy się za N dni** | 30, 14 i 7 dni przed datą zakończenia aktywnego zamówienia |
| **Umowa ramowa wygasa za N dni** | 30, 14 i 7 dni przed końcem umowy ramowej z klientem |
| Zbliżający się koniec umowy z konsultantem | 90, 60, 30, 14 i 7 dni przed końcem |
| **Nowy draft kontraktu + zamówienia** | w chwili zatrudnienia kandydata — z prośbą o uzupełnienie stawek, dat i wgranie PDF-a |

Każdy próg przychodzi raz. **Zmiana daty zakończenia w istniejącym zamówieniu
nie odnawia progów** — jeśli przesuniesz koniec o pół roku, ostrzeżenia 30/14/7
już się nie odezwą. Nowe ostrzeżenie dostaniesz dopiero wtedy, gdy powstanie
nowe zamówienie (np. przez „Dodaj przedłużenie").

### Miejsce 2: sekcja „Powiadomienia" na pulpicie Delivery Leada

Pulpit w widoku **Delivery Lead**. To lista **spraw do załatwienia**, z przyciskiem
**Oznacz jako obsłużone**, zakładką **Historia** i eksportem do Excela z czasem
reakcji. Pięć rodzajów:

| Sprawa | Kiedy powstaje | Czy się powtarza |
|---|---|---|
| **[Klient] — [kto] bez zamówienia** | zamówienie konsultanta wisi w statusie **Draft** (czeka na uzupełnienie) | co 7 dni |
| **[Klient] — brak stawki przychodowej** | zamówienie bez stawki, którą płaci klient | co 7 dni |
| **[Klient] — mało MD na zamówieniu [numer]** | zostało 15 MD lub mniej — konsultantowi (budżet przy osobie) albo całemu zamówieniu (wspólna pula) | co 7 dni |
| **[Klient] — zamówienie [numer] wyczerpane** | budżet **kosztowy** albo **wspólna pula MD** zeszły do zera | raz |
| **[Klient] — decyzja MD po zakończeniu współpracy** | konsultant zakończył pracę na zamówieniu MD — **zawsze**, także gdy nie zostało ani jedno MD | raz |

> **Uwaga na dziurę w pierwszym alercie:** przypomina on o zamówieniach
> w statusie **Draft**, a nie o osobach, które zamówienia **w ogóle nie mają**.
> Konsultant z umową, ale bez żadnego zamówienia — tak jak u Polkomtela, gdzie
> zamówienie zakładasz ręcznie — nie wywoła żadnego powiadomienia. Takich osób
> musisz pilnować sam.

**Warunek, bez którego nie dostaniesz nic z tej sekcji:** musisz być **przypisany
do klienta jako Delivery Lead** (profil klienta → zakładka „Delivery Lead"). Bez
przypisania sprawy z pulpitu dla tego klienta **w ogóle nie powstają — dla
nikogo**. To pierwsza rzecz do sprawdzenia, gdy „system nic nie przysyła".
Powiadomienia z dzwonka (Miejsce 1) idą niezależnie od przypisania.

Sekcja pokazuje wyłącznie **Twoje** wpisy — nawet administratorowi. Widać ją
tylko w widoku pulpitu „Delivery Lead".

**Powtórki wracają co 7 dni jako nowy wpis**, dopóki nie klikniesz **Oznacz jako
obsłużone** albo przyczyna nie ustąpi. Uwaga: kliknięcie **wycisza sprawę na
stałe**, także wtedy, gdy problem nadal trwa. Nowa sprawa (inne zamówienie, inna
osoba) alarmuje od nowa.

**Trzy rzeczy, o których warto wiedzieć zawczasu:**

* **Zamówienie kosztowe nie ostrzega wcześniej — tylko po fakcie.** Odpowiednika
  progu „mało MD" dla puli w złotych nie ma: alert przychodzi dopiero, gdy kwota
  zejdzie do zera. Wcześniejszy sygnał daje wyłącznie filtr **Bliskie wyczerpania
  budżetu (≥80%)**, który trzeba sprawdzać samodzielnie.
* **Alertu „decyzja MD" nie da się odkliknąć.** Zamyka się dopiero, gdy podejmiesz
  w zamówieniu decyzję o pozostałej puli.
* **Powiadomienia z pulpitu nie trafiają do dzwonka i odwrotnie.** To dwa osobne
  miejsca — sprawdzaj oba.

Skanery chodzą **raz na dobę, licząc od ostatniego restartu aplikacji** — nie ma
stałej godziny wysyłki.

Poza aplikację idzie tylko jedna rzecz: zbiorcze podsumowanie wygasających umów
z konsultantami na Slacka, i to wyłącznie gdy administrator skonfigurował
integrację.

### Zakończenie współpracy na zamówieniu MD

To jedyny moment, w którym system **zatrzymuje się i czeka na Twoją decyzję**.
Przy zamówieniu okresowym i kosztowym rozliczy zakończenie sam; przy MD zostaje
niewykorzystana pula i ktoś musi powiedzieć, co z nią zrobić. Do czasu decyzji
system blokuje inne zmiany na tym zamówieniu.

Okienko **„Zakończenie współpracy — decyzja o MD"** daje dwie opcje:
**Usuń z zamówienia** albo **Przelicz na innego konsultanta** (wskazujesz osobę
przejmującą i podstawę stawki: osoby odchodzącej albo przejmującej).

Przy **wspólnej puli MD** decyzja tylko zdejmuje osobę z obsady — pula nie jest
pomniejszana ani nikomu przypisywana, bo i tak była wspólna.

---

## Kto co może

Uprawnienia rozkładają się na **trzy niezależne poziomy** i to tłumaczy większość
pytań „dlaczego nie widzę przycisku".

| Poziom | Kto |
|---|---|
| **Odczyt zamówień** | administrator, Head of Recruitment oraz Delivery Lead i TAC **przypisani do klienta**. Rola Finanse widzi **tylko zamówienia zbiorcze (MD i kosztowe)** — sekcja „Okresowe" jest dla niej pusta, bez żadnego komunikatu |
| **Cykl życia** (zakończ, przywróć, usuń — także usunięcie konsultanta) | administrator, Head of Recruitment, Finanse, przypisany Delivery Lead |
| **Stawki i obsada** (dodanie/edycja konsultanta, edycja zamówienia) | **wyłącznie** administrator i przypisany Delivery Lead |

**Head of Recruitment i Finanse przechodzą bramkę u wszystkich klientów, bez
przypisania** — ale stawek nie zapiszą. Head of Recruitment dodatkowo ich **nie
zobaczy** (w miejscu kwot ma „—"); rola Finanse kwoty **widzi**, tylko nie może
ich zmienić. Delivery Lead **zawsze** wymaga jawnego przypisania do klienta.

**Przedłużenie jest w tej tabeli tylko formalnie.** Samo okienko otworzy każdy
z powyższych, ale przedłużenie, w którym od razu podaje się konsultantów ze
stawkami, wymaga uprawnień finansowych — czyli w praktyce administratora albo
przypisanego Delivery Leada.

Rola bez uprawnień do stawek (np. Head of Recruitment, TAC) widzi na zamówieniach
zbiorczych **myślnik „—"** — nie zero i nie komunikat o błędzie — a na kartach
pojedynczych konsultantów wiersze z pieniędzmi w ogóle się nie pokazują.

**Importu zużycia MD nie robi Delivery Lead.** Moduł Finanse jest dostępny tylko
dla ról administrator i Finanse — ale wynik tego importu natychmiast zmienia to,
co widzisz w zakładce „Zamówienia", i uruchamia powiadomienia o budżecie.

---

## Skąd biorą się liczby zużycia

Zużycie — dni albo złotówek — wpisuje **wyłącznie miesięczny import raportu
z Finansów**. Delivery Lead nie odejmuje niczego ręcznie; może za to poprawić
błędną pozostałość korektą (patrz koniec tej sekcji).

* Import robi rola Finanse albo administrator, w **Finanse → Import zużycia MD**.
* Jeden plik obejmuje wszystkich klientów naraz. Miesiąc raportu **wybiera
  operator** — system nigdy nie zgaduje go z nazwy pliku.
* Wiersze dopasowywane są do zamówień **po imieniu i nazwisku**. Jedno trafienie
  → zaktualizowane; zero → „Brak aktywnego zamówienia"; **więcej niż jedno →
  „Wymaga przypisania"** i system czeka, aż człowiek wskaże właściwe zamówienie.
  Nie zgaduje, bo trafienie w złe zamówienie odejmuje dni nie temu klientowi
  i wychodzi dopiero na fakturze.
* **Przy wspólnej puli MD (Lotte Wedel, Cyfrowy Polsat) samo nazwisko nie
  wystarcza** — wiersz musi mieć dodatkowo **numer tego zamówienia w kolumnie
  „Uwagi"**. Bez numeru (albo gdy numer pasuje do kilku zamówień) **z puli nie
  schodzi ani jeden dzień**, a wiersz zostaje niedopasowany. To najczęstsza
  przyczyna „import przeszedł, a budżet stoi w miejscu".
* **U Polkomtela numer z „Uwag" jest rozstrzygający.** Jeżeli wiersz go niesie
  i pasuje do zamówienia Polkomtela — decyduje numer, nie nazwisko; jeżeli nie
  pasuje, system **nie wraca do dopasowania po nazwisku**, tylko zostawia wiersz
  niedopasowany. U BNP i BIK obowiązuje samo nazwisko.
* **Powtórny import tego samego miesiąca nadpisuje** poprzednie zużycie — MD nie
  odejmą się drugi raz.
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
administratorowi** zamiast obchodzić regułę ręcznie — z wyjątkiem Orlenu i PFRON,
które działają zawsze.

Skrót **„Powiadomienia: standardowe"** znaczy: alerty o końcu zamówienia
**30, 14 i 7 dni** przed datą (dzwonek) oraz sprawy **„bez zamówienia"** i
**„brak stawki przychodowej"** co 7 dni (pulpit Delivery Leada).

### BNP Paribas

* **Tylko zamówienia typu MD.** Przełącznik nie pokazuje ani „Okresowe", ani
  „Kosztowe" — to ustawienie wpisane na stałe w systemie, nie do zmiany
  z poziomu aplikacji.
* Jeden numer, kilku konsultantów, **budżet dni przy każdej osobie**. Zużycie
  schodzi z miesięcznego importu z Finansów, dopasowywanego po imieniu
  i nazwisku.
* **BNP ma własną regułę odczytu dokumentu.** Dokument jest jednoosobowy, więc
  wszystko, co w nim stoi, dotyczy osoby, z której karty uruchamiasz odczyt:
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
* **Powiadomienia:** standardowe, plus alert **„mało MD"**, gdy konsultantowi
  zostanie 15 dni lub mniej.

### BIK

* **Tylko zamówienia typu MD** — tak samo jak BNP i z tego samego powodu.
* Budżet dni przy każdej osobie; import dopasowuje wiersze po imieniu
  i nazwisku.
* **Powiadomienia:** jak u BNP — standardowe plus „mało MD" przy 15 dniach.

### Polkomtel

* **Zamówienia MD i kosztowe.** Typ „Okresowe" jest niedostępny.
* **System NIE zakłada tu automatycznie zamówienia po zatrudnieniu konsultanta.**
  U pozostałych klientów po przejściu kandydata na „zatrudniony" pojawia się
  szkic zamówienia do uzupełnienia — u Polkomtela musisz założyć zamówienie sam.
  To najważniejsza różnica praktyczna dla tego klienta.
* Przy zamówieniu kosztowym kwota jest **wspólna dla całego zamówienia**; przy
  konsultancie nie ma pola budżetu, są tylko obie stawki.
* Na zamówieniach MD budżet jest **przypisany osobie**, jak u BNP i BIK.
* **W imporcie z Finansów numer zamówienia z kolumny „Uwagi" jest u Polkomtela
  rozstrzygający.** Gdy wiersz go niesie, decyduje numer, a nie nazwisko — i gdy
  numer nie pasuje do żadnego zamówienia Polkomtela, system **nie próbuje już
  dopasować po nazwisku**, tylko zostawia wiersz niedopasowany.
* **Powiadomienia:** standardowe, plus alert **„mało MD"** przy 15 dniach na
  zamówieniach MD. Przy zamówieniu **kosztowym** przyjdzie jednorazowy alert
  o wyczerpaniu; **wcześniejszego ostrzeżenia o kończącej się kwocie nie ma
  w ogóle**, więc jedynym sygnałem jest filtr **Bliskie wyczerpania budżetu
  (≥80%)**, który trzeba sprawdzać samemu.

### Lotte Wedel

* **Zamówienia MD i kosztowe.** „Okresowe" są zablokowane nie tylko
  w interfejsie — próba zapisu zostanie odrzucona.
* Przy zamówieniu MD obowiązuje **wspólna pula dni**: budżet mieszka na
  zamówieniu, nie przy osobie. Konsultant dodany do takiego zamówienia **nie
  dostaje własnego budżetu MD** — wszyscy czerpią z jednej puli. **To wariant
  zarezerwowany dla Lotte Wedel i Cyfrowego Polsatu**; u pozostałych klientów
  budżet MD jest przypisany osobie.
* Pulę pomniejsza import z Finansów tylko wtedy, gdy wiersz zawiera
  **jednocześnie nazwisko i numer zamówienia** w kolumnie „Uwagi".
* Typy zamówień i wspólna pula są u tego klienta **wpisane w system na stałe** —
  działają niezależnie od konfiguracji. (Nie dotyczy to reguł odczytu PDF-a:
  Lotte Wedel żadnej własnej nie ma.)
* **Powiadomienia:** standardowe, a dla wspólnej puli MD dwa własne: **„mało MD"**,
  gdy w puli zostanie 15 dni lub mniej, oraz jednorazowy alert **o wyczerpaniu**,
  gdy zejdzie do zera i zamówienie przestanie przyjmować konsultantów. Przy
  zamówieniu **kosztowym** przychodzi tylko ten drugi — o kończącej się kwocie
  nie ostrzega nic poza filtrem „Bliskie wyczerpania budżetu (≥80%)".

### Cyfrowy Polsat

* **Wszystkie trzy typy do wyboru** — Okresowe, Kosztowe i MD.
* Przy typie MD obowiązuje **wspólna pula dni**, tak samo jak u Lotte Wedel.
* Typy zamówień i wspólna pula są wpisane w system na stałe, niezależnie od
  konfiguracji. Własnej reguły odczytu PDF-a ten klient nie ma.
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
„number", „no.", „nr" i „#"). **Numeru umowy ramowej („Frame Agreement number")
nie weźmie nigdy**, nawet gdy stoi w dokumencie wyżej — to była przyczyna
zgłoszenia „system wpisuje zły numer". Jeżeli tej etykiety w dokumencie nie ma, **system nie poda
żadnego numeru** — nigdy nie podstawi numeru oferty ani projektu. Dostaniesz
o tym komunikat w banerze — ale **pole numeru nie zostanie wyczyszczone**: jeżeli
coś już w nim stało (numer z poprzedniego zamówienia albo wartość zastępcza ze
szkicu), zostanie tam nietknięte i zapisze się razem z zamówieniem. Po odczycie
u Nordei **zawsze przeczytaj pole numeru** i wpisz właściwy ręcznie.
Pozostałe pola (daty, stawka) czytane są normalnie.

**2. Import zamówień z CSV — nie dla Ciebie.** W zakładce „Zamówienia" jest
zwijany panel **„Import zamówień Nordea z CSV"**, ale **widzi go wyłącznie
administrator**. Aktualizuje naraz wielu konsultantów z pliku od Finansów
(średnik jako separator; numer zamówienia, kontraktor, line manager, start,
koniec, stawka przychodowa, stawka z umowy ramowej). Przebieg jest dwuetapowy:
**Sprawdź import** (podgląd, nic się nie zapisuje), potem **Zastosuj import**
z potwierdzeniem. Import nadpisuje numer, obie daty, stawkę przychodową i status zamówienia,
a dodatkowo **zapisuje stawkę z umowy ramowej** — w umowie konsultanta jako
stawkę obowiązującą od podanej daty; jeśli wpis z tą samą datą już istnieje,
nadpisuje go.
**Stawki kosztowej nie rusza nigdy.** Powtórzenie tego samego pliku niczego nie
duplikuje.

* Nordea nie ma zawężonej listy typów — masz do wyboru wszystkie trzy. W praktyce
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

* **Kwota w dokumencie jest brutto.** System dzieli ją przez **1,23** i zapisuje
  wartość netto, a obok pola pokazuje kwotę brutto z dokumentu do porównania.
* **Jednostka stawki jest twardo ustawiana na godzinę** — nawet jeśli dokument
  mówił „za dzień" albo nie mówił nic. Dotyczy to wyłącznie sytuacji, w której
  jakąkolwiek stawkę udało się odczytać.
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

* **Liczba MD z dokumentu jest zawsze pomijana** — bezwarunkowo, szerzej niż
  u Orlena.
* **Data zakończenia** jest podawana tylko wtedy, gdy w dokumencie jest
  **dokładnie jedna** jednoznaczna data końca usług. Przy zerze albo kilku
  różnych datach system nie poda żadnej, a w banerze pojawi się o tym komunikat —
  ale **wcześniejszej wartości w polu nie skasuje**, więc sprawdź, co tam stoi.
* **Stawka jest przeliczana z brutto na netto** (dzielona przez 1,23),
  a jednostka ustawiana na **godzinę**. Pod polem zobaczysz podpis
  „Z dokumentu: X/h brutto → Y/h netto (÷ 1,23)".
* **Wartość całkowita zamówienia nie jest przeliczana** — sprawdź ją sam.
* Ta reguła **działa zawsze**, bez żadnej konfiguracji.
* **Powiadomienia:** standardowe.

### Centrum e-Zdrowia

* Jedyny klient z polem **„Wybór części umowy \*"** — i jest ono **obowiązkowe**
  przy nowym zamówieniu oraz przy przedłużeniu. Do wyboru: **cz.1, cz.2, cz.4,
  cz.5, cz.6** (część 3. nie istnieje i to jest poprawne).
* Systemu **nie odczyta** części umowy z dokumentu — wybierasz ją sam.
* **Powiadomienia:** standardowe.

### Alior

* **Alior nie ma w module zamówień żadnej własnej reguły.** Obowiązuje wyłącznie
  opis ogólny — ta sekcja istnieje po to, żebyś nie szukał dalej.
* Warto natomiast wiedzieć (to działa u każdego klienta, nie tylko tutaj):
  **stawki godzinowe zapisują się z dokładnością do trzech miejsc po przecinku**
  — np. 164,375 zł/h. System niczego nie zaokrągla, więc wpisuj wartość
  z dokumentu co do trzeciego miejsca.
* **Powiadomienia:** standardowe.

### Pozostali klienci

* Do wyboru **wszystkie trzy typy** zamówienia. Zamówienia MD i kosztowe nie są
  już zarezerwowane dla wybranych firm — jeśli klient przysłał jeden numer
  obejmujący kilka osób, załóż je również tutaj.
* Na zamówieniu MD budżet dni jest **przypisany każdej osobie** — wspólna pula
  jest zarezerwowana dla Lotte Wedel i Cyfrowego Polsatu.
* Odczyt PDF-a działa w wersji ogólnej — bez żadnych przeliczeń specyficznych dla
  klienta.
* **Powiadomienia:** standardowe, a na zamówieniach MD dodatkowo alert
  **„mało MD"**, gdy konsultantowi zostanie 15 dni lub mniej.

---

## Najczęstsze pułapki

1. **„Nie dostaję żadnych powiadomień o tym kliencie."** Sprawdź, czy jesteś
   przypisany jako Delivery Lead na zakładce „Delivery Lead" w profilu klienta.
   Bez przypisania nie powstaną dla Ciebie **sprawy z pulpitu** — i nie trafią
   wtedy do nikogo. Powiadomienia o **końcu zamówienia** (30/14/7 dni) idą
   niezależnie, także do administratora i Head of Recruitment.
2. **„Zamówienie utknęło w Draft."** Brakuje jednej z czterech rzeczy: numeru,
   daty rozpoczęcia, stawki przychodowej albo kosztowej. **Jeżeli szkic ma typ MD
   albo Kosztowy, potrzebny jest jeszcze budżet** — bez niego cztery pozostałe
   pola nie wystarczą. **Data zakończenia nie jest wymagana** — nie wpisuj jej
   „żeby ruszyło".
3. **„Odczyt zostawił puste stawki."** Przy zamówieniach z wieloma osobami to
   zwykle znaczy, że system nie potrafił jednoznacznie znaleźć wiersza wybranej
   osoby — i celowo nie zgadywał. Sprawdź, czy wybrałeś właściwego konsultanta,
   i wpisz stawkę ręcznie.
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
7. **„Kwoty pokazują myślnik."** Myślnik wygląda tak samo w dwóch różnych
   sytuacjach i **nie da się ich po nim rozróżnić**: stawki nie ma w systemie
   albo Twoja rola jej nie widzi. Jako Delivery Lead przypisany do klienta
   stawki widzisz — u Ciebie myślnik znaczy więc **brak wpisanej stawki**;
   uzupełnij ją. Przy brakującej stawce przychodowej na aktywnym zamówieniu
   przyjdzie o tym osobne powiadomienie.
8. **„Osoba wzięta z Bazy Nexus nie liczy się do przychodów."** Powstał jej
   **szkic umowy** — trzeba go domknąć osobno.

---

## Skąd wiadomo, że ta instrukcja jest aktualna

Data u góry (**Zgodność z systemem sprawdzona**) to dzień, w którym treść ostatni
raz porównano z działającym systemem.

**Zmiana w module zamówień nie może trafić na produkcję, dopóki ktoś nie
przejrzy tej instrukcji i nie potwierdzi jej nową datą.** Pilnuje tego sama
aplikacja przy wypuszczaniu zmian — także liczb, które tu padają wprost, jak
próg „15 MD" i powtórka „co 7 dni". Dzięki temu data u góry nie jest
deklaracją, tylko warunkiem wypuszczenia zmiany.

Jeżeli mimo to zauważysz, że system zachowuje się inaczej, niż tu napisano —
zgłoś to. To znaczy, że jakaś zmiana ominęła ten przegląd.

Treść jest odświeżana przy każdym wdrożeniu. **Jeżeli poprawisz ją ręcznie
w edytorze procedur, przestanie być odświeżana** — od tego momentu utrzymujesz ją
sam. Dopisanie praktyki zespołu jest jak najbardziej w porządku; opisu działania
systemu lepiej nie poprawiać na własną rękę — zgłoś rozbieżność, żeby poprawka
weszła po obu stronach.
