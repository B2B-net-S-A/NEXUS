# Filtr „Umowa nierozwiązana” w rejestrze kontraktów (decyzja Artura 28.10.2026)

Na kopii produkcji z 22.10 69 z 73 zakończonych albo kończących się
kontraktów B2B nie miało zapisanego rozwiązania umowy (18 z 22 zakończeń od
23.09, gdy okno „Zakończ współpracę” już pytało o umowę). Zespół domyka
zaległe porozumienia i wypowiedzenia z jednej listy: przycisk „Umowa
nierozwiązana” w pasku filtrów `/contracts`.

- **Zbiór liczy serwer** (`agreement_not_terminated` w
  `_apply_contract_list_filters`, `api/contracts.py`): `contract_type = b2b`,
  status `ended` albo `ending`, `agreement_termination_mode IS NULL`. Ta sama
  funkcja karmi listę i eksport, więc „eksportuj to, co widzę” trzyma.
  Umowa zlecenie i UoP nie mają porozumienia z generatora B2B — nie wchodzą.
- **Pole wypełniają dwie ścieżki:** okno „Zakończ współpracę” („Umowa jest
  już rozwiązana albo wypowiedziana”) i podpis porozumienia w generatorze
  (`effects.apply`). Nowa ścieżka rozwiązania umowy, która nie zapisuje
  `agreement_termination_*`, zostawi kontrakt na tej liście.
- **Adres:** `?agreement=not_terminated` (`lib/contracts-list-navigation.ts`).
  Wejście z samym filtrem bierze wszystkie statusy (`status=all`), bo domyślne
  „Aktywne + Kończące się” ucięłyby zakończone. Jawny status łączy się z
  filtrem przez AND (`status=active` daje pustą listę, nie ignoruje filtra).
  Wyłączenie przycisku przy pustym statusie wraca do domyślnych statusów.
- Trasa ta sama co lista (`DeliveryViewUser`, zakres klientów Delivery Leada),
  więc bez zmian w `tests/data/authz_golden/`. Wpis w spisie:
  `k.agreement-not-terminated-filter`.
