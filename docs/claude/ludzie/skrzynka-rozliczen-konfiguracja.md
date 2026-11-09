# Skrzynka rozliczeń `rozliczenia@` — uruchomienie czytnika (M365, zmienna, sprawdzenie)
<!-- indeks: CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX, cp_mailbox_state, czytnik rozliczeń, Application Mail.Read, RBAC for Applications, NEXUS Kadry, portal konsultanta, dokumenty z maila, cp_documents channel mailbox -->

Instrukcja z 09.11.2026 (roadmapa rozliczeń klientów, punkt E0.4). Konfigurację w M365 robi
administrator tenanta; NEXUS potrzebuje tylko jednej zmiennej. Kod: `app/services/consultant_portal/mailbox.py`,
pętla `consultant_portal_mailbox` w `app/tasks/hr_loops.py` (co 15 min, pierwszy bieg przy starcie
kontenera), reguły portalu w `portal-konsultanta.md`.

## Co robi czytnik i czego nie robi

- Czyta wyłącznie folder **Inbox** skrzynki z `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` przez Graph
  app-only rejestracji **„NEXUS Kadry”** (`HR_M365_CLIENT_ID` / `HR_M365_CLIENT_SECRET`, tenant
  `M365_MAIL_TENANT_ID`). Niczego w skrzynce nie zmienia: nie oznacza jako przeczytane, nie przenosi.
  Potrzebuje więc tylko `Mail.Read`.
- Bierze maile z załącznikami, nadawcę dopasowuje po `contracts.candidate_email`. Plik trafia do
  `cp_documents` z `channel = 'mailbox'` i statusem `received` (zawsze czeka na decyzję Finansów, bo
  adres nadawcy da się podrobić).
- Pierwszy bieg czyta 3 dni wstecz, potem od znacznika `last_seen_received_at` z zakładką 2 h,
  najwyżej 200 wiadomości na bieg.
- Portal w stanie `off` = czytnik kończy się przed odczytem zmiennej i nie woła Graphu. Samo ustawienie
  zmiennej niczego nie uruchamia.

## Stan na 09.11.2026 (odczyt read-only produkcji)

| Co | Stan |
|---|---|
| `HR_PROGRAM_ENABLED`, `HR_LOOPS_ENABLED` | `true`, `true` — pętla startuje |
| `app_settings['consultant_portal']` | brak wiersza = `off` |
| moduł `back_office` w `app_settings['hr_modules']` | brak klucza = wyłączony |
| `cp_mailbox_state` | 0 wierszy (czytnik nigdy nie doszedł do skrzynki) |
| `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` | według zadania nieustawiona; spoza białej listy `prod_readonly.py env`, **niepotwierdzone** |

**Niepotwierdzone** (nie da się sprawdzić z repo ani z bazy):
- czy `rozliczenia@b2bnetwork.pl` istnieje i czym jest (skrzynka współdzielona, lista dystrybucyjna,
  skrzynka na hostingu) — domena przyjęta jak przy `zgody@` i `zamowienia@`;
- czy wskaźnik service principal „NEXUS Kadry” w Exchange nadal ma przypisania z 18.10.2026
  (`runbook-przelaczenia-z-compassa.md`, sekcja 0) i czy sekret rejestracji jest ważny
  (`HR_M365_CLIENT_SECRET_EXPIRES_ON`, sonda `hr_m365` w `/api/health`).

## 1. M365 / Exchange (administrator tenanta)

### 1a. Skrzynka

```powershell
Connect-ExchangeOnline
Get-Recipient rozliczenia@b2bnetwork.pl | Format-List Name,RecipientTypeDetails,PrimarySmtpAddress
```

- **Brak adresu** → skrzynka współdzielona bez licencji i bez hasła:
  `New-Mailbox -Shared -Name "NEXUS Rozliczenia" -PrimarySmtpAddress rozliczenia@b2bnetwork.pl`.
