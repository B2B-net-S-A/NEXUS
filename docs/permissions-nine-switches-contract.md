# Dziewięć uprawnień — kontrakt wdrożenia

Ekran **Ustawienia → Zespół i dostęp → Osoby i role** ustawia dziewięć uprawnień
tak/nie. To, co admin zaznaczy, decyduje na trasie; odmowa nazywa brakującą
pozycję. Dokument opisuje reguły wspólne dla backendu i frontu oraz kontrakt API
panelu. Decyzje Artura z 02.10.2026.

## 1. Model

| # | Klucz | Nazwa na ekranie | Grupa | Domyślnie (poza adminem) |
|---|---|---|---|---|
| 1 | `delivery_view` | Klienci, kontrakty i zamówienia: podgląd | Klienci i kontrakty | Finanse, DL, TCM |
| 2 | `clients_edit` | Klienci: dodawanie i edycja | Klienci i kontrakty | DL |
| 3 | `contracts_orders_edit` | Kontrakty i zamówienia: tworzenie i edycja | Klienci i kontrakty | DL, Finanse |
| 4 | `contract_status` | Zakończenie współpracy, zmiana statusu kontraktu | Klienci i kontrakty | DL, TCM |
| 5 | `b2b_signature_confirmation` | Umowy B2B: oznaczanie jako podpisane | Klienci i kontrakty | DL, TCM |
| 6 | `recruitment_manage` | Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta | Rekrutacje | DL |
| 7 | `amounts_view` | Stawki i kwoty: podgląd | Pieniądze | Finanse, DL |
| 8 | `amounts_edit` | Stawki i kwoty: zmiana | Pieniądze | Finanse |
| 9 | `finance_module` | Moduł Finanse | Pieniądze | Finanse |

- **Zapis:** istniejące tabele akcji (`rbac_role_action_permissions`,
  `rbac_user_action_overrides`), wartości `manage` / `none`. Katalog:
  `backend/app/services/permission_catalog.py`; ten sam plik JSON czyta front
  (`frontend/src/lib/permission-catalog.json`).
- **Zależności (liczone przy odczycie):** 2, 3, 4, 7 ⇒ 1; 8 ⇒ 7; 9 ⇒ 7.
- **Sekcje Delivery i Finanse wynikają z uprawnień:** Delivery = zapis przy
  2/3/4/8, odczyt przy 1; Finanse = zapis przy 9. `VIEW_FINANCE` /
  `MANAGE_FINANCE` wynikają z sekcji Finanse, czyli z uprawnienia 9. Sourcing,
  Pipeline, Insights i System — jak dotąd, z zapisanych wierszy.
- **Admin ma wszystko zawsze.** Role `user` i `trainee` nie przyjmują uprawnień.

## 2. Zakres klientów (bez zmian)

Uprawnienie mówi, CO konto może; zakres mówi, U KOGO.

- Konto **rządzone portfelem Delivery Leada** = ma rolę `delivery_lead` i nie
  jest adminem (`access_scope.is_delivery_lead_governed`). Działa u swoich
  klientów — dokładnie jak dziś: granica WIDOCZNOŚCI
  (`resolve_delivery_lead_client_ids`) dla odczytu i zwykłych zapisów, granica
  PRZYPISANIA (`resolve_delivery_lead_assigned_client_ids`, razem ze scalonymi
  duplikatami klienta) dla kwot, plików i konsekwentnych zapisów prawnych.
- **Każdy inny posiadacz uprawnienia działa u wszystkich klientów** (resolvery
  zwracają `None`).
- Wymieniamy test ROLI na test UPRAWNIENIA. Helper zakresu w handlerze zostaje.
  Trzy kopie „czy DL jest przypisany” (`require_dl_assigned_or_admin`,
  `_dl_assigned_to_client`, resolver) zastępuje resolver.

## 3. Rdzeń (gotowy — używaj, nie kopiuj)

