# NEXUS — LinkedIn: materiały do Chrome Web Store

Stan przygotowania: 28.10.2026. Materiały opisują kod w `extension/`.
Nie są potwierdzeniem publikacji w sklepie ani testu na żywym Recruiterze.

## Pola oferty

Nazwa: **NEXUS — LinkedIn**

Język: **polski**. Kategoria: **Productivity / Workflow & Planning**
(wybrać odpowiadającą jej dostępną kategorię w aktualnej konsoli).

Widoczność: **Unlisted / Niepubliczna**. Dostęp przez link do oferty;
funkcje wymagają konta NEXUS i odpowiednich uprawnień rekrutera.

Opis krótki (z manifestu):

> Panel boczny NEXUSA na LinkedInie: sprawdź osobę w bazie, dodaj ją do rekrutacji i zapisz kontakt.

Opis szczegółowy do wklejenia:

```text
NEXUS — LinkedIn to panel boczny Chrome dla rekruterów korzystających z NEXUSA.
Na otwartej stronie LinkedIna sprawdzisz, czy osoba jest już w bazie, kto ją
prowadzi i w jakich rekrutacjach uczestniczy.

W panelu możesz:
• sprawdzić osobę w NEXUSIE i zobaczyć historię kontaktów zespołu;
• przejrzeć ostrzeżenia off-limits, status kontraktora i status zgody RODO;
• sprawdzić odczytane dane i poprawić je przed zapisaniem osoby do bazy;
• dodać osobę do wybranych rekrutacji;
• zapisać notatkę, kontakt i przypomnienie;
• przygotować i edytować szkic wiadomości dla wybranej rekrutacji;
• po kliknięciu sprawdzić jedną otwartą stronę wyników wyszukiwania.

Odczyt profilu następuje przy otwarciu panelu, po zmianie aktywnej karty lub
adresu obsługiwanej strony przy otwartym panelu oraz na żądanie użytkownika.
Wyniki wyszukiwania są odczytywane po kliknięciu „Sprawdź tę stronę”.
Wtyczka odczytuje dane dostępne w otwartej stronie i przekazuje dane profilu
do NEXUSA, aby sprawdzić bazę i podpowiedzieć rekrutacje. Nie przegląda
samodzielnie kolejnych profili i nie wysyła wiadomości ani zaproszeń.
Tekst wiadomości kopiujesz, wklejasz i wysyłasz samodzielnie.

Do korzystania potrzebne są Chrome 116 lub nowszy, konto NEXUS i uprawnienia
rekrutera. Połączenie odbywa się przez stronę logowania NEXUSA; wtyczka nie
prosi o hasło do NEXUSA ani do LinkedIna.

Wtyczka obsługuje profile publiczne i wyniki wyszukiwania osób na LinkedInie.
Czytnik LinkedIn Recruiter jest dostępny, ale jego zgodność z aktualnym
interfejsem wymaga jeszcze weryfikacji na koncie z licencją Recruiter.
Układ i dostępność odczytywanych pól mogą zależeć od wersji strony LinkedIna.

NEXUS — LinkedIn jest narzędziem NEXUSA. Nie jest produktem LinkedIn ani nie
jest sponsorowany lub zatwierdzony przez LinkedIn.
```

Strona produktu: `https://nexus.b2bnetwork.pl`

Polityka prywatności: `https://nexus.b2bnetwork.pl/wtyczka/prywatnosc`

Pomoc: administrator NEXUSA w organizacji użytkownika; jako adres URL pomocy
można wskazać tę samą stronę polityki, która opisuje kontakt z administratorem.
Nie wpisywać wymyślonego adresu e-mail. Pole e-mail wydawcy bierze dane
zweryfikowanego konta Google obsługującego publikację.

## Single purpose — jeden cel

```text
Ułatwienie rekruterom NEXUSA obsługi osoby widocznej na LinkedInie: sprawdzenie
jej w bazie NEXUSA, przegląd kontekstu rekrutacji i kontaktów oraz zapisanie
danych i działań rekrutacyjnych z panelu bocznego.
```

## Uzasadnienie uprawnień

Teksty odpowiadają manifestowi po zawężeniu dostępu do jawnych hostów NEXUSA.