- **`SharedMailbox` / `UserMailbox`** → zostaje; do zmiennej idzie jej `PrimarySmtpAddress`.
- **`MailUniversalDistributionGroup`** (jak `zamowienia@`) → Graph nie czyta listy. Zrób skrzynkę
  współdzieloną, np. `nexus-rozliczenia@b2bnetwork.pl`, dodaj ją jako członka listy
  (`Add-DistributionGroupMember`) i do zmiennej wpisz adres skrzynki, nie listy. Lista musi przyjmować
  pocztę z zewnątrz: `Set-DistributionGroup rozliczenia@b2bnetwork.pl -RequireSenderAuthenticationEnabled $false`.
- **Skrzynka na hostingu poza M365** → czytnik jej nie przeczyta; najpierw przenieść adres do Exchange Online.

Reguły Outlooka, które przenoszą maile z Inbox do podfolderów, wyłącz — czytnik ich nie zobaczy.

### 1b. Dostęp tylko do odczytu, tylko do tej skrzynki

Uprawnienie nadajesz **wyłącznie w Exchange RBAC for Applications**. W Entra ID rejestracja „NEXUS Kadry”
ma mieć nadal tylko `User.Read.All` — aplikacyjne `Mail.Read` dodane w Entra działałoby na każdą skrzynkę
w firmie, a granty Entra i Exchange się sumują.

Wariant zalecany: osobny zakres z samym `Application Mail.Read`. Grupa „NEXUS Kadry - skrzynki”
(`nexus-kadry-skrzynki@b2bnetwork.pl`) daje oprócz odczytu także `Mail.Send`,
`MailboxSettings.ReadWrite` i `Calendars.ReadWrite`, a czytnik rozliczeń potrzebuje tylko odczytu.

```powershell
# AppId rejestracji „NEXUS Kadry” = wartość HR_M365_CLIENT_ID (wskaźnik istnieje od 18.10.2026)
Get-ServicePrincipal | Where-Object DisplayName -like "NEXUS Kadry*" | Format-List DisplayName,AppId,ObjectId

New-ManagementScope -Name "NEXUS Kadry - rozliczenia" `
  -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'rozliczenia@b2bnetwork.pl'"

New-ManagementRoleAssignment -Name "NEXUS Kadry - rozliczenia - Mail.Read" `
  -Role "Application Mail.Read" -App <AppId> -CustomResourceScope "NEXUS Kadry - rozliczenia"
```

Przy wariancie z listą dystrybucyjną w filtrze stoi adres skrzynki współdzielonej, nie listy.
Jeśli `-App <AppId>` zostanie odrzucone, podaj `ObjectId` z `Get-ServicePrincipal` (składnia nie była
próbowana na tym tenancie).

Wariant prostszy, jak przy `zgody@`: `Add-DistributionGroupMember -Identity nexus-kadry-skrzynki@b2bnetwork.pl
-Member rozliczenia@b2bnetwork.pl`. Działa od razu na istniejących przypisaniach, ale daje aplikacji na tej
skrzynce także wysyłkę i zmianę ustawień.

Sprawdzenie (przypisania RBAC propagują się od 30 min do 2 h):

```powershell
Test-ServicePrincipalAuthorization -Identity <AppId> -Resource rozliczenia@b2bnetwork.pl
#  → wiersz "Application Mail.Read", InScope = True
Test-ServicePrincipalAuthorization -Identity <AppId> -Resource <dowolna skrzynka spoza zakresów>
#  → "Application Mail.Read" z zakresu "NEXUS Kadry - rozliczenia": InScope = False
```

Test RBAC nie widzi grantów Entra, więc osobno: Entra ID → App registrations → „NEXUS Kadry” →
API permissions — brak `Mail.Read` typu Application.

### 1c. Próba dostarczenia

Mail z dowolnej skrzynki (także spoza firmy) z PDF-em w załączniku ląduje w Inbox `rozliczenia@`.
Skrzynka nowa albo z wyczyszczonym Inbox: pierwszy bieg czyta 3 dni wstecz.

## 2. Zmienna w NEXUSIE (workflow „Coolify set env”)

Jedna zmienna, wartość to goły adres skrzynki (bez nazwy, cudzysłowów i spacji). To nie sekret, więc
idzie przez `value`, nie `value_from_secret`.

```bash
env -u GH_TOKEN gh workflow run "Coolify set env" --repo B2B-net-S-A/NEXUS --ref main -f key=CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX -f value=rozliczenia@b2bnetwork.pl -f redeploy=false
```

