# Jedna skrzynka wsparcie@ — rozliczenia@ i administracja@ wchodzą do niej, potem znikają
<!-- indeks: wsparcie@, rozliczenia@, administracja@, jedna skrzynka, alias, proxyAddresses, przekierowanie, CONSULTANT_PORTAL_MAILBOX, CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX, ADMIN_CASES_MAILBOX, ADMIN_CASES_M365_MAILBOX, cp_mailbox_state, admin_mail_ingest_state, czytnik spraw, czytnik rozliczeń, RBAC for Applications, NEXUS Kadry, wygaszenie adresów -->

## Reguła

Decyzja Artura z 09.11.2026: docelowo jest **jedna skrzynka `wsparcie@b2bnetwork.pl`** i wszystkie
sprawy (tickety) od konsultantów wchodzą przez nią. `rozliczenia@`, `administracja@` i inne adresy
wsparcia na czas przejścia są aliasami albo przekierowaniami do `wsparcie@`, a potem znikają.

- Nowy kod i nowe treści podają `wsparcie@`. Nie dopisuj nowego miejsca z `rozliczenia@` ani
  `administracja@`.
- NEXUS rozróżnia rozliczenia od spraw po adresie, na który ktoś napisał (nagłówek `To`/`Cc`),
  dlatego przejście musi ten adres zachować (niżej).
- Czytniki łączy jeden router: etap E8 roadmapy rozliczeń (`docs/rozliczenia-klientow-roadmapa.md`
  na gałęzi `claude/nexus-rozliczenia-przejecie-804835`). Do tego czasu na jedną skrzynkę patrzy
  najwyżej jeden czytnik.
- Stary adres znika dopiero wtedy, gdy nie podaje go żaden kod, szablon ani **obowiązująca umowa**.
  Podpisane umowy B2B wskazują `administracja@` jako adres zawiadomień, a część z nich
  `rozliczenia@` jako adres raportów. Alias nic nie kosztuje, więc zostaje, dopóki takie umowy działają.

## Stan na 09.11.2026 (odczyt read-only produkcji i DNS)

| Co | Stan |
|---|---|
| MX `b2bnetwork.pl` | `hosting.b2bnetwork.pl` (home.pl); SPF obejmuje też `spf.protection.outlook.com` |
| `administracja@` | skrzynka na home.pl, ludzie czytają ją tam; NEXUS miał dostawać kopię w skrzynce M365 (wariant B, `opieka-mapa-technologii-i-sprawy.md`) |
| czytnik spraw (`admin_cases_mail_ingest`) | `ADMIN_CASES_MAIL_INGEST_ENABLED=false`, `admin_mail_ingest_state` pusty, 0 spraw z maila (654 sprawy ręczne i z importu) |
| czytnik rozliczeń (`consultant_portal_mailbox`) | portal `off` (brak wiersza `app_settings['consultant_portal']`), `cp_mailbox_state` pusty |
| `HR_PROGRAM_ENABLED`, `HR_LOOPS_ENABLED` | `true`, `true` — pętle startują, każda ma własny wyłącznik |
| moduł `back_office` | wyłączony (brak klucza w `app_settings['hr_modules']`) |
| adresy w treściach w bazie (`app_settings`, `email_templates`, `lifecycle_template_items`) | 0 trafień |

Żaden czytnik nie czyta dziś poczty, więc przejście nie ma czego zepsuć po stronie NEXUSA.

**Niepotwierdzone** (nie widać z repo, bazy ani DNS):
- jak poczta z zewnątrz dochodzi do skrzynek M365, skoro MX wskazuje home.pl (przekierowanie
  na home.pl na adres `…@<tenant>.onmicrosoft.com`? osobna domena trasowania?) — od tego zależy,
  czy alias w Exchange w ogóle zobaczy maile od konsultantów;
- czy `wsparcie@` jest skrzynką M365 (współdzieloną) i czy jest już w grupie `NEXUS-Meetings-Scope`
  (wymaga tego organizator rozmów, `portal-konsultanta.md`);
