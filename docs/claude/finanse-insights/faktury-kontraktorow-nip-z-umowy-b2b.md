# Faktury kontraktorów: NIP z umowy B2B nie wiąże sam (25.11.2026)

Audyt finansów z 25.11.2026: `b2b_generated_contracts.partner_nip` bywa NIP-em innej firmy niż osoba
z kontraktu. Pomiar na produkcji: 6 ze 130 kontraktów z NIP-em z generatora — inkubator wystawiający
faktury za wielu konsultantów (61 faktur w 2026 r. z jednego NIP-u), firma innej osoby („Partner”
w generatorze to ktoś inny niż kontrakt) i spółki osób bez nazwiska w nazwie. `candidates.nip` był pusty
u wszystkich, więc każde wiązanie po NIP-ie szło z generatora. Od 17.11 do 25.11 automat związał
5 faktur, wszystkie poprawnie: błąd czekał na pierwszą fakturę inkubatora.

Reguła (`contractor_invoices.by_seller_nip`, decyzja Artura z 25.11.2026: „zatwierdzenie przez Finanse”):

- **NIP zatwierdzony u osoby** (`candidates.nip`, z podpowiedzi zatwierdzonej przez Finanse albo
  wpisany ręcznie) wiąże fakturę jak dotąd, także gdy nazwa sprzedawcy to spółka.
- **NIP tylko z umowy B2B** wiąże sam, gdy nazwa sprzedawcy ma pełne imię i nazwisko osoby
  (bez polskich znaków i wielkości liter, `name_tokens`) albo gdy netto jest równe rozliczeniu co do grosza
  (ta sama ścieżka kwoty co przy kilku osobach na jednym NIP-ie). Inaczej faktura idzie jako
  `suggested`: „NIP kontraktora do zatwierdzenia” na karcie osoby. Zatwierdzenie zapisuje NIP osobie,
  więc kolejne faktury tej spółki wiążą się same; odrzucenie (para NIP + kontrakt w `rejected`)
  zatrzymuje dalsze podpowiedzi z tego NIP-u dla tego kontraktu — tak Finanse zamykają inkubator.
- **Pełne imię i nazwisko INNEJ osoby z kontraktem** w nazwie sprzedawcy: NIP nie rozstrzyga nigdy,
  nawet przy równej kwocie. Faktura idzie ścieżką nazwiska (podpowiedź dla tamtej osoby, jeśli nie ma NIP-u).
  Ta sama osoba na drugim kontrakcie to nie „ktoś inny”.

Lista dla Finansów: Finanse → Rozliczenia, karta „Umowy B2B z NIP-em innej firmy”
(`GET /api/finance/settlements/contract-nip-review`, `contract_nip_review.py`). Kontrakt w zakresie
automatu (trwający albo zakończony w `ENDED_GRACE`), bez NIP-u osoby, którego `partner_nip`
ma w generatorze innego „Partnera” (`partner_name` to imię i nazwisko, nie firma) albo faktury z KSeF
(kosztowe w `approval_documents` i kontraktorów) bez imienia i nazwiska osoby w nazwie sprzedawcy.
Po zatwierdzeniu NIP-u osoba ma własny NIP i znika z listy. Pusta lista = brak karty, awaria = komunikat.

Nazwisk ani NIP-ów osób z produkcji nie zapisujemy w repo (repo publiczne); listę dostaje Artur prywatnie.

Testy: `tests/test_client_settlements_contractor_invoices_db.py` (sekcja „NIP z umowy B2B”),
`frontend/src/components/finance/settlements/__tests__/contract-nip-review.test.tsx`.
