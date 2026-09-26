# Prepy i follow-upy w Teams — konfiguracja Microsoft 365 (jednorazowo, administrator)

Kod i konfiguracja aplikacji są wdrożone. Od 26.09.2026 przełączniki
`TEAMS_PREP_APP_ONLY_ENABLED` i `TEAMS_PREP_TRANSCRIPTS_ENABLED` są włączone,
a `/api/health` zwraca `checks.teams_prep = healthy`. Ten wynik potwierdza
konfigurację; dowód nagrania i importu wymaga zakończonego spotkania z mową.

## Stan tenanta 26.09.2026

- Osobna aplikacja **NEXUS Teams Prep** została zarejestrowana.
  Administrator zatwierdził aplikacyjne `OnlineMeetings.ReadWrite.All`,
  `OnlineMeetingTranscript.Read.All`
  i `User.ReadBasic.All`. Nie ma delegowanego `User.Read` ani nieograniczonego
  `Calendars.ReadWrite` w Entra.
- Exchange App RBAC przyznał `Application Calendars.ReadWrite` przez zakres
  `NEXUS-TeamsPrep-Calendar-Scope` i grupę `NEXUS-Meetings-Scope`. Test dla
  `ewa.kalata@b2bnetwork.pl` zwrócił `InScope=True`, a dla
  `artur.twardowski@b2bnetwork.pl` `InScope=False`.
- Teams `Microsoft Graph access` dla transkryptów jest włączony. Polityka
  aplikacji `NEXUS-TeamsPrep-ApplicationAccess` i polityka spotkań
  `NEXUS-TeamsPrep-AutoRecording` są przypisane 13 organizatorom z aktywną
  skrzynką. Odczyt polityki potwierdził `AutoRecording=Enabled`,
  `AllowCloudRecording=True`, `AllowTranscription=True` i
  `ExplicitRecordingConsent=Enabled`. W porównaniu z ich poprzednią polityką
  globalną zmieniła się tylko wymagana zgoda uczestnika.
- Adres Wiktorii Deneki to `wiktoria.deneka@b2bnetwork.pl`. Wstępne
  sprawdzenie błędnego adresu `wiktoria.denka@...` dało fałszywy brak skrzynki;
  poprawny adres rozwiązuje się do `UserMailbox`.
