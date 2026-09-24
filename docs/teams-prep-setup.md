# Prepy w Teams — konfiguracja Microsoft 365 (jednorazowo, administrator)

Kod jest wdrożony z wyłączonymi przełącznikami. Do czasu tych kroków okno
„Zaplanuj prep” działa jak dotąd (zwykłe zaproszenie przez połączone konto
M365), a sonda `checks.teams_prep` mówi `unconfigured`.

## 1. Nowa rejestracja aplikacji w Entra ID

Osobna od „NEXUS ATS - Mailbox and Login”. Polityka dostępu Exchange zawęża
aplikację do skrzynek, a nie do uprawnień: dodanie skrzynek DL-i i rekruterów
do zakresu tamtej aplikacji (ma `Mail.Read`) dałoby jej odczyt ich poczty.

1. Entra ID → App registrations → New registration: **NEXUS Teams Prep**
   (single tenant).
2. API permissions → Microsoft Graph → **Application permissions**:
   - `Calendars.ReadWrite` — spotkanie w kalendarzu organizatora,
   - `OnlineMeetings.ReadWrite.All` — identyfikator spotkania i włączenie
     automatycznej transkrypcji,
   - `OnlineMeetingTranscript.Read.All` — pobranie transkryptu,
   - `User.ReadBasic.All` — identyfikator obiektu organizatora
     (ścieżki `onlineMeetings` go wymagają).
3. **Grant admin consent**.
4. Certificates & secrets → New client secret. Zapisz wartość (widać ją raz).

## 2. Grupa, do której aplikacja ma dostęp

Mail-enabled security group **NEXUS-Meetings-Scope** (ukryta w GAL), członkowie:
wszyscy Delivery Leadzi i rekruterzy prowadzący prepy.

## 3. Zawężenie dostępu (PowerShell)

Exchange Online (kalendarze):

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

## 4. Polityka spotkań Teams

Dla grupy: transkrypcja dozwolona (Teams admin center → Meetings → Meeting
policies → Recording & transcription → Transcription: On).

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

## Czego NEXUS nie kasuje

Nagranie i transkrypt zostają też w OneDrive i Teams organizatora. Usunięcie
kandydata w NEXUSIE (art. 17) kasuje transkrypt i ocenę w NEXUSIE; kopię
w M365 obejmuje polityka retencji tenanta (domyślnie nagrania Teams wygasają
po 120 dniach).
