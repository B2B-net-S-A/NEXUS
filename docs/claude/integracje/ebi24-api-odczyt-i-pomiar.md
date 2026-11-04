# EBI24: API tylko do odczytu i pomiar przed integracją

Decyzja Artura z 02.11.2026: najpierw odczyt i pomiar na prawdziwym koncie, wystawianie
faktur później. Faktury klientom firma wystawia w EBI24. Źródła od dostawcy, poza repo:
podręcznik „EBI24 Klient API v1” 1.9.1, generator żądań `EBI24_API_generator.html` i odpowiedzi
na pytania z 03 i 04.11.2026.

## Co jest w kodzie

- `app/services/ebi24/environment.py`: `EBI24_MODE=off|uat|prod` i cztery pola dostępowe.
  Domyślnie `off`; brak pola albo klucz inny niż 32 bajty w base64 wyłącza integrację.
- `app/services/ebi24/client.py`: podpis i `CREDENTIALS` sprawdzone wektorem z podręcznika,
  jedno żądanie naraz co sekundę, rosnący znacznik, 429 z `Retry-After`, ponawianie błędów sieci.
  `READ_ACTIONS` to jedyne akcje, które klient wyśle; `bucket/create` celowo tam nie ma,
  bo ponowienie żądania daje duplikat, a kontrola duplikatów jest po naszej stronie.
- `scripts/ebi24_probe.py`: same liczniki, bez nazw, NIP-ów, numerów, kwot i identyfikatorów.

Nic innego tego kodu nie używa: bez pętli w lifespanie, tras API i ekranów.

## Uruchomienie sondy

UAT sprawdza połączenie i podpis, a liczby do decyzji daje dopiero PROD, bo tylko tam są
prawdziwe dokumenty.

1. Klucze: UAT przekazuje dostawca, na PROD Finanse (właściciel konta EBI24) tworzą osobnego
   użytkownika API tylko do odczytu i generują dane w Ustawienia → Moje dane → API. Klucze
   pokazują się raz, razem z końcowym `=`.
2. Artur wpisuje je jako sekrety repo, a na produkcję idą wyłącznie workflow „Coolify set env”
   z `value_from_secret`. Nie przez czat ani mail: dają pełny dostęp do danych konta.
3. Po wdrożeniu w oknie: `python -m scripts.ebi24_probe` w kontenerze backendu, z terminala.
   Wynik zapisany w logach Actions byłby publiczny, choć to same liczby.
4. UAT jest dostępny wyłącznie z zaufanych adresów, a dostawca otwiera go dla adresu serwera produkcji
   NEXUSA, więc brak odpowiedzi z laptopa nie jest awarią. Na PROD adresu nie zgłaszamy z wyprzedzeniem,
   bo dopuszczenie zależy od reputacji adresu. Gdy tam pojawi się `not_authorized` (strona
   „not authorized”), zgłoś to dostawcy: doda konto API do zaufanych.

Sonda nie potrzebuje generatora. Jeśli używasz go do porównania podpisu, pamiętaj, że przy każdym
wpisaniu zapisuje klucz i sekret w `localStorage` przeglądarki bez szyfrowania, także bez
zapisywania profilu. Prawdziwych kluczy nie wpisuj tam na współdzielonym komputerze.

## Co musi rozstrzygnąć pomiar

- **Kompletność:** faktura z KSeF jest w EBI24 dopiero po utworzeniu z dokumentu KSeF (ręcznie,
  regułą albo powiązaniem), więc nie zakładaj, że są wszystkie. Porównaj liczby z Finansami.
- **Status zapłaty:** `paid` ma sens tylko, jeśli Finanse naprawdę oznaczają w EBI24 zapłaty.
  Podręcznik nie wymienia `paidAmount` i `remainingAmount` w nagłówku listy, a dostawca potwierdza
  tylko ich odczyt. Sonda liczy je w nagłówkach (`header_paid_amount`, `header_remaining_amount`) i w
  próbce `bucket/getDocument` (`payment_sample`, także płatności częściowe). Gdy są tylko w danych
  dokumentu, adapter musi je czytać osobnym żądaniem na dokument, a limit to 60 żądań na minutę.
