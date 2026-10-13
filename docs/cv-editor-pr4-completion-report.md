# Edytor CV 2 — PR 4: polecenie dla całego CV (13.10.2026)

Czwarty z pięciu PR-ów zatwierdzonych przez Artura 12.10.2026. Rekruter pisze
własnymi słowami, co zmienić w całym CV (albo wybiera gotowe polecenie),
i dostaje **plan zmian** do decyzji — operacja po operacji. Reguły:
`docs/claude/generator-cv/edytor-cv-pelny-ekran.md`, sekcja „Polecenie dla
całego CV (PR 4)”.

**Zakres jest węższy niż w planie:** przeniesienie zmian PL→EN nie weszło
i czeka na decyzję Artura (niżej, z liczbami).

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Pasek „Polecenie” | Przycisk w pasku narzędzi otwiera pole na własne słowa i cztery gotowe polecenia: skróć do 2 stron, usuń najstarsze role, ułóż punkty według wymagań klienta, ujednolić formę zdań |
| Plan zmian | Panel z operacjami i polami wyboru: usuń punkty, przeredaguj, połącz, zmień kolejność, usuń stanowisko, usuń sekcję. Przy każdej: miejsce w CV, treść „było / będzie”, zdanie asystenta, „Pokaż w CV” |
| Podgląd na kartce | Przekreślone to, co zniknie; nowa treść pod zmienianym wierszem; numer nowego miejsca przy przestawianych punktach. Do decyzji kartka jest tylko do odczytu |
| Kontrola | Serwer wypuszcza tylko operacje, które nie ruszają układu szablonu i nie dopisują liczb, dat, nazw ani wymagań; panel mówi, ile propozycji odrzucił. Przeredagowanie z nowymi słowami (których kontrola nie ocenia) nie jest zaznaczone i pokazuje te słowa |
| Wymagania klienta | Operacja, po której wymaganie rekrutacji znika z całego CV, ma ostrzeżenie i nie jest zaznaczona |
| Zastosowanie | „Zastosuj zaznaczone (N)” to jedna zmiana — całość cofa jedno „Cofnij”. Na zatwierdzonym CV nowy szkic powstaje dopiero wtedy |

Backend: trasa `POST /api/pipeline/stages/{id}/cv-ai/command`, klucz AI
`cv_editor_command` (F31), migracja `0434_cv_editor_command_ai_key` z lustrem
w `entrypoint.sh` (sama wartość enumu i wiersz ustawień — bez zmian tabel).

## PL→EN — do decyzji Artura

Makieta zakładała dwie wersje językowe obok siebie i „Przenieś 3 zmiany do EN”.
Model danych wygląda inaczej (odczyt kodu + produkcja, same liczby):

- Etap rekrutacji trzyma **jedno CV w jednym języku**. Druga wersja to osobny
  dokument generatora z własnym szkicem, zatwierdzeniem i historią; z pierwszą
  łączy go tylko zadanie generatora.
- Wersja EN powstaje drugim wywołaniem generatora ze źródeł, nie tłumaczeniem
  polskiej — nie jest wyrównana wiersz w wiersz. Nie ma też zapisanej bazy do
  policzenia „co zmieniło się w PL”.
- Produkcja, 30 dni do 13.10.2026: 699 zadań generatora, **18 z drugą wersją
  językową (2,6%)**; z 65 CV etapów **2 mają odpowiednik w drugim języku (3%)**.
  Angielskie CV są częste (369 dokumentów EN wobec 353 PL), ale jako jedyna
  wersja — a polecenie i AI na zaznaczeniu działają na nich tak samo.