| Uprawnienie | Uzasadnienie do formularza |
| --- | --- |
| `sidePanel` | Wyświetla panel NEXUSA obok otwartej strony LinkedIna. Wszystkie funkcje rekrutacyjne wtyczki znajdują się w panelu bocznym. |
| `storage` | Zapisuje lokalnie klucz połączenia z NEXUSEM, adres serwera i czas połączenia. Użytkownik może usunąć lokalne połączenie przyciskiem „Odłącz”. Dane nie są synchronizowane przez chrome.storage.sync. |
| `scripting` | Odczytuje tekst i strukturę obsługiwanej, aktywnej strony LinkedIna na potrzeby widocznego panelu. Profile mogą zostać przewinięte, aby doładować sekcje, po czym pozycja jest przywracana. Brak skryptów stale działających na stronach i brak automatycznego przechodzenia do kolejnych profili. |
| `https://www.linkedin.com/*` | Pozwala odczytać dane z otwartego profilu lub pojedynczej strony wyników, także z widoków Recruitera na tym hoście. Wtyczka nie wywołuje wewnętrznego API LinkedIna i nie wysyła tam wiadomości. |
| `https://nexus.b2bnetwork.pl/*` | Oficjalny serwer NEXUSA, strona połączenia i obsługa dozwolonego adresu API, jeśli jest ustawiony na ten host. |
| `https://api.nexus.b2bnetwork.pl/*` | Jawnie dozwolony alternatywny host API NEXUSA w konfiguracji połączenia. Obsługuje ten sam kontrakt /api/extension/*. |
| `https://api.nexus.dynaminds.pl/*` | API NEXUSA: uwierzytelnienie kluczem wtyczki, sprawdzenie osoby, rekrutacje, zapis danych, notatek i kontaktów oraz przygotowanie szkicu wiadomości. |
| `http://localhost:8100/*` | Istniejący, wybierany przez użytkownika tryb „Staging na laptopie” łączy się wyłącznie z lokalnym API na porcie 8100. Umożliwia testowanie bez zapisów w produkcji. |

`externally_connectable` przyjmuje wiadomości wyłącznie z frontu NEXUSA
oraz lokalnych frontów na portach 3100/3101. Służy do przekazania klucza po
zalogowaniu w NEXUSIE. Nadawca, format klucza i host API są walidowane.

Remote code: **No, I am not using remote code.** Wszystkie skrypty są w ZIP;
API zwraca dane JSON i tekst, które nie są wykonywane jako kod.

## Privacy practices — zakres danych

Zaznaczyć poniższe kategorie zgodnie z faktycznym zakresem funkcji. Kategorie
obejmują także dane przetwarzane lokalnie lub otrzymywane z NEXUSA.

| Kategoria konsoli | Wybór | Faktyczny zakres |
| --- | --- | --- |
| Personally identifiable information | Tak | Imię i nazwisko, publiczny URL profilu, stanowisko, firma i historia zawodowa; tożsamość zalogowanego rekrutera. |
| Health information | Nie | Brak funkcji zbierania danych medycznych. |
| Financial and payment information | Tak | Panel może wyświetlać stawkę wynagrodzenia kandydata z NEXUSA. Nie obsługuje kart, płatności ani kont bankowych. |
| Authentication information | Tak | Klucz API wtyczki w chrome.storage.local oraz nagłówku do API NEXUSA; bez odczytywania haseł i ciasteczek LinkedIna. |
| Personal communications | Tak | Szkice wiadomości oraz notatki i historia kontaktów z NEXUSA; tekst zapisuje się po działaniu rekrutera. Brak odczytu skrzynki LinkedIna. |
| Location | Tak | Miejscowość/region podane w profilu zawodowym oraz informacje lokalizacyjne w danych NEXUSA; brak GPS. |
| Web history | Tak | Adres konkretnego profilu/strony LinkedIna obsługiwanej w otwartym panelu; brak zbierania ogólnej historii przeglądarki. |
| User activity | Tak | Licznik odczytów i rejestr działań w NEXUSIE związanych z funkcją rekrutacyjną. Brak rejestracji klawiszy, ruchów myszy i ogólnego zachowania w przeglądarce. |
| Website content | Tak | Tekst profilu, doświadczenie, umiejętności i dane z widocznej strony wyników; opcjonalny PDF dołączony przez rekrutera. |

Zewnętrzne przetwarzanie: dane profilu są przekazywane do API NEXUSA.
Dopasowanie do rekrutacji i szkic wiadomości mogą korzystać z dostawców AI
skonfigurowanych w NEXUSIE. Nie deklarować, że wszystkie dane zostają lokalnie
ani że dane nigdy nie trafiają do podmiotów przetwarzających.

Trzy certyfikacje formularza odpowiadają zamierzonemu użyciu produktu:
brak sprzedaży/transferu danych poza dozwolonymi przypadkami; użycie wyłącznie
do wskazanego celu; brak użycia do oceny kredytowej i pożyczek. Nie zastępują
one polityki prywatności ani rzeczywistej konfiguracji dostawców NEXUSA.

## Instrukcja dla recenzenta

```text
This extension requires an authorized NEXUS recruiter account. It is distributed
as Unlisted for the organization's team. It does not support consumer self-signup.

1. Install the extension and open its side panel using the toolbar action.
2. Select "Zaloguj przez NEXUS" and authenticate on nexus.b2bnetwork.pl.
3. Return to a LinkedIn profile you are authorized to view and open the panel.
4. The panel checks the profile in NEXUS and shows the person's recruitment context.
5. For search-result pages, click "Sprawdź tę stronę" to check one visible page.
6. Candidate creation, notes, contacts and assignments require explicit button clicks.
7. Message text is only drafted/copied. Sending on LinkedIn remains manual.

The store listing screenshots render the actual panel components using fictional
fixture data. They are not screenshots of a real LinkedIn Recruiter session.
```

Jeżeli konsola wymaga danych testowych, dostarczyć je wyłącznie przez prywatne
pole instrukcji recenzenta. Ten plik i repozytorium nie zawierają danych logowania.

## ZIP, ikona i zrzuty

```sh
cd extension
npm ci --ignore-scripts
npm run pack
# dist/nexus-linkedin-1.0.0.zip i dist/nexus-linkedin-1.0.0.zip.sha256
```

Pakowanie wymaga zielonych testów; bez zależności kończy się błędem. Archiwum
zawiera wyłącznie manifest, ikony i kod `src/`, bez testów i materiałów sklepu.

Ikona 128×128: `extension/icons/icon-128.png`.

```sh
node extension/scripts/store-screenshots.mjs
# extension/dist/webstore/nexus-linkedin-{person,add,message}-1280x800.png
```

Generator używa istniejącej zależności Playwright z frontendu, lokalnego serwera
i aktualnych komponentów panelu. Można podać `PLAYWRIGHT_MODULE_PATH` oraz
`PLAYWRIGHT_EXECUTABLE_PATH`, jeśli zależność lub Chromium są w innym miejscu.
PNG mają 1280×800, 24-bit RGB, bez przezroczystości. `screenshots.json`
zawiera sumy SHA-256 i oznaczenie danych fikcyjnych. Zrzuty **nie potwierdzają
działania na żywym Recruiterze**. Wszystkie trzy trzeba obejrzeć przed uploadem.

## Wymagania sprawdzone w dokumentacji Google

- [Opis i grafiki oferty](https://developer.chrome.com/docs/webstore/cws-dashboard-listing): ikona 128×128 i co najmniej jeden zrzut 1280×800; do pięciu zrzutów.
- [Pola prywatności](https://developer.chrome.com/docs/webstore/cws-dashboard-privacy): jeden cel, uzasadnienia uprawnień, remote code i kategorie danych.
- [Zasady danych i minimalnych uprawnień](https://developer.chrome.com/docs/webstore/program-policies/user-data-faq): zakres obejmuje również lokalne przetwarzanie; polityka opisuje zbieranie, użycie i ujawnianie danych.
- [Rejestracja wydawcy](https://developer.chrome.com/docs/webstore/register/): konto dewelopera, akceptacja warunków i jednorazowa opłata. Kwotę i stan konta potwierdza aktualna konsola.
