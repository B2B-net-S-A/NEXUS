# Nowa firma z NIP-u: wyszukiwarka ⌘K i przycisk Jarvisa (decyzja Artura 23.11.2026)
<!-- indeks: prośba Sprzedaży „Jarvis zakłada firmę z NIP-u”, wariant B (A + karta Jarvisa), C odrzucony, CommandPaletteV2 „Załóż firmę z NIP …”, nipFromQuery, zła suma kontrolna, /sales/companies?nowa=<NIP>, CompanyFormDialog initialNip, nameWithoutLegalForm, „Dopisz NIP do tej karty”, registry-nip-taken, KRS i REGON z rejestru, new_sales_company (link, sales_edit), 4,7% kart z NIP-em, 58 par dubli z pełną formą prawną -->

Prośba handlowca z 23.11.2026: Jarvis zakłada nową firmę z NIP-u po sprawdzeniu,
że NIP nie jest już użyty. Makiety: https://claude.ai/artifact/XbSgRKCE2dpFLSr9nyrU9R.
Artur wybrał wariant B: wyszukiwarka ⌘K i przycisk Jarvisa prowadzą do tego samego
okna, a zapis robi człowiek. Wariant C (Jarvis zapisuje sam z „Cofnij”) odpadł.

## Dlaczego nie „sprawdź NIP i załóż”

Kopia produkcji z 23.11: NIP ma 570 z 12 256 aktywnych kart (4,7%). Brak karty
z NIP-em zwykle nie znaczy, że firmy nie ma — CD PROJEKT RED nie ma po NIP-ie, ale
karta „CD PROJEKT RED” istnieje bez NIP-u. Rejestry podają nazwę z pełną formą
prawną („… SPÓŁKA AKCYJNA”), a `normalize_company_name` jej nie zdejmuje, więc
kontrola dubli (`/duplicates`, `/identity`, 409 przy zapisie) nie łączyła takiej
nazwy z kartą. 58 par kart już tak powstało. Do tego „CD PROJEKT S.A” i „CD PROJEKT
RED” to dwie spółki tej samej marki — rozstrzyga człowiek, nie model.

## Jak działa

- **⌘K** (`CommandPaletteV2`): awaria wyszukiwania firm chowa „Załóż”, bo nie wiadomo,
  czy karta jest. Zapytanie, które jest samym polskim NIP-em
  (`nipFromQuery`: kreski, spacje, prefiks PL), u osoby z `sales_edit`, gdy wśród
  wyników nie ma karty Sprzedaży → grupa „Sprzedaż” z „Załóż firmę z NIP …”
  (`/sales/companies?nowa=<NIP>`). Zła suma kontrolna → nieaktywna pozycja
  „ma złą sumę kontrolną — sprawdź cyfry”, bez zapytania do rejestru.
- **Jarvis**: narzędzie `new_sales_company` (tier `link`, `any_permission=sales_edit`)
  daje przycisk „Nowa firma w Sprzedaży” z tym samym adresem. Niczego nie zapisuje;
  NIP bez 10 cyfr albo ze złą sumą wraca do modelu jako błąd. Jarvis nie czyta
  kartoteki Sprzedaży, więc sprawdzenie robi okno.
- **Okno „Nowa firma”** z `initialNip` (`CompaniesList` czyta `?nowa=`):
  - od razu `GET /api/sales/companies/registry` (jedno zapytanie na otwarcie);
    nazwa bez formy prawnej (`nameWithoutLegalForm`), pełna w „Pełnej nazwie
    prawnej”, KRS i REGON idą przy zapisie nowej karty, dopóki NIP się nie zmieni;
  - karta z dokładnie tym NIP-em (`GET /api/sales/companies?q=<NIP>`, porównanie
    całego numeru) → ostrzeżenie z linkiem, bez dopisywania;
  - NIP wolny, a `/identity` zwraca kartę o tej samej nazwie i `nip: null` → „Dopisz
    NIP do tej karty”; karta z innym NIP-em to inna spółka tej samej marki, jej numeru
    okno nie rusza (PATCH samego NIP-u: resztę uzupełnia sprawdzenie rejestru po zapisie,
    które nie nadpisuje pól człowieka, `dane-firm-z-rejestrow.md`). Nowa karta
    wtedy tylko przyciskiem „To inna spółka — dodaj nową kartę”.
- Ręczne „Nowa firma” → „Pobierz z rejestru” też wpisuje nazwę bez formy prawnej,
  więc kontrola dubli przy zapisie łapie kartę o tej nazwie.

## Czego to nie robi

- Karty zapisane z pełną formą prawną w nazwie (331 na kopii z 23.11) dalej nie
  łączą się z nazwą bez formy. Poprawka `normalize_company_name` zmienia
  `sales_companies.normalized_name` i dopasowania „Kogo znamy”, więc idzie osobno,
  z przeliczeniem kolumny.
- Staging nie wychodzi do rejestrów: okno na stagingu pokaże błąd pobierania,
  a próbę robi się z zaślepioną odpowiedzią albo na produkcji.