| Co | Gdzie |
|---|---|
| `ProductAction.<klucz>`, `has_permission(user, action)`, `named_permissions_of(user)` | `app/services/action_permissions.py` |
| `require_permission(action)`, `require_any_permission(*actions)` | `app/api/deps.py` |
| Aliasy: `DeliveryViewUser`, `ClientsEditUser`, `ContractsOrdersEditUser`, `ContractStatusUser`, `RecruitmentManageUser`, `AmountsViewUser`, `AmountsEditUser`, `FinanceModuleUser`, `ContractsOrdersOrAmountsEditUser`, `ClientContractsEditUser` (3 + przypisanie klienta z adresu) | `app/api/permission_access.py` |
| `permission_denied(*actions)`, `ensure_permission`, `ensure_any_permission` | `app/services/permission_denial.py` |
| `is_delivery_lead_governed(user)` | `app/services/access_scope.py` |
| `can_read_client_finance`, `can_manage_finance_amounts(user, client_id=, delivery_lead_finance_client_ids=)`, `can_write_order_amounts`, `order_amounts_denied`, `assert_amounts_only(..., can_edit_record=)` | `app/api/financial_access.py` |
| `ClientAccess` (flagi z uprawnień + `edit_denial()` / `legal_denial()` + `generator_can_*`), `reads_delivery_organization_wide(user)` | `app/services/client_access.py` |
| `assert_contract_legal_client_access`, `require_contract_legal_read_access` | `app/api/contract_access.py` |
| Front: `hasPermission`, `hasAnyPermission`, `permissionsOfUser`, `isDeliveryLeadGoverned`, `PERMISSIONS`, `PERMISSION_GROUPS`, `closePermissions`, `impliedBy` | `frontend/src/lib/permissions.ts` |

Odmowa 403 z bramki uprawnienia:

```json
{"detail": {"code": "permission_denied", "permission": "contracts_orders_edit",
  "label": "Kontrakty i zamówienia: tworzenie i edycja",
  "permissions": ["contracts_orders_edit"],
  "message": "Brakuje Ci uprawnienia „Kontrakty i zamówienia: tworzenie i edycja”. Poproś administratora o dostęp."}}
```

Front pokazuje `detail.message` (`lib/api-error.ts` już to robi).

**Bramka sekcji też nazywa uprawnienie.** Zależności routera
(`DELIVERY_SECTION_DEPENDENCIES`, `FINANCE_SECTION_DEPENDENCIES`,
`require_section_access_any*`) biegną przed bramką uprawnienia trasy. Gdy
odmawiają w sekcji Delivery albo Finanse, czytają uprawnienie zadeklarowane
przez trasę (`require_permission`, `require_any_permission`,
`require_client_contracts_edit` — atrybut `required_permissions`) i zwracają
tę samą odmowę `permission_denied`:

1. trasa deklaruje uprawnienie, którego konto nie ma → nazwane jest ono;
2. inaczej odmowa ODCZYTU Delivery nazywa „podgląd” (`delivery_view`), a każda
   odmowa sekcji Finanse — „Moduł Finanse” (`finance_module`), o ile konto ich
   nie ma;
3. w pozostałych przypadkach zostaje `section_access_denied` (dla zapisu
   w Delivery z polskim `message`). Bramki Sourcing, Pipeline i Insights
   działają jak dotąd.

Nazywane jest wyłącznie uprawnienie, którego konto NIE ma — osoba ograniczona
starym wyjątkiem sekcji dostaje zwykłą odmowę sekcji. Wniosek dla nowych tras:
czyste wymaganie uprawnienia deklaruj zależnością trasy, nie sprawdzeniem
w środku handlera — tylko zależność da się nazwać, zanim handler ruszy.

## 4. Reguły, które łatwo pomylić

- **Kwoty kontraktu** zmienia 8. **Kwoty zamówienia i linii MD** zmienia 8 albo
  (3 i 7 u klienta z zakresu) — tak jak dotąd przypisany DL
  (`can_write_order_amounts`). Posiadacz 3 bez 7 zakłada kontrakt i zamówienie
  bez kwot, a przy stawkach i pliku PDF dostaje odmowę z nazwą „Stawki i kwoty:
  podgląd” (`order_amounts_denied`).