- czy `rozliczenia@` istnieje i gdzie (home.pl, Exchange, lista dystrybucyjna);
- czy skrzynka z kopią administracji (wariant B) powstała i jak się nazywa;
- czy przy przekierowaniu z home.pl zostaje oryginalny nagłówek `To` (sprawdzenie w kroku 1d).

## 1. M365 i home.pl (bez kodu)

### 1a. Najpierw ustal trasę poczty z zewnątrz

MX jest na home.pl, więc mail od konsultanta trafia najpierw tam. Sprawdź w panelu home.pl, co dzieje
się z `wsparcie@`, `rozliczenia@` i `administracja@`: skrzynka na home.pl, przekierowanie (dokąd)
albo brak adresu. Exchange obsłuży alias tylko dla poczty, która do niego dojdzie.

### 1b. Jak stare adresy mają trafiać do wsparcie@

| Sposób | Gdzie | Nagłówek `To` | Kiedy |
|---|---|---|---|
| **Alias** — dodatkowy adres w `EmailAddresses` (proxyAddresses) skrzynki `wsparcie@` | Exchange: `Set-Mailbox wsparcie@b2bnetwork.pl -EmailAddresses @{add="smtp:rozliczenia@b2bnetwork.pl"}` | zostaje oryginalny (`rozliczenia@…`); Graph pokazuje go w `toRecipients` | zalecany, gdy adres nie istnieje jako osobny odbiorca w Exchange (alias nie może być zajęty przez inną skrzynkę ani listę) |
| **Przekierowanie na home.pl** (adres na home.pl przesyła dalej do `wsparcie@`) | panel home.pl | zwykle zostaje oryginalny, bo przekierowanie zmienia tylko kopertę — **niepotwierdzone dla home.pl** | gdy adres musi zostać na home.pl (dziś `administracja@`, gdzie czytają go ludzie) |
| **Przekazywanie skrzynki w Exchange** (`ForwardingAddress` na starej skrzynce) | Exchange | zostaje oryginalny | gdy stara skrzynka w Exchange musi jeszcze chwilę istnieć |
| Reguła Outlooka „Przekaż” | — | **traci** oryginał: nowy mail od skrzynki, nadawca podmieniony | nie używać; „Przekieruj” (redirect) zachowuje nagłówki, ale zależy od skrzynki osoby |

Mail wysłany w ukrytej kopii (UDW) nie ma starego adresu w żadnym nagłówku, który NEXUS czyta
(`toRecipients`, `ccRecipients`); taki mail router uzna za sprawę.

Kolejność dla `administracja@`: dopóki ludzie czytają ją na home.pl, przekierowanie z kopią
zostawioną na home.pl (jak wariant B, tylko celem jest `wsparcie@`). Alias w Exchange dopiero po
przeniesieniu adresu z home.pl.

### 1c. Uprawnienia rejestracji „NEXUS Kadry” do wsparcie@

Oba czytniki i odpowiedzi ze spraw idą przez rejestrację „NEXUS Kadry” (`acquire_hr_token`).
Na `wsparcie@` potrzebne są:

| Uprawnienie (Exchange RBAC for Applications) | Po co |
|---|---|
| `Application Mail.Read` | czytnik spraw i czytnik rozliczeń (folder Inbox) |
| `Application Mail.Send` | odpowiedź ze sprawy (`POST /users/{upn}/messages/{id}/reply`), komunikaty do konsultantów i mail powitalny z tej skrzynki, linki z portalu (`portal_mail`) |

Kalendarz `wsparcie@` (organizator rozmów z portalu) to osobna rejestracja „NEXUS Teams Prep” i grupa
`NEXUS-Meetings-Scope` — bez zmian.

Uprawnienia nadajesz **wyłącznie w Exchange**. W Entra ID „NEXUS Kadry” ma mieć nadal tylko
`User.Read.All`: aplikacyjne `Mail.Read` albo `Mail.Send` w Entra działałyby na każdą skrzynkę
w firmie, a granty Entra i Exchange się sumują.

