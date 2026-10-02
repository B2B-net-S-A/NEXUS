# Dziewięć uprawnień zamiast macierzy sekcji — raport

PR: [B2B-net-S-A/NEXUS#1976](https://github.com/B2B-net-S-A/NEXUS/pull/1976) ·
migracja `0410_named_permissions` · kontrakt:
`docs/permissions-nine-switches-contract.md` · makieta:
https://claude.ai/artifact/EfjFN2sFCY8tDq6r3XksPt

## Po co

Zgłoszenie administratora z 02.10.2026: ekran Ustawienia → Zespół i dostęp →
„Osoby i role” → „Uprawnienia” nie mówił, co kto może, ani co da się nadać.
Ustawiał sześć sekcji i dwie „funkcje specjalne”, a o operacjach decydowało
ponad 80 bramek ról w kodzie i reguły w środku handlerów. Finanse miały
Delivery „Odczyt i zapis”, a kontraktu nie mogły założyć (bramka admin +
Delivery Lead); roli Finanse nie da się łączyć z inną, więc administrator nie
miał żadnego ruchu.

Decyzje Artura (02.10.2026): dziewięć pozycji wystarczy · Finanse dostają
„Kontrakty i zamówienia: tworzenie i edycja” · konto Talent Community Managera
ze zgłoszenia też ma tworzyć kontrakty (nadanie jednej osobie).

## Co jest teraz

| # | Klucz | Nazwa na ekranie | Domyślnie ma (poza adminem) |
|---|---|---|---|
| 1 | `delivery_view` | Klienci, kontrakty i zamówienia: podgląd | Finanse, DL, TCM |
| 2 | `clients_edit` | Klienci: dodawanie i edycja | DL |
| 3 | `contracts_orders_edit` | Kontrakty i zamówienia: tworzenie i edycja | DL, Finanse (nowe) |
| 4 | `contract_status` | Zakończenie współpracy, zmiana statusu kontraktu | DL, TCM |
| 5 | `b2b_signature_confirmation` | Umowy B2B: oznaczanie jako podpisane | DL, TCM |
| 6 | `recruitment_manage` | Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta | DL |
| 7 | `amounts_view` | Stawki i kwoty: podgląd | Finanse, DL |
| 8 | `amounts_edit` | Stawki i kwoty: zmiana | Finanse |
| 9 | `finance_module` | Moduł Finanse | Finanse |

- **Ekran „Uprawnienia”**: jedna rola naraz, dziewięć przełączników w trzech
  grupach, pasek zapisu z potwierdzeniem i liczbą osób, które zostaną
  wylogowane. Pozycja wymuszona przez inną (edycja ⇒ podgląd, zmiana kwot ⇒
  podgląd kwot) jest włączona i zablokowana.
- **„Edytuj użytkownika” → „Dodatkowe uprawnienia”**: lista pokazuje tylko to,
  czego role osoby nie dają; zaznaczone działa wyłącznie dla tej osoby. Na
  liście kont plakietka „+N uprawnienie”.
- **Odmowa nazywa pozycję**: „Brakuje Ci uprawnienia „…”. Poproś administratora
  o dostęp.” — także wtedy, gdy zatrzymuje bramka sekcji, która biegnie przed
  bramką trasy.
- **Sekcje Delivery i Finanse są wyliczane** z uprawnień; Sourcing, Pipeline,
  Insights i poziomy Generatora B2B zostały przy zapisanych wartościach
  (zniknęły tylko z ekranu).
- **Zakres klientów bez zmian**: konto z rolą Delivery Leada działa u swoich
  klientów, każdy inny posiadacz uprawnienia — u wszystkich.

## Co zmieniło się w zachowaniu

Lista zamknięta — kontrakt, §6. W skrócie: Finanse prowadzą kontrakty
i zamówienia (statusu kontraktu nadal nie zmieniają — także datą końca ani
przedłużeniem „Zakończonego”); TCM ma zbiorcze „Oznacz
zakończone”; TAC nie ma już nigdy niedziałającego „oznaczania podpisu”; 403
nazywa uprawnienie; `/settings/cv-rules` wpuszcza posiadaczy edycji klientów.
Skutki w treści handlerów (Finanse edytują pola kontraktu poza kwotami, TCM
potwierdza dokumenty zakończenia, zamówienia z maila wymagają prowadzenia
zamówień, budżet linii w kwocie jest kwotą) są wypisane w tym samym paragrafie.

## Jak to jest zbudowane

- Katalog: `backend/app/services/permission_catalog.py` (klucze, nazwy,
  zależności, domyślni posiadacze) — ten sam JSON czyta front
  (`frontend/src/lib/permission-catalog.json`, `lib/permissions.ts`).
- Przechowywanie: istniejące tabele akcji (`rbac_role_action_permissions`,
  `rbac_user_action_overrides`), wartości `none|manage`. Bez nowych tabel.
- Bramki: aliasy z `backend/app/api/permission_access.py` jako zależności tras;
  kwoty — `financial_access.py`; zakres — `access_scope.py` (bez zmian reguł).
- Zasiew: `permission_schema.py` (jedno źródło dla migracji 0410, 0282
  i `entrypoint.sh`), siatka przy starcie `named_permissions_bootstrap.py`.
  Rola bez wierszy zasiewu jest liczona funkcją zasiewu z jej zapisanych
  sekcji, więc start bez migracji nie zamyka Delivery.
- Panel: `backend/app/api/admin_section_permissions.py` (GET z katalogiem
  i wartościami efektywnymi, `GET …/users/{id}`, zapis ról i osób z rewizją,
  wpisy w Historii zdarzeń, wylogowanie dotkniętych kont).

## Jak to jest sprawdzone

- **Macierz bramek** (`backend/tests/test_authz_guard_matrix.py`): werdykt
  zależności każdej z 1229 tras dla 21 person, bez bazy; wzorzec w
  `backend/tests/data/authz_golden/`. Diff wzorca względem stanu sprzed
  przepięcia to lista zmian dostępu.
- **Testy zachowania przez HTTP** (baza, CI): `test_named_permissions_http.py`,
  `test_permissions_orders.py`, `test_permissions_recruitment.py`,
  `test_permissions_finance_module.py`, `test_admin_section_permissions.py`.
- **Front**: testy komponentów ekranu i okna użytkownika, lustro reguł
  backendu (`capabilities.test.ts`), harness `/preview/permissions`
  przeklikany przy 1280 × 720 i 360 px.
- **E2E `@stack`** (`frontend/e2e/permissions.spec.ts`): Finanse zakładają
  kontrakt i zamówienie; przełącznik roli kliknięty na ekranie otwiera
  i zamyka trasę; uprawnienie nadane osobie daje kontrakt bez kwot, a ze
  stawką — odmowę z nazwą „Stawki i kwoty: zmiana”.
  Scenariusze pamiętają token roli w procesie workera (`e2e/helpers/api.ts`)
  — logowanie ma limit 30/min, a jedno logowanie na test wyczerpywało go
  w połowie zestawu.
- **Przeglądy** na scalonym drzewie (commit `fe8ec0ced`): bezpieczeństwo,
  backend, frontend i przegląd adwersarialny „persona × trasa” (wzorzec
  bramek sprzed przepięcia porównany trasa po trasie; poza zamierzonymi
  zmianami żadna persona nie zyskała trasy). Znalezione i naprawione:
  - budżet linii wpisany kwotą pozwalał odczytać stawkę z przeliczonej
    liczby MD; sama „zmiana kwot” przechodziła bramkę zapisu kolejki zamówień
    z maila (przegląd pakietu zamówień);
  - kreator metryk pulpitu liczył kwoty po roli Delivery Leada, a zapis
    warunków kontraktowych klienta ekran bramkował edycją klientów (frontend);
  - skutki podpisanego dokumentu w kontrakcie nie sprawdzały już zapisu
    w sekcji Delivery (backend);
  - data końca pozwalała osobie bez „zmiany statusu” zakończyć albo przywrócić
    współpracę (adwersarialny);
  - nadana pozycja „Rekrutacje” dawała zapis widełek wynagrodzenia, których
    Delivery Lead nie ustawia; nadania przeżywały zmianę roli na Viewera
    (bezpieczeństwo).
  Dane produkcji sprawdzone odczytem 02.10.2026: wyjątków sekcji i nadań per
  osoba jest 0, wiersz podpisu TAC nie był zmieniany z panelu — migracja
  nikomu nie odbiera dostępu i wyłącza podpis TAC.

## Po wdrożeniu — po stronie administratora

Zaznaczyć kontu ze zgłoszenia dwie pozycje w oknie „Edytuj użytkownika” →
„Dodatkowe uprawnienia” (decyzja Artura 02.10.2026):

- „Kontrakty i zamówienia: tworzenie i edycja” — zakładanie i prowadzenie
  kontraktów oraz zamówień;
- „Stawki i kwoty: podgląd” — bez niej przycisk „Nowe zamówienie” i formularze
  zamówień się nie pokazują, bo niosą stawki i PDF zamówienia.

Z tym kompletem konto zakłada kontrakt (bez kwot kontraktu — te zmienia
„Stawki i kwoty: zmiana”, czyli Finanse) oraz zamówienia ze stawkami i PDF-em
u wszystkich klientów. Połączenie obu pozycji u Talent Community Managera
pilnuje `test_order_editor_needs_amounts_view_for_amounts_and_files`.
Nadanie robi człowiek, nie migracja — wpis w Historii zdarzeń ma mieć autora,
a stałe id w migracji działałoby też na bazach testowych.

## Poza zakresem (świadomie)

- Ekran dla Sourcing / Pipeline / Insights i poziomów Generatora B2B.
- Eksporty POST jako żądania „tylko do odczytu” (dziś wymagają zapisu
  w Delivery).
- Uprawnienia w tokenie JWT (wystarcza bramka strony).
- Przegląd tabeli `rbac_permission_audit` w UI (wpisy trafiają do Historii
  zdarzeń).

## Znalezione przy okazji (nie naprawione tutaj)

- Kolejka przeglądu DL zostaje przy roli: Delivery Lead z wyłączonym
  uprawnieniem do wysyłki CV nadal dostaje karty „do wysłania”, a osoba
  z nadanym uprawnieniem bez roli DL kolejki nie ma.
- Tygodniowy mail KPI filtruje dostęp do Insights z wartości domyślnych, nie
  z zapisanej polityki (stan sprzed tej zmiany).
- „Mamy championa” i „Oznacz jako zatrudnionego” zostały przy rolach.
- Okno relacji kluczowych wysyła puste notatki przy każdym zapisie (ten sam
  wzorzec, który w oknie edycji klienta został naprawiony).
- W kilku starszych komunikatach frontu zostało „Twoja rola…”.
- Finanse widzą pole daty końca i „Przedłuż” także na kontrakcie
  „Zakończonym”; serwer odmawia z nazwą uprawnienia. Ekran mógłby te akcje
  chować tak jak listę statusu.
- `require_financial_access` i `require_contract_legal_access` nie mają już
  użycia w trasach (zostały z własnymi testami).
