# Umowy klientów: lista i pliki bez kwot w systemie (04.11.2026)

<!-- indeks: `client_contracts_view`, `/client-contracts`, bez sekcji Delivery, bez notatek, stawki mogą być w plikach -->

Decyzja Artura z 04.11.2026: osoba z administracji ma widzieć umowy z klientami,
ale nie stawki. Stare trasy umów wymagają „Stawki i kwoty: podgląd” i sekcji
Delivery, które otwierają kwoty i kontrakty w całym systemie.

- **Własne uprawnienie i ekran:** `client_contracts_view` otwiera tylko
  `/client-contracts` i `/api/client-contract-documents` (lista, plik umowy, plik
  aneksu). Domyślnie ma je tylko admin, resztę nadaje okno „Edytuj użytkownika”.
  Sekcji produktu nie ma, jak w Sprzedaży (`test_section_ceiling_contract`).
- **Odpowiedź API to osobny schemat, nie `ClientFrameworkContractRead`.** Notatki,
  waluta, warunki aneksu i odczytany tekst nie wychodzą, bo mogą nieść stawki:
  33 z 48 umów ma notatkę. Nowe pole dodawaj tylko po sprawdzeniu, czy nie niesie kwoty.
- **W plikach stawki mogą być i to świadoma decyzja.** Pomiar z 04.11.2026 na
  81 odczytanych dokumentach (42 umowy, 39 aneksów): 16 ma kwotę przy słowie „stawka”
  albo „netto/za dzień”, 74 ma jakąkolwiek kwotę. Artur odrzucił wariant z oznaczaniem
  plików „bez stawek”, dlatego nazwa uprawnienia mówi o tym wprost. Nie obiecuj
  „bez stawek” bez tego zastrzeżenia.
- **Delivery Lead z tym uprawnieniem zostaje przy swoich klientach**
  (`resolve_delivery_lead_client_ids`). Klient usunięty znika z listy i plików.