Zawężenie do jednej skrzynki — osobny zakres z dwiema rolami:

```powershell
Connect-ExchangeOnline
# AppId = wartość HR_M365_CLIENT_ID; wskaźnik service principal istnieje od 18.10.2026
Get-ServicePrincipal | Where-Object DisplayName -like "NEXUS Kadry*" | Format-List DisplayName,AppId,ObjectId

New-ManagementScope -Name "NEXUS Kadry - wsparcie" `
  -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'wsparcie@b2bnetwork.pl'"
New-ManagementRoleAssignment -Name "NEXUS Kadry - wsparcie - Mail.Read" `
  -Role "Application Mail.Read" -App <AppId> -CustomResourceScope "NEXUS Kadry - wsparcie"
New-ManagementRoleAssignment -Name "NEXUS Kadry - wsparcie - Mail.Send" `
  -Role "Application Mail.Send" -App <AppId> -CustomResourceScope "NEXUS Kadry - wsparcie"
```

Prostszy wariant: `Add-DistributionGroupMember -Identity nexus-kadry-skrzynki@b2bnetwork.pl -Member
wsparcie@b2bnetwork.pl`. Ta grupa daje dodatkowo `MailboxSettings.ReadWrite` i `Calendars.ReadWrite`,
których `wsparcie@` w NEXUSIE nie potrzebuje. Jeśli `-App <AppId>` zostanie odrzucone, podaj
`ObjectId` z `Get-ServicePrincipal` (składnia nie była próbowana na tym tenancie).

Sprawdzenie (przypisania rozchodzą się od 30 min do 2 h):

```powershell
Test-ServicePrincipalAuthorization -Identity <AppId> -Resource wsparcie@b2bnetwork.pl
#  → "Application Mail.Read" i "Application Mail.Send": InScope = True
Test-ServicePrincipalAuthorization -Identity <AppId> -Resource <skrzynka spoza zakresów>
#  → obie role z zakresu "NEXUS Kadry - wsparcie": InScope = False
```

Test RBAC nie widzi grantów Entra, więc osobno: Entra ID → App registrations → „NEXUS Kadry” →
API permissions — bez `Mail.Read` i `Mail.Send` typu Application.

### 1d. Próba: czy adres odbiorcy przetrwał

Z konta spoza firmy wyślij po jednym mailu na `wsparcie@`, `rozliczenia@` i `administracja@`.
W Outlooku na `wsparcie@`: wszystkie trzy są w Inbox, a w nagłówku „Do” stoi adres, na który je
wysłano. Pełne nagłówki: Plik → Właściwości → Nagłówki internetowe. Jeśli „Do” pokazuje
`wsparcie@` albo adres `onmicrosoft.com`, przekierowanie przepisało nagłówek — wtedy router E8 nie
rozróżni rozliczeń i trzeba zmienić sposób z tabeli 1b.

## 2. Zmienne (workflow „Coolify set env”)

| Zmienna | Dziś czyta | Rola |
|---|---|---|
| `CONSULTANT_PORTAL_MAILBOX` (`config.py:1603`) | `portal_mail`, `meetings` | nadawca linków z portalu i organizator rozmów (`wsparcie@`) |
| `ADMIN_CASES_MAILBOX` (`config.py:1638`) | `admin_cases/mailbox.public_address` | adres widoczny: autoodpowiedź urlopowa, Reply-To komunikatów i maila powitalnego, ekrany |
| `ADMIN_CASES_M365_MAILBOX` (`config.py:1639`) | `admin_cases/mailbox.m365_mailbox`, czytnik spraw (`hr_loops.py:96`) | skrzynka, którą czyta czytnik spraw i z której wysyłają komunikaty i odpowiedzi; pusta = `ADMIN_CASES_MAILBOX` |
| `ADMIN_CASES_MAIL_INGEST_ENABLED` | czytnik spraw | wyłącznik czytnika spraw (dziś `false`) |
| `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` (`config.py:1605`) | czytnik rozliczeń (`consultant_portal/mailbox.py`) | skrzynka dokumentów; czytnik działa tylko przy portalu `pilot`/`all` |

### Ryzyko: dwa czytniki na jednej skrzynce

Oba czytniki czytają ten sam folder Inbox, każdy z własnym znacznikiem (`admin_mail_ingest_state`,
`cp_mailbox_state`), i żaden nie zmienia skrzynki (nie oznacza jako przeczytane, nie przenosi).
Jeśli `ADMIN_CASES_M365_MAILBOX` i `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` wskażą `wsparcie@`:

- każdy mail z załącznikiem od konsultanta z aktywnym panelem stanie się **i** sprawą, **i**
  dokumentem do decyzji Finansów (dwie osoby zajmą się tym samym);
- w stanie portalu `all` każdy mail z załącznikiem od nieznanego nadawcy da sprawę i kartę do
  przypisania;
- czytnik spraw zakłada sprawę z **każdej** nowej wiadomości, więc wszystkie raporty i faktury
  zrobią się sprawami.

### Bezpieczny stan przejściowy (do routera E8)

Na `wsparcie@` patrzy najwyżej jeden czytnik — **czytnik spraw**:

```bash
env -u GH_TOKEN gh workflow run "Coolify set env" --repo B2B-net-S-A/NEXUS --ref main -f key=ADMIN_CASES_M365_MAILBOX -f value=wsparcie@b2bnetwork.pl -f redeploy=false
```

```bash
env -u GH_TOKEN gh workflow run "Coolify set env" --repo B2B-net-S-A/NEXUS --ref main -f key=CONSULTANT_PORTAL_MAILBOX -f value=wsparcie@b2bnetwork.pl -f redeploy=false
```

- `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` zostaje **pusta**. Raporty i faktury z maila są wtedy
  sprawami (ręczna obsługa); w panelu konsultanta dokumenty idą kanałem portalu jak dotąd.
- `ADMIN_CASES_MAILBOX` (adres widoczny) zmieniasz na `wsparcie@` dopiero wtedy, gdy ludzie
  czytają `wsparcie@` zamiast `administracja@` na home.pl — to ten adres widzą konsultanci
  w autoodpowiedziach i jest w Reply-To.
- `ADMIN_CASES_MAIL_INGEST_ENABLED=true` włączasz osobno, po próbie z kroku 1d.
- Zmiana skrzynki zeruje znacznik czytnika spraw (`_state` porównuje `mailbox`), więc pierwszy bieg
  weźmie ostatnie 3 dni Inbox `wsparcie@`. Jeśli są tam stare maile, które nie mają być sprawami,
  przenieś je z Inbox przed włączeniem.

Zmienne wchodzą przy najbliższym zwykłym wdrożeniu w oknie (pon–pt 18:00–08:00, weekend o każdej
porze); `emergency` i `redeploy=true` nie są potrzebne. Wycofanie: `ADMIN_CASES_MAIL_INGEST_ENABLED=false`
+ wdrożenie.

Po routerze E8 wszystkie trzy role czytają jedną zmienną; opis zmiennych zmieni wtedy PR etapu E8.

## 3. Sprawdzenie po wdrożeniu

`/api/health` → `version` = SHA z maina z tego wdrożenia; sonda `admin_cases_mail`
(`app/services/hr/health.py`) zgłasza błąd ostatniego przebiegu albo przebieg starszy niż 30 min,
a sonda `hr_m365` — problem z sekretem „NEXUS Kadry”.
Stan z bazy (`~/.claude/nexus-rutyny/bin/prod_readonly.py sql`):

```sql
SELECT mailbox, last_status, last_error, last_run_finished_at, last_received_at FROM admin_mail_ingest_state;
SELECT source, count(*) FROM admin_cases WHERE created_at > now() - interval '1 day' GROUP BY 1;
SELECT last_run_at, last_status, last_error, last_seen_received_at FROM cp_mailbox_state;
SELECT channel, status, count(*) FROM cp_documents WHERE channel = 'mailbox' GROUP BY 1, 2;
```

Czego oczekiwać w stanie przejściowym:

- czytnik spraw (co 5 min): `mailbox = wsparcie@b2bnetwork.pl`, `last_status = 'ok'`, mail próbny
  z kroku 1d = nowa sprawa z `source = 'mail'`. Błąd `http_403` = brak przypisania RBAC albo jeszcze
  się nie rozeszło; `no_token` = brak albo wygasły sekret „NEXUS Kadry”;
- czytnik rozliczeń: `cp_mailbox_state` bez zmian i 0 dokumentów z `channel = 'mailbox'`
  (zmienna pusta). Przy portalu `off` czytnik w ogóle się nie uruchamia; przy `pilot`/`all` zapisze
  `last_status = 'disabled'`, `last_error = 'no_mailbox'` — to oczekiwany stan, nie awaria.

Gdyby przed routerem E8 trzeba było włączyć czytnik rozliczeń, to tylko na **osobnej** skrzynce
(nie `wsparcie@`). Wtedy przy portalu `pilot` do 15 min: `last_status = 'ok'`, dokumenty tylko od
adresów z aktywowanych kontraktów; `all` bez modułu `back_office` działa jak `off`.

Decyzja Artura z 12.11.2026: czytnik rozliczeń rusza od rozliczenia listopada dla wszystkich
klientów (panel `all`), kroki w E7 roadmapy rozliczeń (`docs/rozliczenia-klientow-roadmapa.md`).
`CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` wskazuje wtedy skrzynkę rozliczenia@, **nigdy** `wsparcie@`,
dopóki nie ma routera E8. Jeśli rozliczenia@ jest już tylko aliasem `wsparcie@`, start czeka na E8.

## 4. Wygaszenie starych adresów — co zmienić wcześniej

Stan z grepu `origin/main` 09.11.2026. Pełne adresy w treściach, które dostają ludzie:

| Miejsce | Adres | Co to |
|---|---|---|
| `backend/app/templates/contract/umowa_b2b_pl.html:125`, `umowa_b2b_en.html:126` | `administracja@` | kontakt B2BNET w umowie B2B |
| `backend/app/services/b2b_documents/company_party.py:27` | `administracja@` | `notices_email` strony B2BNET w dokumentach B2B |
| `backend/app/services/b2b_contract_generator/clause_override_content.py:802`, `:854` | `rozliczenia@` | klauzula: raport do 3 dni po okresie na ten adres (PL i EN) |

Adresy bez domeny w napisach interfejsu (ok. 70 plików, bez testów i harnessów `/preview`):
„Sprawy administracja@” (`frontend/src/lib/api/hr.ts:230`, `permission-catalog.json:188`,
`app/people/cases/page.tsx`, `CareScreen.tsx`, `WorkBoard.tsx`), komunikaty do konsultantów
(`components/care/announcements/*`: „z administracja@”), mail powitalny (`WelcomeMailCard.tsx`),
dokumenty na karcie Finansów (`components/back-office/CardDocuments.tsx:22`: „z rozliczenia@”),
opisy w `backend/app/data/screen_guides/guides.json:1067`, `back_office/board.py:49`,
`welcome_mail.py`, `announcements.py:90`, `hr_mail.py`, `service.py:157` („Przypisano Ci sprawę
administracja@”), `notification_categories.py:105`, `notification_delivery.py:313`. Pełna lista:

```bash
git grep -n -E "(administracja|rozliczenia)@" origin/main -- backend/app frontend/src
```

Poza repo: podpisane umowy B2B (adres zawiadomień i raportów), podpisy i stopki w Outlooku zespołu,
strona firmy i materiały na start w portalu (`cp_faq_items` dziś bez trafień), autoodpowiedzi
ustawione ręcznie na home.pl.

Kolejność: (1) nowe umowy i treści na `wsparcie@`, (2) router E8, (3) alias albo przekierowanie
zostaje, dopóki działa jakakolwiek umowa ze starym adresem, (4) dopiero potem usunięcie adresu.