- Sekrety obu osobnych aplikacji zapisano w GitHub Actions i Coolify.
  Wartości nie są zapisywane w repozytorium ani raportach. Wdrożenie
  [36243866470](https://github.com/B2B-net-S-A/NEXUS/actions/runs/36243866470)
  zakończyło się sukcesem; produkcja potwierdziła rewizję
  `300a535963878af59dd62d3c9713fe6134827c7f`.
- Test wysyłki systemowej
  [36243955101](https://github.com/B2B-net-S-A/NEXUS/actions/runs/36243955101)
  zwrócił Graph HTTP 202. Wiadomość od `nexus-powiadomienia@b2bnetwork.pl`
  dotarła do Outlooka właściciela o 15:04 CEST. Rutynowe powiadomienia nadal
  mają osobny przełącznik polityki; przywrócenie transportu nie włącza ich.
- Kontrolowany test pełnego przepływu nadal musi potwierdzić powstanie
  nagrania i import transkryptu. Sam odczyt polityk nie daje tego dowodu.

### Test dostępu Graph bez danych kandydata

Workflow `Coolify Ops` ma dwa działania dostępne wyłącznie z `main`:

- `teams-prep-config-audit`: uzyskuje token aplikacji i potwierdza dostęp do
  kalendarza Ewy oraz HTTP 403 dla Artura poza zakresem.
- `teams-prep-meeting-probe`: po tej samej kontroli tworzy jedno oznaczone
  spotkanie bez uczestników, sprawdza zapis i odczyt `recordAutomatically`
  oraz `allowTranscription`, a także odczyt listy transkryptów. Następnie
  odwołuje wyłącznie utworzone spotkanie. Nie dołącza do Teams.

Skrypt wypisuje statusy i identyfikator korelacji, bez sekretu, tokena,
linku spotkania ani treści odpowiedzi Graph. `cleanup_required=true` wymaga
sprawdzenia oznaczonego spotkania w kalendarzu Ewy; wynik nie jest wtedy
zaliczany. Pusta lista transkryptów w tym teście potwierdza tylko dostęp API.

## 1. Nowa rejestracja aplikacji w Entra ID

Osobna od „NEXUS ATS - Mailbox and Login”. Polityka dostępu Exchange zawęża
aplikację do skrzynek, a nie do uprawnień: dodanie skrzynek DL-i i rekruterów
do zakresu tamtej aplikacji (ma `Mail.Read`) dałoby jej odczyt ich poczty.

1. Entra ID → App registrations → New registration: **NEXUS Teams Prep**
   (single tenant).
2. API permissions → Microsoft Graph → **Application permissions**:
   - `OnlineMeetings.ReadWrite.All` — identyfikator spotkania i włączenie
     automatycznej transkrypcji,
   - `OnlineMeetingTranscript.Read.All` — pobranie transkryptu prepu i follow-upu,
   - `User.ReadBasic.All` — identyfikator obiektu organizatora
     (ścieżki `onlineMeetings` go wymagają).
3. **Grant admin consent** tylko dla powyższych uprawnień. Dostęp do kalendarzy
   nadaj przez Exchange App RBAC z rolą `Application Calendars.ReadWrite` i
   zakresem skrzynek organizatorów. Nie dodawaj równolegle nieograniczonego
   uprawnienia `Calendars.ReadWrite` w Entra.
4. Certificates & secrets → New client secret. Zapisz wartość (widać ją raz).

## 2. Grupa, do której aplikacja ma dostęp

Mail-enabled security group **NEXUS-Meetings-Scope** (ukryta w GAL), członkowie:
wszyscy Delivery Leadzi i rekruterzy prowadzący prepy lub follow-upy.

## 3. Zawężenie dostępu (PowerShell)

Exchange Online (kalendarze): skonfiguruj [App RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac)
z rolą `Application Calendars.ReadWrite` ograniczoną do skrzynek organizatorów
i sprawdź dostęp do skrzynki w zakresie oraz poza nim. Poniższa Application
Access Policy to starsza ścieżka awaryjna. Wymaga grantu aplikacyjnego
`Calendars.ReadWrite` w Entra i nie powinna być łączona z App RBAC, bo
uprawnienia obu mechanizmów są sumowane.

```powershell
Connect-ExchangeOnline
New-ApplicationAccessPolicy -AppId <APP_ID> `
  -PolicyScopeGroupId nexus-meetings-scope@b2bnetwork.pl `
  -AccessRight RestrictAccess `
  -Description "NEXUS Teams Prep — tylko kalendarze DL i rekruterów"
Test-ApplicationAccessPolicy -AppId <APP_ID> -Identity <dl@b2bnetwork.pl>     # Granted
Test-ApplicationAccessPolicy -AppId <APP_ID> -Identity <ktos-inny@b2bnetwork.pl>  # Denied
```

Teams (spotkania i transkrypty):

```powershell
Connect-MicrosoftTeams
New-CsApplicationAccessPolicy -Identity NEXUS-Meetings -AppIds <APP_ID> `
  -Description "NEXUS Teams Prep"
Grant-CsApplicationAccessPolicy -PolicyName NEXUS-Meetings -Group <ID_GRUPY>
```

Propagacja polityki Teams trwa do ok. 30 minut.

## 4. Polityka spotkań Teams i dostęp API

Dla grupy: transkrypcja dozwolona (Teams admin center → Meetings → Meeting
policies → Recording & transcription → Transcription: On). Aktualna polityka
globalna ma już `Meeting recording` i `Transcription` włączone, ale
`Require participant agreement for recording, transcription, and Copilot` jest
wyłączone. Przed automatycznym nagrywaniem przypisz organizatorom politykę
z wymaganą zgodą i sprawdź faktyczny ekran zgody u uczestnika testowego.
Sprawdź też `AutoRecording=Enabled` dla tych organizatorów: Microsoft wymaga
tej polityki, aby ustawienie „Record and transcribe automatically” było
dostępne. Samo `allowTranscription=true` jedynie zezwala na transkrypcję.

Osobno: Teams admin center → Meetings → Meeting settings → Transcript API
access → Microsoft Graph access. Ten przełącznik jest domyślnie wyłączony i
blokuje odczyt nawet przy `OnlineMeetingTranscript.Read.All`. Speaker
attribution jest osobnym ustawieniem; może pozostać wyłączone. Po odmowie
formatu z mówcami NEXUS pobiera transkrypt bez ich nazw i nie wyliczy udziału
kandydata w czasie rozmowy. Przed zmianą polityki globalnej sprawdź dostęp
konkretnych aplikacji i zakres ich uprawnień w Entra.

Uzgodnij informację i zgodę uczestników przed automatycznym nagrywaniem.
Obecny akapit w zaproszeniu (`PREP_NOTICE_TEXT`) jest roboczy i wymaga
akceptacji prawnej; samo zaproszenie nie zastępuje polityki zgody w Teams.

## 5. Zmienne w Coolify (workflow „Coolify set env”)

```
TEAMS_PREP_CLIENT_ID=<APP_ID>
TEAMS_PREP_CLIENT_SECRET=<sekret>
TEAMS_PREP_APP_ONLY_ENABLED=true
TEAMS_PREP_TRANSCRIPTS_ENABLED=true
```

`M365_MAIL_TENANT_ID` jest już ustawiony (tenant dla client_credentials).

## 6. Sprawdzenie na jednym prawdziwym prepie

1. `/api/health` → `checks.teams_prep = healthy`.
2. Z kalendarza „Rozmowy u klienta” zaplanuj Prep 1 dla prawdziwego kandydata:
   spotkanie pojawia się w kalendarzu DL-a z linkiem Teams, a kandydat dostaje
   zaproszenie z akapitem o nagrywaniu.
3. W Teams sprawdź, że nagrywanie i transkrypcja startują same. Jeśli nie,
   okno pokaże „włącz transkrypcję ręcznie”, a Teams wymaga osobnej polityki.
4. Mów po polsku i sprawdź, czy język transkrypcji to polski (opcja spotkania
   „Language spoken in meeting”).
5. Kilkanaście minut po spotkaniu na karcie kandydata pojawia się ocena prepu,
   a w notatkach kandydata podsumowanie.
6. Pomiar modeli: `python -m scripts.eval_prep_review --limit 20` w kontenerze
   backendu (po ok. 20 prepach).

## 7. Follow-up w Teams

W profilu kandydata, przy aktywnym follow-upie, przycisk „Zaplanuj follow-up
w Teams” zakłada spotkanie w kalendarzu osoby zapisującej. Kandydat otrzymuje
zaproszenie z informacją o nagrywaniu. NEXUS próbuje włączyć automatyczne
nagranie i transkrypcję tymi samymi uprawnieniami co prep. Stan konfiguracji
jest widoczny przy spotkaniu; gdy Graph odmówi, prowadzący musi włączyć
nagrywanie ręcznie. Po zakończeniu kolejka pobiera transkrypt do NEXUS.
Transkrypt jest widoczny w profilu kandydata również po zakończeniu rundy
follow-upu. Identyfikator żądania chroni przed podwójnym zaproszeniem.
Historyczne połączenia CloudTalk pozostają w historii, ale nowe follow-upy
korzystają z Teams.

Sprawdzenie: zaplanuj kontrolowane spotkanie z testowym kandydatem, otwórz
link Teams, potwierdź informację i zgodę na nagrywanie, zakończ spotkanie,
a następnie sprawdź `transcript_status=fetched` i tekst transkryptu w NEXUS.
Sam fakt utworzenia zaproszenia nie potwierdza nagrywania ani pobrania
transkryptu.

## Czego NEXUS nie kasuje

Nagranie i transkrypt zostają też w OneDrive i Teams organizatora. Usunięcie
kandydata w NEXUSIE (art. 17) kasuje transkrypt i ocenę w NEXUSIE; kopię
w M365 obejmuje polityka retencji tenanta (domyślnie nagrania Teams wygasają
po 120 dniach).
