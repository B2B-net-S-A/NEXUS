# Scenariusz: lista „Kto się liczy” (etap w nawiasie, marża placementów)

Reguła: `docs/claude/finanse-insights/marza-na-liscie-placementow.md`.

Kto → co robi → co widzi następny:

1. **Admin** otwiera Insights → Zespół → „Kto się liczy · cały zespół” →
   Weryfikacje, filtr „Przed wysłaniem”. „Teraz” pokazuje
   „Przed wysłaniem do klienta (<etap z procesu klienta>) · N dni”; przy
   „Inne zakończenia” „Odrzucenie u nas (na <etap>) · powód”.
2. **Admin** przełącza na Placementy (miesiąc). Widzi kolumny Koszt, Klient,
   Marża (zł/h · %, zł/mies.), bez kolumny „Godzina”; nad tabelą „Marża
   łącznie”. Kontrakt bez stawki klienta ma znaczek „z rekrutacji”, minus jest
   na czerwono. Sprawdza ekran 1280 × 720.
3. **Finanse** — to samo co Admin (Moduł Finanse widzi wszystkich klientów).
4. **Delivery Lead** otwiera Placementy: kwoty tylko klientów z portfela,
   w pozostałych wierszach „—” z podpowiedzią; suma „Marża Twoich klientów”.
   `GET /api/dashboard/v2/recruitment-activity/details?metric=placement…`
   jego tokenem nie ma kwot w wierszach spoza portfela (`margin: null`,
   `margin_hidden: true`).
5. **Head of Recruitment** (rola, która ma nie widzieć kwot) otwiera
   Placementy: lista jak przed zmianą, z „Godziną”, bez kolumn kwot; to samo
   API jego tokenem zwraca `margin_scope: null` i `margin: null` w każdym
   wierszu.
6. **Rekruter** otwiera „Mój miesiąc” → Weryfikacje: etap w nawiasie; lista
   placementów bez kwot (`margin_scope: null`).