| Opcja | Co daje | Koszt |
|---|---|---|
| A. Nie robić (rekomendacja) | Nic nie tracimy dla 97% CV; para PL+EN nadal powstaje w generatorze („Obie”) | Poprawki w parze trzeba nanieść w obu dokumentach ręcznie albo wygenerować EN ponownie |
| B. „Utwórz wersję EN z tego CV” | Tłumaczenie całego poprawionego CV blok po bloku do NOWEGO dokumentu, z tą samą kontrolą co „Na angielski” | Osobny PR: nowy dokument generatora, etykiety szablonu po angielsku, osobne zatwierdzenie; nie synchronizuje późniejszych zmian |
| C. Pełna synchronizacja par | Zgodnie z makietą | Wymaga zmian w modelu (wspólna baza zmian, wyrównanie bloków, dwa zatwierdzenia naraz, pakiet) — kilka PR-ów dla 3% przypadków |

## Decyzje przyjęte domyślnie (do wiadomości Artura)

| Sprawa | Przyjęte | Dlaczego |
|---|---|---|
| Model | Sonnet 5 (zapas Haiku), osobny klucz `cv_editor_command` | Ten sam autor co AI na zaznaczeniu; osobny klucz, bo jedno wywołanie czyta całe CV i kosztuje wielokrotnie więcej — widać to wtedy osobno w zużyciu AI |
| „Wersja anonimowa” z makiety | Pominięta | Zamiana nazwy firmy na opis branży dopisuje treść, której kontrola nie przepuści; generator ma tryb „blind” |
| „Usuń role sprzed 2015” | Jako „Usuń najstarsze role” | Sztywny rok w nazwie zestarzałby się; polecenie własnymi słowami przyjmie dowolny |
| Miniatury stron („Teraz · 3 strony”) | Zamiast nich „krótsze o N%” | Edytor nie zna podziału na strony; liczba stron byłaby zgadywana |
| Operacja gubiąca wymaganie klienta | Niezaznaczona, z ostrzeżeniem | Usunięcie jedynego miejsca z wymaganiem ma być świadome |
| Kartka w trakcie planu | Tylko do odczytu | Plan odnosi się do treści z chwili zamówienia |
| Lista technologii, stanowisko, firma | Poza poleceniem (znikają tylko z całą rolą) | Mają zapis, z którego serwer składa Word |
| Edytor wyniku generatora | Bez polecenia | Nie ma tam rekrutacji ani wymagań do sprawdzenia |
| Limit | 6 poleceń na minutę, CV do 400 wierszy i 60 tys. znaków | Jedno wywołanie czyta całe CV |

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Kontrola planu | zielone lokalnie | `tests/test_cv_command_ai.py` (45): każdy rodzaj operacji, układ szablonu, nowe fakty i nowe słowa, jeden wiersz w jednej operacji, znikające wymaganie (narastająco), CV bez znaczników, złe kształty, koszt |
| Wywołanie modelu | zielone lokalnie | model poza transakcją, awaria = „niedostępne”, wyłącznik i brak klucza bez wywołania, polecenie i wiersze nie rozrywają promptu, gotowe polecenie z kodu |
| Trasa | schemat lokalnie, reszta w CI | granice żądania bez bazy; przebieg z bazą (brak zapisu w szkicu, ślad bez treści, 404, 422) w `tests/test_cv_editor_ai_route.py` |
| Klucz AI, migracja, uprawnienia | zielone lokalnie | rejestr modeli, ustawienia, lustro enumu, `authz_golden/cv_editor_ai.json` (ten sam wzorzec co `cv-ai/selection`), jedna głowa Alembica |
| Logika edytora | zielone lokalnie | `lib/__tests__/cv-editor-command.test.ts` (14) na prawdziwym edytorze: wiersze, każda operacja, kilka naraz, jedno „Cofnij”, plan dla zmienionej treści, kolejność przy pustym punkcie i dwóch listach |
| Pasek i panel | zielone lokalnie | `CvEditorPlan.test.tsx` (15), sprawdzone też celowym zepsuciem kodu (5 testów pada) |
| Okno i harness | zielone lokalnie | testy okna, `cv-editor-harness.test.tsx` (16, w tym 4 scenariusze polecenia, zero sieci) |
| Przeglądarka | przeklikane ze zrzutami | harness w Chromium (skrypt Playwright) przy 1280×720, 768×1024 i 390×844: pasek, panel i „Zastosuj zaznaczone” w oknie, kartka tylko do odczytu w trakcie planu, podgląd na kartce, zastosowanie, zmiana kolejności, operacja z ostrzeżeniem, Escape w panelu; zero błędów strony |

