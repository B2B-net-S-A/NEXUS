# „Start u klienta: N z M ustalone” — ustalone to jawny wybór, nie wartość domyślna (20.11.2026)
<!-- indeks: `lib/client-start-readiness.ts` (`startReadiness`), `ClientStartReadiness` nad zakładką `?tab=wejscie`, „Klient nie wymaga dokumentów” = `clients.start_documents_not_required_at/_by` (0747, poza ORM), `PUT /api/start-documents/clients/{id}/not-required`, cztery pola, wzory protokołów poza licznikiem, licznik od 2 widocznych części -->

Decyzja Artura z 20.11.2026 (pytanie z liczbami w sesji, rekomendowane warianty
obu pytań). Makieta przebudowy Klientów (19.11.2026, ekran 7, wariant A)
pokazywała u PKO „2 z 5 ustalone”, ale obie „ustalone” pozycje były wartościami
domyślnymi: „Kto odbiera pierwszego dnia: menedżer z kontraktu” i „Wzory
protokołów: standard recepcji”. Licznik liczący domyślne wartości kłamie.

Stan produkcji 20.11.2026 (odczyt): 28 klientów z 512 kontraktami przed startem
i w trakcie; 0 pakietów klienta, 0 list dokumentów do startu, 0 sposobów
rozliczenia, sprzęt wskazany u 2 klientów (oba „od klienta”), 0 wgranych wzorów
protokołów w całym systemie, menedżer klienta wpisany w 20 z 512 kontraktów.

## Cztery pola i kiedy są ustalone

| Pole | Ustalone, gdy | Nieustalone |
|---|---|---|
| Dokumenty do startu | lista ma co najmniej jedną pozycję **albo** ktoś zaznaczył „Klient nie wymaga dokumentów” | pusta lista bez znacznika („brak listy”) |
| Sposób rozliczania | wybrany tryb (wiersz `client_settlement_rules`) | brak wyboru („nie wybrano”) |
| Sprzęt | „od nas” albo „od klienta” (`clients.equipment_provider`) | „Nie wiadomo” — też wtedy, gdy ktoś wybrał je ręcznie |
| Pierwszy dzień | wpisane „Gdzie” w pakiecie (po przycięciu spacji) | brak miejsca; „Kto odbiera” i „O której” nie wystarczają |

- **Wzory protokołów nie wchodzą do licznika.** W systemie nie ma żadnego
  wgranego wzoru, więc każdy klient ma „Standard recepcji” bez wyboru — pole
  byłoby ustalone zawsze albo nigdy. Gdy recepcja zacznie wgrywać wzory,
  wróć do Artura z liczbami, zanim dołożysz pole.
- **„Kto odbiera” to cecha kontraktu**, nie klienta: domyślnie menedżer
  z kontraktu, a ten jest wpisany w 20 z 512 kontraktów. Dlatego pierwszy dzień
  mierzy miejsce, nie osobę.
- **Domyślna wartość nigdy nie jest „ustalona”.** Nowe pole w liczniku musi
  mieć jawny wybór odróżnialny od wartości startowej; bez tego zapytaj Artura.

## „Klient nie wymaga dokumentów”

- Przycisk przy pustej liście w „Dokumentach do startu” (uprawnienie „Klienci:
  dodawanie i edycja” w portfelu DL, jak dodanie pozycji). Po zaznaczeniu
  panel mówi, kto i kiedy; „Cofnij” zdejmuje znacznik.
- Pusta lista nadal znaczy „NEXUS o nic nie pyta” (`kontrakty/dokumenty-do-startu.md`)
  — znacznik nie zmienia par ani przypomnień, rozróżnia tylko decyzję od braku
  decyzji.
- Znacznik stoi wyłącznie przy pustej liście: zaznaczenie przy pozycjach na
  liście = 409. Dodanie pierwszej pozycji go zdejmuje, więc usunięcie
  wszystkich pozycji wraca do „nieustalone”, a nie do starej decyzji.
- Kolumny `clients.start_documents_not_required_at` i `_by` (migracja 0747,
  lustro w `entrypoint.sh` z `services/start_documents_schema.py`) są poza
  modelem ORM, jak `equipment_provider`: czyta je i pisze
  `services/start_documents.py`. Zapis i zdjęcie idą do historii klienta
  (`activities`, `start_documents_not_required_set` / `_cleared`).
- Scalenie klientów znacznika nie przenosi — tak jak samej listy dokumentów.
- „Klient nie wymaga dokumentów” pisze się wyłącznie przy jawnej decyzji. Pusta
  lista „Dokumenty od konsultanta” w pakiecie pisała to samo zdanie z samego
  braku pozycji, więc od 20.11.2026 ma „Brak dokumentów na liście.”.

## Kto widzi licznik

- Licznik liczy tylko pola z części, które osoba ma na ekranie, i pojawia się
  od **dwóch** takich części (przy jednej powtarzałby jej własny stan).
  Części: „Dokumenty do startu” (podgląd Delivery), pakiet klienta (moduł
  „Wejście i odejście” albo panel konsultanta, plus podgląd Delivery albo
  „Sprzęt”) — daje sprzęt i pierwszy dzień — oraz sposób rozliczenia
  (Finanse, Opieka, admin; inni dostają 403).
- 20.11.2026 na produkcji moduł „Wejście i odejście” jest wyłączony, a panel
  konsultanta ma stan `internal`, więc Delivery Lead widzi tylko „Dokumenty do
  startu” i licznika nie ma; admin widzi „N z 4” (podgląd modułu). Po
  włączeniu modułu DL dostaje „N z 3” sam, bez zmiany kodu.
- Część w trakcie wczytywania albo z błędem: licznika nie ma, bo zaniżyłby
  mianownik; błąd pokazuje sama część. Część z 403/404 po prostu wypada.
- Licznik korzysta z tych samych zapytań (kluczy React Query) co części pod
  nim, więc nic nie pobiera drugi raz, a zapis w części od razu go zmienia.

Testy: `lib/__tests__/client-start-readiness.test.ts` (przypadki brzegowe),
`app/clients/[id]/__tests__/ClientStartReadiness.test.tsx`,
`components/v2/start-docs/__tests__/ClientStartDocsPanel.test.tsx`,
`backend/tests/test_start_documents_api.py::test_not_required_is_an_explicit_decision_on_an_empty_list`.