- **Dokumenty i pliki** (mogą nieść stawki) = 7 u klienta z zakresu; zapis
  dokumentów prawnych = 3 i 7 u klienta z przypisania. Zastępuje to `_is_read_only_tcm`
  i role wpisane w aliasy odczytu.
- **Trasa mieszana** (PATCH kontraktu, zamówienia, grupy, linii): wejście
  3 albo 8 (`ContractsOrdersOrAmountsEditUser`); kto nie ma 3, zmienia wyłącznie
  kwoty (`assert_amounts_only(..., can_edit_record=has_permission(user, 3))`).
- **Zmiana `status` w zwykłym `PATCH /api/contracts/{id}`** wymaga 4 tylko wtedy,
  gdy status naprawdę się zmienia (formularz odsyła `status` przy każdym zapisie).
- **Prywatne notatki relacyjne kontaktu** zostają przy roli (właściciel, admin,
  Finanse; TCM nigdy) — `ClientAccess.reads_private_notes_org_wide`.
- **Generator umów B2B** (`purpose="org"`) działa jak dotąd
  (`generator_can_view_legal` / `generator_can_edit_legal`, `_RateVisibility`).
- **Podpis B2B (5):** konto z rolą DL potwierdza u klientów z przypisania, każdy
  inny posiadacz — u wszystkich. TAC nie ma go domyślnie.

## 5. Co zostaje przy roli

Trasy tylko dla admina · „Cofnij zakończenie” i „Powrót po przerwie” (admin,
Finanse, TCM) · skrzynka alertów DL · struktura zespołu i przypisania DL↔klient
· Champion (weryfikacja, briefing, generowanie) · przypinanie w czacie ·
szablony pipeline'u · kolejka przeglądu DL · pełna edycja rekrutacji przez TAC
· tabela rok do roku dla HoR bez kwot · podgląd stawki do klienta
(`CLIENT_RATE_VIEW_ROLES`) · stawki w Generatorze B2B · „Może usuwać klientów”.

## 6. Zmiany zachowania (jedyne zamierzone)

1. **Finanse:** całość pozycji 3 — kontrakt (tworzenie, edycja, aktywacja,
   unieważnienie, usunięcie, dokumenty, aneksy), zamówienia (tworzenie,
   przedłużenie, linie MD, zastosowanie zamówienia z maila), umowy ramowe
   i wykonawcze. Statusu kontraktu nadal nie zmieniają (to 4).
2. **TCM:** zbiorcze „Oznacz zakończone” i „Zakończ projekt” (to samo
   uprawnienie co pojedyncze zakończenie).
3. **TAC:** podpis B2B wyłączony (był włączony, ale nigdy nie działał).
4. Odmowa na przepiętych trasach niesie nazwę uprawnienia.
5. `/settings/cv-rules` wpuszcza posiadaczy pozycji 2.
6. Przypisanie DL liczone jedną funkcją, razem ze scalonymi duplikatami klienta.
7. Świeże bazy: TCM ma Delivery „zapis”, jak produkcja.

Wszystko inne ma zostać identyczne. Pilnuje tego macierz bramek
(`backend/tests/test_authz_guard_matrix.py`, wzorzec w
`backend/tests/data/authz_golden/`): 1227 tras × 21 person (18 pierwszych to
persony sprzed przepięcia; trzy ostatnie — rekruter z nadanym
`recruitment_manage`, `finance_module` i samym `amounts_edit` — odróżniają
bramkę uprawnienia od bramki roli).

### Skutki w treści handlerów (macierz ich nie widzi)

Wynikają z punktów wyżej albo z tego, że bramka pyta o uprawnienie:

- **Finanse** edytują w `PATCH /api/contracts/{id}` także pola niebędące
  kwotami (pkt 1); status i dane zakończenia współpracy zostają przy pozycji 4.
- **TCM** potwierdza podpis dokumentów pochodnych z rodziny zakończenia
  (rozwiązanie, wypowiedzenie) — to pozycja 4, którą ma.
