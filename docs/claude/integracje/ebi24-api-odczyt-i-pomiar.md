# EBI24: API tylko do odczytu i pomiar przed integracją

Decyzja Artura z 02.11.2026: najpierw odczyt i pomiar na prawdziwym koncie, wystawianie
faktur później. Faktury klientom firma wystawia w EBI24. Podręcznik: „EBI24 Klient API v1”,
wersja 1.9.1 (plik od dostawcy, poza repo).

## Co jest w kodzie

- `app/services/ebi24/environment.py`: `EBI24_MODE=off|uat|prod` i cztery pola dostępowe.
  Domyślnie `off`; brak pola albo klucz inny niż 32 bajty w base64 wyłącza integrację.
- `app/services/ebi24/client.py`: podpis i `CREDENTIALS` sprawdzone wektorem z podręcznika,
  jedno żądanie naraz co sekundę, rosnący znacznik, 429 z `Retry-After`, ponawianie błędów sieci.
  `READ_ACTIONS` to jedyne akcje, które klient wyśle; `bucket/create` celowo tam nie ma,
  bo faktura po utworzeniu idzie w obieg księgowy, a ponowienie żądania daje duplikat.
- `scripts/ebi24_probe.py`: same liczniki, bez nazw, NIP-ów, numerów, kwot i identyfikatorów.

Nic innego tego kodu nie używa: bez pętli w lifespanie, tras API i ekranów.

## Uruchomienie sondy

1. Finanse (właściciel konta EBI24) tworzą osobnego użytkownika API tylko do odczytu i generują
   dane w Ustawienia → Moje dane → API. Klucze pokazują się raz, razem z końcowym `=`.
2. Artur wpisuje je jako sekrety repo, a na produkcję idą wyłącznie workflow „Coolify set env”
   z `value_from_secret`. Nie przez czat ani mail: podręcznik mówi, że dają dostęp do danych konta.
3. Po wdrożeniu w oknie: `python -m scripts.ebi24_probe` w kontenerze backendu, z terminala.
   Wynik zapisany w logach Actions byłby publiczny, choć to same liczby.
4. `not_authorized` oznacza, że serwer (Hetzner, Niemcy) jest spoza listy zaufanych: pomoc EBI24
   dodaje adres IP lub konto. Podręcznik opisuje to dla serwerów spoza Polski.

## Co musi rozstrzygnąć pomiar

- **Kompletność:** faktura z KSeF jest w EBI24 dopiero po utworzeniu z dokumentu KSeF (ręcznie,
  regułą albo powiązaniem), więc nie zakładaj, że są wszystkie. Porównaj liczby z Finansami.
- **Status zapłaty:** `paid` ma sens tylko, jeśli Finanse naprawdę oznaczają w EBI24 zapłaty.
- **XML:** czy `getKsefData` daje plik, który czyta `services/hr/ksef/fa.py`.
- **Przyrost:** podręcznik nie opisuje filtra zakresu dat. Sonda próbuje `greaterOrEqual`
  na `_createdDate`; odmowa oznacza pytanie do dostawcy.

## Kolejność po pomiarze

1. Adapter `InvoiceSource` (`services/hr/ksef/source.py`): ten sam parser i dopasowanie do
   zamówień. Odczyt z EBI24 jest alternatywą dla tokenu KSeF, którego NEXUS wciąż nie ma.
2. `paid` i `paidDate` obok zapłat z wyciągu (`client_invoicing/payments.py`).
3. Wystawianie z „Do faktury” przez `bucket/create`, tylko na UAT. Blokady przed startem: NEXUS
   nie zna stawek VAT (`client_invoicing/export.py`), API nie ma klucza idempotencji, a podręcznik
   nie mówi, jak utworzona faktura trafia do KSeF.

## Czego podręcznik nie rozstrzyga

Serwer UAT (tabela: `test-api.ebi24.pl`, przykłady: `test.ebi24.pl`; 02.11 oba bez odpowiedzi
z laptopa), GET w przykładach a POST w zaleceniach, pola `COST_INVOICE`, oznaczanie zapłaty
przez API (brak), korekty przez `bucket/create`. Brak też webhooków: nowe dokumenty sprawdzamy
najwyżej co 5 minut, a duże pobrania robimy w godzinach 20:00–7:00.
