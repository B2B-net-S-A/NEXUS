# Rola „Back office”: zamówienia i umowy bez finansów firmy (0645, 04.11.2026)
<!-- indeks: rola back_office, uprawnienie orders_work, zakładki zamówień w /finance bez sekcji Finanse, znacznik fo w tokenie, kwoty przez amounts_view zamiast VIEW_FINANCE -->

Zgłoszenie Artura 04.11.2026: w Finansach za dużo osób widzi za dużo. Rola Finanse
to jeden pakiet, więc osoba od zamówień dostawała też Wyniki miesięczne, Płace
i faktury. Makiety i decyzje: https://claude.ai/artifact/6FBkVh1TMC2XKMgYSiwxyP.

## Decyzje Artura

- **Wariant B:** Zmiany w zamówieniach, Zamówienia PDF i Import zużycia MD zostają
  w `/finance`. Back office widzi tam tylko te trzy zakładki.
- **Marża przy rekordzie zostaje** (panel i karta kontraktu), a edycja klientów
  zostaje jak u dotychczasowych Finansów.
- Nie ma: Wyników miesięcznych, Archiwum, Faktur do klientów, Wydatków ze zgodą,
  Płac, Kadr, czatów przy wszystkich rekrutacjach, prywatnych notatek o klientach,
  analityki zarządczej. Wyniki firmy są zamknięte tak samo jak u Finansów.
- Role kont zmienia Artur w „Osoby i role”. Identyfikatorów kont nie ma w repo,
  bo jest publiczne.

## Reguła, której łatwo nie zauważyć

**Back office nie może mieć sekcji Finanse.** Jej odczyt dodaje `VIEW_FINANCE`
(`analytics/capabilities.py`), a ta capability steruje ponad 40 powierzchniami.
Dlatego:

- Zakładki o zamówieniach otwiera **`orders_work`** („Zamówienia: zmiany, PDF-y,
  import MD”). Trasy stoją na `finance.orders_router`, bez bramki sekcji;
  `/api/md-consumption` na `OrdersWorkUser`. „Moduł Finanse” pociąga `orders_work`,
  więc posiadacz modułu niczego nie traci.
- Odebranie „Modułu Finanse” osobie z rolą Finanse zostawia jej zakładki o zamówieniach.
  Żeby zamknąć całe wejście, trzeba odebrać oba uprawnienia.
- Kwoty przy rekordzie daje „Stawki i kwoty: podgląd”
  (`financial_access.can_read_client_finance`), tą samą drogą co Delivery Leadowi.
- Middleware nie widzi uprawnień, więc `orders_work` podróżuje w tokenie jako
  podpisany znacznik **`fo`**. To warstwa UX; bramką jest API.
- **Sam `amounts_view` to za mało, żeby otworzyć faktury.** Back office ma go u wszystkich
  klientów, więc `/api/clients/sales-invoices/overdue` i zakładka „Faktury” przy kliencie
  mają własną odmowę dla roli (`client_sales_invoices._require_invoicing_reader`), a `module`
  zwraca `open: false`. Nowa trasa za `AmountsViewUser`, która zbiera dane z wielu klientów,
  potrzebuje tej samej decyzji.
- Trasa zbiorcza albo nowa zakładka pieniędzy w `/finance` idzie na `router`
  z bramką sekcji albo za `CompanyResultsUser`, nigdy na `orders_router`.

## Rola a zbiory ról

Back office jest dopisany tam, gdzie Finanse pracują operacyjnie: kandydaci
i rekrutacje (`candidate_access`, `recruitment_access`), Generator i dokumenty
umów, umowy przedwstępne, „Cofnij zakończenie”, alerty Delivery Leada, dzwonek
o zatrudnionym bez zamówienia i zadania na pulpicie (`board_flow.load_finance`).
Świadomie nie ma go w: `admin_chats`, `PRIVATE_NOTES_ORGANIZATION_ROLES`, raportach
`reports.py`, kalendarzu całej firmy, analityce `scope.py`, eksporcie alertów
wszystkich Delivery Leadów. Nowy zbiór z Finansami: zdecyduj, do której grupy należy,
a diff wzorca `tests/data/authz_golden/` pokaże skutek.

Zespół „Zamówienia” w kolejce spraw wynika z `orders_work`, „Umowy” z `contracts_orders_edit`.
