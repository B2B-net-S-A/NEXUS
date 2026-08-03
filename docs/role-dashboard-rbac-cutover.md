# Dashboardy ról i cutover RBAC

## Cel

NEXUS ma jeden kanoniczny dashboard v2, ale prezentuje go przez pięć presetów
wynikających z persony i capability użytkownika. Backend jest źródłem prawdy dla
zakresu danych; frontend wybiera wyłącznie spośród presetów zwróconych przez
`/api/auth/me`.

| Persona | Preset | Główny zakres | Najważniejsze elementy | Granice |
| --- | --- | --- | --- | --- |
| Admin | `admin-ops` | cała organizacja | gotowość systemu, drift schematu, workery, integracje, alerty i kolejka operacyjna | pełny dostęp administracyjny |
| Delivery Lead | `delivery-lead` | przypisani klienci i pary klient–TAC | otwarte requesty/wakaty, SLA pierwszej rekomendacji, fill rate, placementy, tablica ryzyk | bez stawek, marży, faktur i innych danych finansowych |
| Head of Recruitment | `head-of-recruitment` | organizacja rekrutacyjna | priorytetowe wakaty, obciążenie, capacity, SLA, konwersja, placementy, tablica zespołu | bez finansów; zarządza kompetencjami i odpowiedzialnościami zespołu |
| Sourcer / TAC / Rekruter | `my-work` | własna praca | realizacja planu, zaległe działania, telefony, weryfikacje, rekomendacje, placementy i kolejka działań | role pozostają technicznie odrębne; hybryda dostaje sumę capability |
| Finanse | `finance` | dane finansowe organizacji | MRR, marża, należności, przeterminowania, forecast, wykorzystanie i wyjątki | rola ekskluzywna; bez danych kandydatów i PII rekrutacyjnego |

Każda sekcja dashboardu ma własny status jakości danych. Brak lub opóźnienie
źródła jest raportowane jako `partial`, `stale` albo `unavailable`, nigdy jako
fałszywe zero.

## Reguły ról

- `admin`, `head_of_recruitment`, `delivery_lead`, `tac`, `recruiter` i
  `sourcer` mogą tworzyć persony hybrydowe; uprawnienia są sumą capability.
- `finance` jest zawsze rolą pojedynczą i ekskluzywną.
- Legacy `user` nie może być już nadawany. Istniejące konta `user` przechodzą na
  `recruiter` i muszą ukończyć onboarding.
- Nowe konta z dozwolonej domeny, zarówno przez rejestrację email/hasło, jak i
  pierwszy login Microsoft SSO, powstają jako `recruiter` za obowiązkowym
  onboardingiem.
- Każda zmiana ról lub aktywności zwiększa `authorization_version` i ustawia
  `tokens_valid_after`, dzięki czemu istniejące access/refresh JWT oraz sesje WS
  nie zachowują starych praw.

## Migracja `0210_role_dashboard_rbac_cutover`

Migracja wykonuje atomowy cutover danych i zapisuje marker
`0210_role_dashboard_rbac_cutover` w `app_settings`. `backend/entrypoint.sh`
zawiera idempotentne lustro dla środowisk, w których Alembic historycznie nie
dochodził do bieżącego heada.

1. Dodaje enum `finance`, tabele audytu/reconciliation i kolumny wersji
   autoryzacji.
2. Zapisuje pre-cutover snapshot roli, profilu, sekcji i stanu sesji każdego
   użytkownika.
3. Normalizuje tablicę `roles`, migruje `user` do `recruiter`, a Finance do
   wyłącznej roli `finance`.
4. Usuwa aktywne relacje rekrutacyjne Finance, czyści właścicieli requestów i
   kontaktów, wyłącza alerty zapisanych wyszukiwań oraz usuwa rekrutacyjne
   powiadomienia. Historyczne autorstwo i ślady audytowe pozostają.
5. Unieważnia wszystkie istniejące sesje i oczekujące kody wymiany SSO.
6. Dodaje TAC-centryczny priorytet klienta i kolejkę jawnej rekonsyliacji.
7. Normalizuje kompetencje do dokładnie jednego możliwego primary; niejednoznaczne
   przypadki zachowuje jako secondary i zapisuje do kolejki rekonsyliacji.

Downgrade jest wyłącznie strukturalny. Nie odtwarza usuniętych relacji Finance
ani sesji; rollback danych wymaga restore albo kontrolowanego forward-fix na
podstawie tabel audytowych.

## Relacje po cutoverze

### Klient–TAC i właściciel requestu

- Klient może mieć wielu równorzędnych TAC-ów.
- Legacy `client_tac_assignments.is_primary` pozostaje na czas expand/contract
  dla starszych podów i powiadomień, ale nie wybiera właściciela nowego requestu.
- `is_first_priority_for_tac` oznacza osobisty klient numer 1 danego TAC-a:
  maksymalnie jeden klient na TAC-a, natomiast ten sam klient może być
  priorytetem wielu TAC-ów.
- Przy dokładnie jednym aktywnym TAC-u klienta nowy request może dostać go
  automatycznie. Przy wielu TAC-ach API wymaga jawnego `tac_id` i zwraca
  `TAC_OWNER_REQUIRED`, zamiast wybierać arbitralnie.
- Zmiana lub usunięcie bieżącego priorytetu z alternatywami wymaga wskazania
  następcy i odbywa się w jednej transakcji.

### Kompetencje

- Docelowo każdy aktywny Sourcer/TAC/Rekruter z przypisaniami ma jedną
  kompetencję primary (`priority=1`) oraz zero lub więcej secondary
  (`priority=2`). Niejednoznaczny rekord może przejściowo nie mieć primary,
  dopóki Head of Recruitment lub Admin nie rozstrzygnie kolejki rekonsyliacji.
- `is_primary` jest lustrzanym polem zgodnym z `priority=1`.
- UI zapisuje primary i secondary jednym atomowym requestem.
- Stara relacja TAC→Delivery Lead nie jest już edytowana w UI. Zakres Delivery
  Leada wynika z relacji DL→klient oraz klient→TAC; nadzór organizacyjny należy
  do Head of Recruitment.

## Finance i Microsoft 365

Przejście konta do Finance uruchamia ten sam cleanup także przy późniejszej
zmianie ręcznej, resynchronizacji AAD oraz loginie SSO. Połączenie M365 pozostaje
w bazie bez mutacji, ale wszystkie endpointy, webhooki i workery ponownie
wczytują właściciela i odmawiają dostępu do Graph, gdy aktualna rola nie ma
capability domeny kandydatów. Zadania mailowe kończą się wtedy jako `skipped`,
bez retry i bez powiadomienia zawierającego PII.

## Kryteria wydania

- Alembic ma dokładnie jeden head: `0210_role_dashboard_rbac_cutover`.
- Trzykrotny `alembic upgrade heads` na świeżej bazie przechodzi idempotentnie.
- Pełne backendowe pytest, Ruff i import aplikacji przechodzą w CI.
- Frontend przechodzi ESLint, type-check, Vitest i build.
- Po deployu `/api/health` raportuje SHA merge commita.
- W produkcji należy sprawdzić przez impersonację: pięć presetów, brak finansów
  u Delivery Leada, brak PII u Finance, dostęp HoR do kompetencji oraz jawny
  wybór TAC-a przy kliencie z wieloma przypisaniami.
- Otwarte rekordy `rbac_relationship_reconciliation` muszą zostać rozstrzygnięte
  przez uprawnionego Admina lub Head of Recruitment; migracja nie zgaduje
  decyzji biznesowych.
