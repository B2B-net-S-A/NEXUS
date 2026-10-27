# Sprzedaż w NEXUSIE (Atlas → NEXUS) — decyzje Artura 26–27.10.2026 i reguły modułu
<!-- indeks: sales_view/sales_edit, kartoteka firm osobna od clients, „Kogo znamy” z pełnym profilem, daty per firma, powiązanie z klientem zamiast automatu, leady bez silnika, import Atlasa -->

Sekcja „Sprzedaż” zastępuje CRM Atlasa (D1 = budowa w NEXUSIE od nowa
i import danych). Propozycja z makietami M0–M4:
https://claude.ai/artifact/DwuZg8fxnWRg4NdXVgLTpe.

## Dostęp

- **Dwa uprawnienia, bez roli „Handlowiec”**: „Sprzedaż: podgląd” (`sales_view`)
  i „Sprzedaż: edycja” (`sales_edit`, pociąga podgląd). Domyślnie ma je tylko
  admin; handlowcom nadaje je ekran Osoby i role. Migracja 0600, katalog
  `permission_catalog.py` (na końcu), CHECK w `entrypoint.sh`.
- **Bez sekcji produktu** (jak „Ludzie”): każda trasa `/api/sales/**` ma
  `SalesViewUser` (odczyt) albo `SalesEditUser` (zapis) z
  `api/permission_access.py`. Menu: capability `nav.sales`.
- Edycja jest otwarta dla każdego z `sales_edit` (jak w Atlasie). **Zmianę
  opiekuna** robi obecny opiekun albo admin (`sales_gates.ensure_owner_or_admin`),
  aktywność usuwa jej autor albo admin.

## Kartoteka firm (D2)

- `sales_companies` jest **osobna od `clients`** — 9 tys. firm z Atlasa nie
  zalewa listy klientów. `client_id` łączy firmę z klientem NEXUSA (jeden klient
  = jedna firma sprzedaży, `ux_sales_companies_client`), `parent_company_id`
  to grupa kapitałowa.
- Duplikat (ten sam NIP albo nazwa kanoniczna `normalize_company_name`)
  **ostrzega (409), nie blokuje** — dwie spółki o tej samej nazwie istnieją.
- Szansa zawsze ma firmę (w Atlasie 115 szans było „sierotami” z samą nazwą).

## „Kogo znamy w firmie” (D3, D4)

- Panel liczy to samo co endpoint dla CRM (`integrations_companies.lookup_company_people`),
  prosto w bazie, z nazwą klienta powiązanego i NIP-em; plus liczby dla firmy
  matki i spółek zależnych.
- **D4: handlowiec widzi pełny profil kandydata** (kontakt, link do profilu) —
  decyzja Artura 26.10.2026, bez przełącznika i bez czekania na opinię IOD.
- **D3: daty zatrudnienia per firma.** Pierwsza szansa w firmie (i przycisk
  „Uzupełnij daty”) odpala w tle bieg dla osób „bez dat” z tej firmy
  (`services/sales/company_dates.py`, do 1000 osób, wyłącznik
  `EXPERIENCE_DATES_ON_DEMAND_ENABLED`, powtórka po 30 dniach). Bieg kosztuje
  (model AI) — na stagingu też. **„running” starszy niż 2 h jest porzucony**
  (wdrożenie restartuje kontener w trakcie biegu) — nie usuwaj tej reguły.

## Szanse

- Reguły cyklu życia z Atlasa (`services/sales/lifecycle.py`): etap z wynikiem
  ustawia status i daty, prawdopodobieństwo idzie za etapem, **kwalifikacja
  ustawia się raz** (cofnięcie jej nie czyści), wartość = MRR + jednorazowa
  (jak w Atlasie — nie mnożymy przez miesiące bez decyzji).
- Ruch po etapach wyłącznie przez `POST /api/sales/opportunities/{id}/move`.

## Wygrana → Delivery (decyzja 27.10.2026)

- **Tylko powiązanie z klientem NEXUSA** (`/api/sales/clients/link/{company_id}`)
  i zakładka „Sprzedaż” w karcie klienta (pod „Więcej”, `sales_view`).
  **Nie** zakładamy klienta, nie przypisujemy DL, nie zakładamy rekrutacji ani
  nie wysyłamy dzwonka — rekrutacje DL zakłada jak dziś (bramka gotowości
  rekrutacji i tak nie przepuściłaby samych ról z szansy).
- Wyszukiwarka klientów dla Sprzedaży zwraca tylko id i nazwę (handlowiec nie
  ma podglądu Delivery) i szuka też po nazwie bez formy prawnej.

## Leady (decyzja 27.10.2026)

- **Bez silnika.** Skan ogłoszeń z Atlasa celował w klientów Elevate (firmy
  spoza IT szukające back-office) i odrzucał zatrudniających programistów —
  odwrotnie niż body leasing. Skrzynka = import otwartych leadów z Atlasa
  i wpisy ręczne.
- **Lead z firmy, która jest już klientem NEXUSA, nie powstaje** (409) —
  popyt u klienta idzie do jego DL (decyzja 22.10.2026); dlatego import
  pomija też `compass_signals` („Od konsultantów”).

## Import z Atlasa

- `backend/scripts/import_atlas_sales.py` — połączenie **tylko do odczytu**
  z `ATLAS_DATABASE_URL`, domyślnie na sucho, `--apply` zatwierdza.
  Idempotentny po `external_ref` / `fingerprint`; drugi bieg nie nadpisuje
  opiekuna ani statusu leada zmienionego w NEXUSIE.
- Firmy-nazwiska bez odwołań odpadają, z odwołaniami dostają tag
  „atlas: do przejrzenia”. Raport to same liczby (repo i Actions są publiczne).
- Pliki z Supabase Storage przenosi osobny krok (wymaga klucza storage Atlasa).

## Poza zakresem (świadomie)

Oferty, P&L sprzedaży, skan ogłoszeń/LinkedIn/prasy, poczta i kalendarz M365
przy szansie, Fireflies, „Kogo możemy dać od ręki” (Talent Radar na rolach).