- **XML:** czy `getKsefData` daje plik, który czyta `services/hr/ksef/fa.py`.
- **Przyrost:** sonda wysyła `_createdDate` `greaterOrEqual` z datą sprzed 30 dni. `narrowed: false`
  oznacza, że filtr nie zawęził listy mimo formatu podanego przez dostawcę.

## Ustalenia z dostawcą (03 i 04.11.2026)

- **Adres UAT:** `test-api.ebi24.pl` z tabeli w podręczniku, nie `test.ebi24.pl` z przykładów.
  Dostawca obiecał środowisko testowe do końca tygodnia (odpowiedź z 04.11.2026).
- **Filtry dat:** `greaterThan`, `greaterOrEqual`, `lessThan`, `lessOrEqual` (pole `value`),
  `between` bez krańców i `betweenInclusive` z krańcami (pola `start`, `end`). Wartość to tekst
  `RRRR-MM-DD`, kryteria w formacie SmartClient AdvancedCriteria.
- **Pobieranie nowych dokumentów:** `greaterOrEqual` po `_createdDate`, od daty poprzedniego sprawdzenia
  włącznie, najwyżej co 5 minut. Filtr ma dokładność do dnia, więc te same dokumenty wracają w kolejnych
  odpytaniach i adapter musi je odsiewać po `_id`.
- **Kwoty** w żądaniach są liczbami całkowitymi w groszach, tak samo kwoty w nagłówkach i danych
  dokumentu. NEXUS trzyma kwoty w złotych, więc adapter i szablony przeliczają je jawnie.
- **`COST_INVOICE`:** te same pola nagłówka co faktura przychodowa.
- **Dokument z `bucket/create` to szablon faktury do edycji.** Wysyłka do KSeF jest akcją użytkownika
  w EBI24, więc NEXUS sam niczego do KSeF nie wyśle.
- **Duplikaty pilnujemy sami.** Gdy żądanie niesie komplet danych z numerem, odpowiedź ma o tym
  informować. Dokładne zachowanie sprawdź na UAT, bo opis dostawcy nie jest jednoznaczny.
- **Płatności:** API daje tylko odczyt (`paid`, `paidDate`, `paidAmount`, `remainingAmount`). Akcji
  oznaczania zapłaty jeszcze nie ma; dostawca da znać, gdy doda ją do instrukcji, i do tego czasu nie
  projektujemy zapisu. **Korekty** powstają w EBI24; korekty przez API wymagają spotkania z dostawcą.
- **Generator:** metoda POST, JSON w zwartej postaci, parametry adresu (np.
  `bucket/getBinaryDocument?disposition=inline`) wchodzą do podpisywanego ciągu.

## Kolejność po pomiarze

1. Adapter `InvoiceSource` (`services/hr/ksef/source.py`): ten sam parser i dopasowanie do
   zamówień, przyrost po `_createdDate` z odsiewaniem po `_id`. Odczyt z EBI24 jest alternatywą dla tokenu KSeF, którego
   NEXUS wciąż nie ma.
2. `paid` i `paidDate` obok zapłat z wyciągu (`client_invoicing/payments.py`).
3. Szablony faktur z „Do faktury” przez `bucket/create`, najpierw na UAT. Człowiek sprawdza szablon
   i wysyła go z EBI24. Przed startem: `taxRate` w wierszu jest wymagany, a NEXUS nie zna stawek VAT
   (`client_invoicing/export.py`), i potrzebny jest zapis w NEXUSIE, który szablon już powstał.

## Co jeszcze niepotwierdzone

Czy reputacja adresu serwera NEXUSA wystarczy na PROD i czy kontener wychodzi z adresu otwartego na
UAT: pokaże pierwszy bieg sondy. Webhooków nie ma, a duże pobrania robimy w godzinach 20:00–7:00.
