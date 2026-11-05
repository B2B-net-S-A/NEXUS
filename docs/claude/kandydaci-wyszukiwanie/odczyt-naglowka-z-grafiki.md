# Nazwisko i kontakt w grafice nagłówka CV: OCR pierwszej strony

05.11.2026 scalenie 21 profili pokazało PDF-y z nazwiskiem, mailem i telefonem
w obrazku nagłówka. Tekst w treści przekraczał 100 znaków, więc OCR nie ruszał,
a `raw_cv_text` nie miał nazwiska ani kontaktu. Reguła nagłówka brała wtedy nagłówek
sekcji, a wykrywanie duplikatów nie miało czego szukać.

## Reguła

`extract_cv_text` to `extract_text` plus OCR pierwszej strony, gdy PDF ma co najmniej
100 znaków tekstu i ani maila, ani telefonu. Krótszy tekst przeszedł już OCR całego pliku.

- Na początek tekstu idą linie, których nie ma w tekście PDF-a. Linia jest nowa, gdy
  co najmniej 60% jej słów nie ma w tekście. Sufit to 15 linii. Linia z telefonem zostaje
  zawsze, bo reszta jej słów bywa w tekście, a numer leży czasem w stopce.
- **Adresów z OCR nie dopisujemy** (`_OCR_ADDRESS`), także z `@` odczytaną jako litera.
  W kalibracji 190 CV 8 z 80 odczytanych adresów było błędnych, a przy porównaniu
  z profilem 24 z 118 było innych. Drugi odczyt w 300 dpi tego nie łapie: w 5 z 55
  par mylą się oba. Wiadomość do kandydata poszłaby do obcej osoby. Telefon: 2 z 179
  błędnych, więc telefon zostaje.
- Awaria OCR, limit czasu albo pamięci zostawia tekst PDF-a. Proces OCR jest osobny
  od odczytu tekstu, żeby przekroczenie limitu nie zabrało samego tekstu.
- Zamówienia, requesty i inne dokumenty zostają przy `extract_text`, bo ich tekst czytają
  reguły klientów.

## Tożsamość

Blok jest zwykłym tekstem CV, nie osobną ścieżką. Nazwa z niego idzie przez odczyt
modelu, `_apply_contact_fallbacks` (`_name_from_header`, #3057), listę częstych słów
(#3062) i `record_detected_identity`. Żadna ścieżka nie zapisuje nazwy z OCR wprost.

`_same_cv_text` uznaje krótszy tekst za ten sam, gdy jest końcem dłuższego i ma co
najmniej 100 znaków, bo starsze odczyty nie mają bloku na początku.

## Mail od modelu musi stać w tekście

Gdy CV ma nazwę, a nie ma adresu, model buduje adres z nazwy. Profil 9772: 3 z 3 odczytów
z pewnością 0,5–0,7, a bez nazwy 0 z 2. Tak samo dokłada domenę do resztki adresu z OCR
(„jan45©”). `_apply_contact_fallbacks` odrzuca adres, gdy nie ma go w tekście po sklejeniu
odstępów albo gdy w tekście nie ma jego części lokalnej i domeny. Część lokalna nie jest
sprawdzana po sklejeniu, bo sklejone „Anna Testowa” zawiera „annatestowa”. Reguła działa
na każdy odczyt, nie tylko z OCR.

Na kopii z 04.11 tę kontrolę oblewa 527 z 52 337 zapisanych odczytów (1%), a 299 takich
adresów stoi w profilach. Dla 175 z 527 w tekście nie ma nawet części lokalnej. Pozostałe 352
mają część lokalną bez domeny. Przyczyn nie rozbijano, więc mogą tam być prawdziwe adresy
z domeną zapisaną inaczej („gmail dot com”). Taki adres przy nowym odczycie zostaje w pliku,
a nie w profilu. Starych profili reguła nie zmienia.

## Pomiar

Kopia produkcji z 04.11, kod z gałęzi, 3 357 profili, z czego 2 448 z PDF-em. Zbiór to
profile bez maila i telefonu albo z nazwą `?` (886, PDF 614) oraz profile, których zapisany
tekst ma co najmniej 100 znaków i nie ma kontaktu.

| | PDF-y | mail lub telefon w tekście przed | po |
|---|---:|---:|---:|
| Profil bez kontaktu albo z nazwą `?` | 614 | 232 | 281 |
| Pozostałe z tekstem bez kontaktu | 1 834 | 112 | 332 |

- Nowy telefon: 269 plików. Zgodny z profilem 201, inny 15, profil bez telefonu 53.
- Ten sam numer u innego profilu: 45 plików, w tym 26 ze zbioru bez kontaktu. To kandydaci
  na ukryte duplikaty. `find_candidate_by_phone_and_name` łączy numer z nazwą.
- Ten sam numer w 7, 5, 3 i 3 plikach, a nazwiska w grupach: 2, 1, 2 i 2. To nie numer firmy.
- Bramka, odczyt modelem na 80 plikach z blokiem, tekst PDF-a kontra tekst z blokiem: 0 nowych
  `confirmed_mismatch`, 16 razy `inconclusive` → `confirmed_match`. Nazwa od modelu: 54 → 76.

## Koszt

Reguła trafia ok. 4,4% CV (2 881 z 64 938 głównych plików wg `raw_cv_text`, także Word).
Odczyt takiego PDF-a rośnie z ok. 0,2 s do 2,1 s (p95 6,3 s, najgorszy 23 s przy 8 równoległych
odczytach). Reszta plików nie płaci nic. Blok w medianie ma 2 linie i 32 znaki, p95 16 linii.

Filtr „strona ma obrazek” nie jest potrzebny: oszczędziłby 62% wywołań, ale zgubił 17 z 360
trafień i 15 ze 179 nowych nazw (tekst z zepsutą mapą czcionek), a wywołań jest mało.

## Czego ta reguła nie załatwia

- **Stare profile.** Działa na nowe odczyty. Bieg po starych profilach to osobna decyzja.
- **Word.** Obrazek w nagłówku DOCX zostaje nieczytany. Ze zbioru 886 profili bez kontaktu
  272 pliki nie są PDF-em.
- **Mail.** Profil dostaje telefon i nazwę, mail zostaje w pliku dla człowieka.
- **Pomiar w kontenerze backendu stagingu.** 10 procesów OCR przekroczyło limit 4 GB
  i zrestartowało wspólny backend (05.11.2026). Taki bieg idzie w jednorazowym kontenerze
  z własnym `--memory` i `--entrypoint python`.
