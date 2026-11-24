# Rozliczenia: MD wdrożeniowe raz na kontrakt, kwota faktury w walucie linii

<!-- indeks: MD wdrożeniowe, order.onboarding_md, _onbording, pula wdrożeniowa, miesiąc startu, nieprzyjęte rozliczenie zużywa pulę, reguła od miesiąca, pierwszy miesiąc reguły, amount_revenue w zł, faktura w EUR, client_price, invoice_month, próba rozliczeń IX–X 2026 -->

Próba rozliczeń IX–X 2026 na kopii produkcji z 23/24.11 (powtórka 6) miała 15 przypadków
ze zgodnymi MD i inną kwotą niż faktura Finansów. 6 z nich (BNP) to błąd puli MD
wdrożeniowych, poprawiony tutaj. 7 (Bosch) to błąd miary samej próby, a 2 to dane jednej
linii zamówienia.

Kod: `services/client_settlements/service.py` (`_onboarding_used`, `_onboarding_eligible`,
`_onboarding_rule_in_start_month`), silnik w `engine.py`.
Testy: `test_client_settlements_onboarding_db.py`, `test_client_settlements_engine.py`.

- **MD wdrożeniowe są raz na kontrakt.** Reguła `order.onboarding_md` (na produkcji tylko
  BNP, od 2026-11). Finanse dają 2 MD za 0 zł na fakturze za miesiąc startu (pozycja
  `_onbording`), a od kolejnego miesiąca fakturują pełne MD. Kontrakt jest „nowy” w miesiącu
  startu i w następnym, żeby przeszła reszta puli po starcie pod koniec miesiąca.
- **Pulę zużywa każde policzone wcześniejsze rozliczenie, nie tylko przyjęte.** Wcześniej
  `_onboarding_used` liczył tylko `accepted`, więc miesiąc po starcie liczony przed
  przyjęciem miesiąca startu dostawał 2 MD drugi raz (BNP: 2 kontrakty ze startem w IX,
  w X o 2 MD za niska kwota). Nie przywracaj filtra statusu.
- **Reszta puli przechodzi tylko z miesiąca startu, w którym reguła już działała.**
  Gdy reguła klienta zaczyna się później niż kontrakt, MD wdrożeniowe za miesiąc startu
  dały Finanse poza NEXUS-em, a NEXUS dawał je w kolejnym miesiącu drugi raz (BNP:
  4 kontrakty ze startem w VIII przy regule od IX). Na produkcji to pierwszy miesiąc
  reguły u klienta, np. kontrakt BNP z X w rozliczeniu za XI. Zakładamy, że w miesiącu
  startu poszła cała pula. Start w ostatnim dniu roboczym miesiąca (1 MD) Finanse
  poprawiają wtedy ręcznie.
- **`amount_revenue` rozliczenia jest w zł, faktura w walucie linii.** Przychód
  rozliczenia służy marży i liczy się z `md_rate_*` linii, które są zawsze w zł/MD.
  Kwotę faktury do klienta w EUR dają pozycje `client_invoice.invoice_month`:
  `client_price` bierze `rate_client` w walucie linii przy stawce dziennej. Kwotę
  NEXUS-a porównuj z fakturą sprzedaży (KSeF) na pozycjach albo w walucie faktury, nie na
  `amount_revenue`. Próba 24.11 uznała 7 przypadków Boscha za złą kwotę (iloraz ok. 4,23,
  czyli kurs), a pozycje dawały kwotę faktury co do grosza.