Z przeklikania poprawione: nowa treść w podglądzie połączenia była przekreślona
(dziedziczyła styl usuwanego wiersza), a na telefonie plakietka „Podgląd zmian”
ściskała nagłówek okna.

## Przeglądy przed PR-em (13.10.2026)

Trzy niezależne przeglądy (bezpieczeństwo, Python, TypeScript), tylko blokery.
Każda poprawka ma test, który przed nią padał.

| Przegląd | Znalezisko | Poprawka |
|---|---|---|
| Bezpieczeństwo | Kontrola faktów nie łapie twierdzeń pisanych małą literą („prowadził zespół”, „magister informatyki”), a panel pisał „żadna zmiana nie dopisuje faktów” i zaznaczał wszystko z góry | Operacja niesie listę nowych słów; taka nie jest zaznaczona, panel pokazuje słowa i mówi dokładnie, co kontrola sprawdza |
| Bezpieczeństwo | W CV bez znaczników stanowisko, firma i etykieta przychodziły jako zwykły tekst i dały się usunąć albo przepisać | Sekcja doświadczenia bez numerów stanowisk nie jest ruszana wcale |
| Python | Wymaganie w dwóch miejscach, usuwane dwiema operacjami: żadna nie ostrzegała i obie były zaznaczone | Ostrzeżenie liczone narastająco — dostaje je operacja, która zabiera ostatnie miejsce |
| Python | Pogrubienie w środku nazwy („Spring **Boot**”) ukrywało albo wymyślało ostrzeżenie | Porównanie bez znaczników |
| Python | `true` jako numer wiersza usuwało sekcję nr 1 | Wartość logiczna nie jest numerem |
| TypeScript | Zmiana kolejności punktów stojących w dwóch listach była pomijana po cichu, a komunikat mówił o sukcesie albo o „zmienionym CV” | Taka operacja nie trafia do planu; pusty punkt na liście nie blokuje zmiany kolejności |
| TypeScript | Po „Zastosuj” klawiatura nie wracała do kartki — Ctrl+Z nie cofał | Kartka jest odblokowana przed ustawieniem fokusu |
| TypeScript | Escape w trakcie liczenia planu zamykał (i zapisywał) cały edytor | Dopóki plan jest otwarty, Escape nie zamyka edytora |

Naniesione przy okazji: pusty punkt nie liczy się jako treść roli, klauzula zgody
nie jest wpisywana ani ruszana przez plan, CV bez stanowisk zachowuje co najmniej
jedną sekcję, znaki niewidoczne z CV nie idą do modelu, „Pokaż w CV” na wąskim
ekranie przewija po pokazaniu kartki.

Znane ograniczenia (nie blokują): lista nowych słów to porównanie rdzeni — może
wskazać synonim albo przepuścić słowo o tym samym początku co inne ze źródła;
przeredagowanie gubi kursywę i odnośniki (edytor i Word znają tylko pogrubienie);
ta sama kontrola faktów działa w „AI na zaznaczeniu” (PR 3), gdzie rekruter
czyta jedną propozycję „było / będzie” naraz.

## Niepotwierdzone

- **Jakość planów prawdziwego modelu** — testy podmieniają model. Po wdrożeniu:
  wpisy `cv_command_ai` w `activities` (`details`: gotowe polecenie, liczba
  operacji i odrzuconych).
- **Edytor na produkcji po zalogowaniu** — przeklikany jest harness.
- **Koszt jednego polecenia** na prawdziwych CV (zużycie AI pod kluczem
  `cv_editor_command`).

## Świadomie poza zakresem

- PL→EN (wyżej), historia wersji i powrót pliku Word (PR 5).
- Polecenie nie dopisuje treści z oryginalnego CV ani z notatek — do tego jest
  „Rozwiń z oryginału” na zaznaczeniu i poprawki z panelu „Do poprawy”.
