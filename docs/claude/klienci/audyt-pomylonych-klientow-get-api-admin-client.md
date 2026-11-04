# Audyt pomylonych klientów — `GET /api/admin/client-mixups`

Read-only raport (admin) rodzin klientów o wspólnym rdzeniu nazwy wraz z ich
kontraktami i umowami B2B; przy każdym wierszu NIP obu stron, klient
REKRUTACJI i flaga `job_client_mismatch`. Powstał po DWÓCH niezależnych
zgłoszeniach tej samej pomyłki (BNP Paribas Cardif ↔ CARDIF - ASSURANCES…).

- **Rodzinę wyznacza wspólny TOKEN nazwy, nie podciąg** — „BNP” jako podciąg
  wciąga „BNP Paribas Bank Polska”, odrębnego prawdziwego klienta.
- **Formy prawne odsiane** („SPÓŁKA AKCYJNA”, „ODDZIAŁ W POLSCE”), inaczej pół
  bazy to jedna rodzina. **`ł` trzeba transliterować ręcznie** — NFKD go nie
  rozkłada, więc „SPÓŁKA” tnie się na „spo” + „ka”.
- **Zero mutacji.** Podobna nazwa bywa naprawdę innym klientem; rozstrzyga
  człowiek. `ContractUpdate` nie ma `client_id` — pojedynczy kontrakt przepina
  administrator akcją „Przepnij na innego klienta” (`contract_client_reassign`),
  a duplikat klienta z historią scala się wzorem z
  `scalenie-cardif-pelne-przeniesienie-danych.md`.
- **Stan rodziny „BNP” (odczyt 13.10.2026):** po scaleniu Cardif żaden
  nieaktywny rekord z Traffita (Arval, Faktoring, Real Estate, Lease Group,
  Group Service Center) nie trzyma rekrutacji, kontraktów ani umów — to
  odrębne spółki z kilkoma kontaktami, nie duplikaty.