- **Druk szkicu kontraktu** bez zapisanego szkicu: osoba z pozycją 3 dostaje
  404 zamiast pustego dokumentu.
- **Stawka do klienta w rekrutacji:** widzi ją także każdy, kto ją zapisuje
  (pozycja 6) — dla ról domyślnych bez zmiany.
- **Zamówienia z maila** („Zastosuj”, „Odrzuć”, „Przelicz plan”) wymagają
  pozycji 3 ORAZ prawa do kwot zamówień klienta; sama pozycja 8 nie wystarcza.
- **Budżet linii zamówienia wpisany kwotą** (tryb „kwota”) zmienia konto
  z prawem do kwot zamówień klienta; budżet w MD — każdy prowadzący zamówienia.
- **Mail zarządu** idzie do posiadaczy pozycji 9 z dostępem do Insights
  (domyślnie ci sami odbiorcy: admin i Finanse).

## 7. API panelu

### `GET /api/admin/section-permissions`

Dotychczasowe pola zostają. Dochodzą:

```json
{
  "derived_sections": ["delivery", "finance"],
  "permission_groups": [{"key": "clients_contracts", "label": "Klienci i kontrakty", "permissions": ["delivery_view", "..."]}],
  "permissions": [{"key": "delivery_view", "label": "…", "group": "clients_contracts", "requires": [], "default_roles": ["finance", "delivery_lead", "talent_community_manager"]}],
  "roles": [{
    "role": "finance",
    "users_count": 1,
    "grantable": true,
    "permissions": {"delivery": "write", "finance": "write", "…": "…"},
    "action_permissions": {"b2b_contract_generator": "manage", "delivery_view": "manage", "…": "…"},
    "named": {"delivery_view": {"granted": true, "effective": true, "implied_by": ["contracts_orders_edit", "amounts_view"]}}
  }]
}
```

- `named[klucz].granted` — zapisany wiersz roli (to, co przełącza admin);
  `effective` — po zależnościach; `implied_by` — które nadane uprawnienia go
  wymuszają (przełącznik włączony i zablokowany).
- `permissions.delivery` / `permissions.finance` — poziom WYLICZONY z uprawnień.
- `users_count` — aktywne konta z tą rolą (główną albo dodatkową).
- `grantable` — `false` dla `admin` (ma wszystko), `user` i `trainee`.

### `PUT /api/admin/section-permissions/roles`

Ciało bez zmian (`revision`, `changes`, `action_changes`).

- `action_changes` dla dziewięciu uprawnień: `access` ∈ `none` | `manage`
  (inaczej 422).
- `changes` z sekcją `delivery` albo `finance` → 422
  `{"code": "derived_section_access", "message": "Dostęp do Delivery i Finansów wynika z uprawnień."}`.
- Nadanie roli `user` albo `trainee` → 422 `{"code": "role_not_grantable"}`.
- Zapis zostawia wpis w Historii zdarzeń: `rbac.role_permissions`.

### `GET /api/admin/section-permissions/users/{user_id}` (nowe)

```json
{
  "revision": 6,
  "user": {
    "user_id": 90, "name": "…", "role": "talent_community_manager", "roles": ["talent_community_manager"],
    "locked": false, "grantable": true,
    "role_permissions": ["delivery_view", "contract_status", "b2b_signature_confirmation"],
    "grants": ["contracts_orders_edit"],
    "restrictions": [],
    "effective": ["delivery_view", "contract_status", "b2b_signature_confirmation", "contracts_orders_edit"],
    "legacy_section_caps": {}
  }
}
```

- `role_permissions` — to, co dają role konta (po zależnościach).
- `grants` — uprawnienia nadane osobie (`manage` w wyjątkach).
- `restrictions` — stare wyjątki odbierające (`none`); nowy ekran ich nie tworzy.
- `legacy_section_caps` — stare wyjątki sekcji Delivery/Finanse (tylko ograniczają).
- `locked: true` dla admina; `grantable: false` dla ról `user`, `trainee`.

### `PUT /api/admin/section-permissions/users/{user_id}`

Ciało bez zmian.