Przy wariancie z listą dystrybucyjną wartością jest adres skrzynki współdzielonej. Zmienna wchodzi do
kontenera przy najbliższym zwykłym wdrożeniu w oknie (pon–pt 18:00–08:00, weekend o każdej porze);
`emergency` ani `redeploy=true` nie są potrzebne. Nic innego nie trzeba ustawiać: poświadczenia
„NEXUS Kadry” i `M365_MAIL_TENANT_ID` są od 18.10.2026.

Wyłączenie czytnika: ta sama komenda z `-f value=` (pusta) i wdrożenie, albo portal w stanie `off`.

## 3. Sprawdzenie po wdrożeniu

Najpierw `/api/health` → `version` = SHA z maina z tego wdrożenia. Stan czytnika z bazy
(`~/.claude/nexus-rutyny/bin/prod_readonly.py sql`):

```sql
SELECT last_run_at, last_status, last_error, last_seen_received_at FROM cp_mailbox_state;
SELECT channel, status, contract_id IS NOT NULL AS przypisany, period_year, period_month, period_guessed, created_at
FROM cp_documents WHERE channel = 'mailbox' ORDER BY created_at DESC LIMIT 20;
```

Trasa `GET /api/back-office/portal/status` zwraca to samo w polu `mailbox` (`configured`, `last_run_at`,
`last_status`, `last_error`), ale tylko przy włączonym module `back_office` i tylko członkowi zespołu
Finansów albo kierownikowi back office; dziś modułu nie ma, więc zostaje SQL.

### Czego oczekiwać w każdym stanie portalu

| Stan portalu | `cp_mailbox_state` | `cp_documents` z maila |
|---|---|---|
| `off` (dziś) | bez zmian (0 wierszy); Graph nie jest wołany. **Tego stanu nie da się użyć do sprawdzenia skrzynki.** | nic |
| `pilot` | do 15 min po przełączeniu: `last_status = 'ok'`, `last_error` NULL, `last_seen_received_at` = najnowszy mail z Inbox | tylko maile od adresu z kontraktu z aktywnym panelem (`cp_activations`); reszta jest pomijana. Bez modułu `back_office` dokument nie ma karty u Finansów — widać go w bazie |
| `all` bez modułu `back_office` | jak `off` | nic |
| `all` z modułem | jak w `pilot` | każdy mail z załącznikiem; nieznany nadawca = `contract_id` NULL i karta do ręcznego przypisania w kolumnie `invoice` zespołu Finansów. Pierwszy bieg obejmie 3 dni wstecz, więc Inbox przed przełączeniem powinien być pusty |

Przełączenie stanu to decyzja administratora (`PUT /api/consultant-panel/settings`, przełącznik na
karcie panelu kontraktu). Do sprawdzenia skrzynki wystarczy `pilot` z jednym aktywowanym kontraktem,
którego adres należy do osoby wysyłającej próbny mail.

### Błędy w `cp_mailbox_state`

| `last_status` / `last_error` | Przyczyna | Co zrobić |
|---|---|---|
| `disabled` / `no_mailbox` | zmienna pusta w kontenerze | sprawdzić bieg „Coolify set env” i czy po nim było wdrożenie |
| `error` / `no_token` | brak lub wygasły sekret „NEXUS Kadry” (`HR_M365_CLIENT_SECRET`) | rotacja sekretu według `runbook-przelaczenia-z-compassa.md` |
| `error` / `http_403` | brak przypisania RBAC albo jeszcze się nie rozeszło | `Test-ServicePrincipalAuthorization` z kroku 1b; odczekać do 2 h |
| `error` / `http_404` | zły adres albo lista dystrybucyjna zamiast skrzynki | krok 1a |
| `partial` | jedna wiadomość padła; znacznik zatrzymał się przed nią i następny bieg spróbuje ponownie | log `consultant_portal_mailbox: message failed (<klasa błędu>)` |

Udany bieg zostawia w logu backendu `consultant_portal_mailbox done {...}` z licznikami `messages`,
`created`, `skipped`, `failed` (bez adresów i tematów).
