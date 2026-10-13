# Lista rekrutacji pamięta ostatnie filtry

Data: 13.10.2026 · Bez migracji · Reguły: `docs/claude/rekrutacja-tablica/lista-rekrutacji-pamieta-ostatnie-filtry.md`

## Po co

Zgłoszenie z 13.10.2026: po wyjściu z listy „Rekrutacje” i powrocie filtry
trzeba było ustawiać od nowa. Filtry żyły wyłącznie w adresie strony, a menu
„Rekrutacje”, okruszek w górnym pasku i kafel pulpitu prowadzą na goły `/jobs`,
który lista traktowała jak czysty start (reguła z audytu rundy 10). „Wstecz”
przeglądarki działało, dopóki ktoś nie kliknął „Rekrutacje” w menu, będąc już
na liście — wtedy adres zostawał goły i „Wstecz” też gubiło filtry.

## Co się zmieniło

| Wejście na listę | Co widać | Pamięć |
|---|---|---|
| goły `/jobs`, osoba ma zapamiętany widok | ostatni widok, już w pierwszym zapytaniu | bez zmian |
| goły `/jobs`, brak wpisu | domyślny widok roli (jak dotąd) | — |
| adres z parametrami listy (pulpit, powiadomienie, „Wstecz”) | widok z linku | nietknięta do pierwszej zmiany osoby |
| osoba zmienia zakres, sortowanie, stan requestu, filtr paska albo przełącznik | — | to, co na ekranie |
| „Wyczyść” | domyślne filtry, sortowanie zostaje | to, co na ekranie; widok domyślny kasuje wpis |
| „Rekrutacje” w menu przy otwartej liście | filtry zostają | bez zmian |
| link z parametrami kliknięty przy otwartej liście | widok z linku (wcześniej zostawał stary stan) | nietknięta |
| inna osoba w tej samej przeglądarce, „podgląd jako” | jej własny widok albo domyślny | osobny wpis per osoba |

- Pamiętane: zakres, sortowanie, stan requestu, filtry paska, trzy przełączniki.
  Nie: tekst z wyszukiwarki i numer strony.
- Wpis jest per osoba, w przeglądarce, i przeżywa wylogowanie. Zawiera same
  klucze i identyfikatory filtrów.
- Kafel „Moje rekrutacje” na pulpicie prowadzi teraz do `/jobs?mine=1`: goły
  adres znaczy „ostatni widok”, a kafel ma otwierać moje rekrutacje.
- Link z jawnym zakresem równym domyślnemu roli (np. `/jobs?mine=1`
  u rekrutera) trzyma zakres w adresie, dopóki osoba niczego nie zmieni —
  dzięki temu „Wstecz” z rekrutacji wraca do widoku z linku, a nie do pamięci.
- Przewodnik Jarvisa dla listy mówi, że lista otwiera się z ostatnimi filtrami
  i jak z nich wyjść.

## Czego świadomie nie zmieniłem

- **Pasek adresu po kliknięciu „Rekrutacje” na liście otwartej z gołego
  adresu** bywa goły do następnej zmiany filtra. Filtry stoją na ekranie,
  a „Wstecz” i F5 oddają ten sam widok z pamięci. Wyrównanie adresu wymagałoby
  zapisów widocznych dla routera, które przerywają nawigację w toku (klik
  w wiersz tuż po wpisaniu tekstu w wyszukiwarkę).
- **Ten sam link kliknięty drugi raz** po własnych zmianach nie jest stosowany
  ponownie — router nie widzi nawigacji.
- **Bez komunikatu „przywrócono filtry”**: aktywne filtry są wyróżnione,
  „Wyczyść” stoi w pasku.
- **Listy Klienci i Kontrakty** trzymają filtry tak jak dotąd, tylko w adresie.

## Weryfikacja

- Test odtwarzający zgłoszenie (filtr, wyjście, powrót gołym adresem) padał
  przed zmianą: 11 z 14 przypadków `JobsListV2Memory.test.tsx` było czerwonych.
  Po zmianie plik ma 15 przypadków i wszystkie przechodzą.
- Vitest na plikach listy, pamięci, adresu, sesji, kafla pulpitu, inwentarza
  funkcji i strażnikach źródeł: 14 plików, 524 testy. `tsc --noEmit` bez
  błędów, ESLint bez błędów, strażnik nieosiągalnych modułów bez nowych pozycji.
- Niezależny przegląd kodu nie znalazł niczego blokującego. Po nim doszło
  jedno utwardzenie: zmiana osoby razem z nawigacją na goły adres też nie
  zapisuje jej cudzego widoku (przypadek nieosiągalny dziś, bo każda zmiana
  osoby przeładowuje stronę).
- Przeklikanie harnessu `/preview/jobs-list-v3` skryptem Playwright na
  lokalnym serwerze, okno 1280 × 720, prawdziwy router: powrót gołym adresem
  oddaje „Otwarte” z wierszami; link `?mine=1` pokazuje „Moje”, zostaje
  w adresie i wraca po „Wstecz”; po kliknięciu menu na otwartej liście filtr
  „Wszystkie” zostaje i wraca po wyjściu i „Wstecz”; „Wyczyść” kasuje wpis.
  Wpis prawdziwej osoby o id harnessu pozostał nietknięty.
- Te same trzy scenariusze są w `e2e/responsive-preview.spec.ts` i biegną na
  zbudowanej aplikacji w kolejce merge'ów.

## Do sprawdzenia po wdrożeniu

Na zalogowanej produkcji: ustaw filtry na liście, otwórz rekrutację, kliknij
„Rekrutacje” w menu — filtry mają stać. Sesja nie miała zalogowanej
przeglądarki, więc tego kroku nie wykonała.