- `action_changes` dla dziewięciu uprawnień: `access` ∈ `manage` | `inherit`.
  `none` → 422 `{"code": "additive_only"}` (uprawnienia osoby tylko dodają).
- `changes` z sekcją `delivery` / `finance`: wyłącznie `inherit` (zdjęcie starego
  ograniczenia); poziom → 422 `derived_section_access`.
- Konto `user` / `trainee` → 422 `role_not_grantable`.
- Wpis w Historii zdarzeń: `rbac.user_permissions`.

### `GET /api/admin/users`

Każde konto niesie `extra_permissions: string[]` — uprawnienia nadane osobie,
których nie dają jej role (plakietka „+N uprawnienie”).

### Wylogowanie

Zmiana uprawnień roli albo osoby nadal unieważnia sesje dotkniętych kont
(`invalidated_users` w odpowiedzi) — token niesie sekcje dla middleware.

### Szczegóły zapisu

- **Rola bez wierszy zasiewu.** Resolver liczy ją funkcją zasiewu z jej
  zapisanych sekcji. Pierwsza prawdziwa zmiana uprawnienia zapisuje komplet
  ośmiu wierszy (inaczej rola stałaby się „zasiana częściowo”, czyli
  zamknięta), a audyt podaje jako stan „przed” wartość efektywną. Zapis tego,
  co rola już ma z zasiewu, zwraca `changed: false` i nie pisze nic.
- **Odmowa bazy** (CHECK akcji sprzed migracji 0410) → 409
  `{"code": "permission_storage_rejected", "message": …}` zamiast 500.
- **Historia zdarzeń.** `rbac.role_permissions`: jeden wpis na rolę, obiekt
  „Uprawnienia roli”; `rbac.user_permissions`: obiekt „Uprawnienia
  użytkownika”. `details.changes` niesie klucze uprawnień z wartościami
  `from` / `to`; kolumna „powód” — zdanie z nazwami („Włączono: …”, „Nadano: …”,
  „Usunięto ograniczenie: …”). Wpis powstaje w tej samej transakcji co zmiana.
- `role_not_grantable` przy osobie dotyczy NADANIA (`manage`); zdjęcie starego
  ograniczenia (`inherit`) przechodzi dla każdego konta poza adminem.

## 8. Ekran (makieta v3)

- Zakładka „Uprawnienia”: chipy ról (bez administratora, bez `user` i `trainee`),
  jedna rola naraz, dziewięć przełączników w trzech grupach. Zmieniony wiersz
  jest podświetlony („zmiana · dziś: tak/nie”). Stopka: „N zmian do zapisania”,
  „Cofnij”, „Zapisz zmiany” → potwierdzenie z liczbą osób, które zostaną
  wylogowane.
- Uprawnienie wymuszone przez inne: włączone i zablokowane, z podpisem
  „Wymagane przez: …”.
- Zakładka „Użytkownicy”: plakietka „+N uprawnienie” przy osobie; w oknie
  „Edytuj użytkownika” sekcja „Dodatkowe uprawnienia” — tylko te, których rola
  tej osoby nie daje. „Może usuwać klientów” zostaje osobnym polem.
- Z ekranu znikają: tabela ról × sekcji, „Funkcje specjalne”, zakładka „Wyjątki
  użytkowników”. Zapisane wartości Sourcing/Pipeline/Insights i poziomy
  Generatora B2B zostają w bazie i działają jak dotąd.

## 9. Testy

- Macierz bramek: `cd backend && python -m pytest tests/test_authz_guard_matrix.py`.
  Czerwony test wypisuje „persona: było→jest”. Zamierzoną zmianę utrwala
  `AUTHZ_GOLDEN_WRITE=1 python -m pytest tests/test_authz_guard_matrix.py`;
  diff plików wzorca trafia do PR-a jako lista zmian dostępu.
- Katalog i resolver: `test_permission_catalog.py`, `test_effective_access.py`,
  `test_permission_access.py`; migracja i siatka przy starcie:
  `test_named_permissions_migration.py` (Postgres).
