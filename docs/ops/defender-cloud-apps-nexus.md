# Defender for Cloud Apps — NEXUS ATS registration

> Operational runbook for registering NEXUS as a sanctioned cloud app in Microsoft Defender XDR (Cloud Apps, dawniej **Microsoft Cloud App Security / MCAS**). Config-only — żadnych code changes po stronie NEXUS. ETA: 1–2h one-time setup + ~30 min annual review.
>
> Plan reference: `~/.claude/plans/elegant-percolating-thimble.md` — Phase 7.10.

## Tenant facts (verified 2026-05-16)

| Field | Value |
|---|---|
| Defender for Cloud Apps Tenant ID | `97509327` |
| Microsoft Entra Tenant ID | `e277180c-…-bb89ab0b1301` (pełna wartość w Coolify env vault → `M365_TENANT_ID`; ukryta tutaj bo gitleaks `fireflies-api-key` rule false-positives na UUID format) |
| Region / Data center | UK South / EU2 |
| Legacy MCAS portal URL (custom app management) | `https://b2bnetsa.eu2.portal.cloudappsecurity.com` |
| Unified portal (preferred for policies + alerts) | `https://security.microsoft.com/cloudapps` |
| Service version (when verified) | 331.161 |

## Status w tenant (2026-05-16)

| Pozycja runbooka | Stan |
|---|---|
| Defender for Cloud Apps aktywny w tenant | ✅ TAK — sidebar pokazuje Cloud apps section z pełną nawigacją (Discovery / Catalog / OAuth / Policies / etc.) |
| App Connectors (legacy AAD connector) | ⚠️ 0 connected apps. Modern Defender XDR używa **Identity inventory integration** zamiast osobnego AAD connector — sign-in/audit logs są forwardowane automatycznie z Entra ID, dodatkowy connector zwykle niepotrzebny |
| Anomaly detection policies (Impossible travel, Infrequent country, Ransomware, Suspicious inbox forwarding, etc.) | ⚠️ **Wszystkie 17 threat detection policies `[Disabled]`** (last modified 2026-02-17). Microsoft sam je wyłączył w ramach migracji do dynamic threat detection model (announced 2025-06-15, patrz [§ Dynamic threat detection migration](#dynamic-threat-detection-migration-2025-06-15)) |
| NEXUS as sanctioned app in Cloud app catalog | ❌ Nie ma. "Add custom app" toolbar button **nie istnieje** w unified portal — funkcjonalność jest w legacy MCAS pod `b2bnetsa.eu2.portal.cloudappsecurity.com/#/settings/customApps` |
| Custom email settings (org-level Mail settings) | ⚠️ **DEPRECATED przez Microsoft** — komunikat *"Custom email settings feature has been deprecated. you will still get email notifications with the default display settings."* Domyślny sender: `no-reply@cloudappsecurity.com`. Brak opcji konfiguracji sender display name |
| My email notifications (Artur Twardowski, Global Admin) | ✅ ENABLED 2026-05-16 — severity ≥ Medium + system alerts (zaznaczone via portal) |
| Smoke test impossible travel | ⏳ TODO — wymaga VPN exit-nodes z 2 krajów + ~1h delay |

## Dynamic threat detection migration (2025-06-15)

Komunikat z portalu pod Policy management:

> *"Starting June 15th, 2025, Microsoft Defender for Cloud Apps will adopt a dynamic threat detection model to enhance accuracy and responsiveness, policies that migrated will be disabled."*

**Implikacje dla runbooka:**

- Legacy policy templates (Impossible travel, Activity from infrequent country, Ransomware, etc.) zostały **automatycznie wyłączone** przez Microsoft podczas migracji.
- Dynamic threat detection model działa w tle — Microsoft uważa że jest dokładniejszy niż statyczne policies z fixed thresholds.
- **Re-enabling legacy policies = duplicate alerts** z dynamic model. Generuje noise.
- Decyzja architektoniczna (do podjęcia przez IT-Security):
  - **Opcja A — zostać przy dynamic model (rekomendacja Microsoft):** akceptujesz że threat detection jest poza Twoją kontrolą (no thresholds, no fine-tuning), ale dostajesz mniej false positives.
  - **Opcja B — re-enable wszystko z legacy:** masz pełną kontrolę nad thresholds, ale: (a) duplikuje dynamic model (więcej alertów), (b) Microsoft może w przyszłości usunąć legacy templates.
  - **Opcja C — hybrid:** dynamic + 2-3 selected custom activity policies dla NEXUS-specific scenarios (np. mass CV export — wymaga że NEXUS sam emituje activity logs).

Dla NEXUS w MVP rekomendacja: **Opcja A** (zostawić dynamic), monitorować przez 90 dni, retroaktywnie dodać custom policies jeśli będą luki w pokryciu.

## License & ownership

| Field | Value |
|---|---|
| License SKU | `Microsoft Defender Suite for Microsoft 365 Business Premium` (zawiera **Defender for Cloud Apps**) |
| Liczba licencji | 1 (CASB jest org-wide, nie per-user) |
| Source | Partner Center (B2BNet / Dynaminds) |
| Renewal date | **2027-05-05** |
| Admin portal | https://security.microsoft.com → Cloud apps |
| Owner | IT-Security (`it-security@b2bnet.pl`) |

> ⚠️ **Privacy note:** Defender for Cloud Apps zbiera Sign-in + Audit logs z Azure AD wszystkich userów NEXUS. To znaczy że IT-Security ma full visibility na każdą sesję. Udokumentuj w GDPR processing register jeśli prowadzony (Art. 30 RODO).

## Overview

Defender for Cloud Apps (MDA) działa jako **CASB** (Cloud Access Security Broker) nad Azure AD. Dla NEXUS daje:

- **Sign-in audit** (automatyczny po podłączeniu AAD connector) — kto, kiedy, z jakiego IP/kraju.
- **Anomaly detection** — impossible travel, infrequent country, mass download, repeated failed logins.
- **Sanctioning** — flaga "NEXUS = official corporate app", pozwala odróżnić shadow IT od sanctioned apps w raportach Cloud Discovery.
- **Optional**: Custom activity policies (wymaga że NEXUS sam emituje activity events via Microsoft Graph Activity API — pominięte w MVP, patrz [§ NEXUS-emitted activity logs](#nexus-emitted-activity-logs-phase-2-opcjonalne)).

Co dostajesz **bez** dodatkowej integracji NEXUS:

| Źródło zdarzeń | Skąd | Dla NEXUS |
|---|---|---|
| Azure AD sign-in logs | Auto przez AAD connector | Logowania userów NEXUS (success/fail, IP, kraj, device) |
| Azure AD audit logs | Auto przez AAD connector | Admin actions w AAD (np. dodanie usera, zmiana hasła) |
| App activity logs | Wymaga Graph Activity API hooks w NEXUS | Bulk export CV, batch delete kandydatów, etc. — **opcjonalne** |

## Prerequisites

- Konto z rolą **Global Administrator** lub **Security Administrator** w tenancie M365.
- NEXUS Azure AD app registration istnieje (Phase 1 done — można potwierdzić wartością `M365_CLIENT_ID` w Coolify env vault).
- Dostęp do https://security.microsoft.com (Microsoft Defender XDR portal).
- Email dystrybucyjny dla alertów: `it-security@b2bnet.pl` (utwórz w M365 Admin jeśli jeszcze brak).

## Procedure

### Step 1 — Sanction NEXUS as a cloud app

Cel: oznaczyć NEXUS jako **Sanctioned app**, dzięki czemu wszystkie sign-iny i activity logs będą agregowane pod jedną tożsamością aplikacji w MDA dashboard.

1. Login do https://security.microsoft.com.
2. Lewy panel → **Cloud apps** → **Cloud app catalog**.
3. Wyszukaj `NEXUS`. Możliwe ścieżki:
   - **Already discovered** (MDA wykrył ruch z AAD sign-in logs): kliknij w wynik → pasek narzędzi → **Sanction app** (zielona ikona ✓).
   - **Not found**: górny przycisk **Add custom app**. Wypełnij:
     - **Name**: `NEXUS ATS`
     - **Domain**: `nexus.dynaminds.pl`
     - **Category**: `Human Resources` (lub `CRM` — IT-Security decyduje, wpływa tylko na grupowanie raportów).
     - **Description**: `Internal ATS — recruitment platform for B2BNet / Dynaminds. Owned by Dynaminds, hosted on Hetzner CAX21 (Coolify).`
     - **Logo**: opcjonalnie — załaduj `frontend/public/logo.svg` (192px PNG).
4. Po utworzeniu → karta NEXUS → **Sanction**.
5. Expected state: w **Cloud apps → Cloud app inventory** NEXUS ma status `Sanctioned` (kolumna *App tags*).

### Step 2 — Connect Azure AD

Cel: podłączyć MDA do tenanta AAD aby auto-import sign-in + audit logs.

> 🔍 **Sprawdź najpierw**: większość tenantów M365 ma już AAD connector skonfigurowany (jeden connector pokrywa wszystkie sanctioned apps). Jeśli istnieje → skip ten step.

1. **Settings** (koło zębate, prawy górny róg) → **Cloud apps** → **Connected apps** → tab **App connectors**.
2. Jeśli widzisz `Microsoft Entra ID (Azure AD)` ze statusem `Connected` → przejdź do Step 3.
3. Inaczej: przycisk `+ Connect an app` → wybierz **Microsoft Entra ID** → **Connect**.
4. Wizard przeprowadzi przez consent flow (jako Global Admin). Permissions wymagane:
   - `AuditLog.Read.All`
   - `Directory.Read.All`
   - `Policy.Read.All`
5. Po consent → status zmieni się na `Connected`. Initial sync trwa **do 24h** (sign-in events pojawiają się szybciej, ~15 min).
6. Verify: **Cloud apps → Activity log** — powinieneś zobaczyć eventy `Logged in` dla userów NEXUS w ciągu godziny.

### Step 3 — Enable anomaly detection policies

Cel: włączyć 4 default-policies które dają największą wartość bez tuningu. Każda z konkretnymi thresholds.

1. **Cloud apps** → **Policies** → **Policy templates**.
2. Filter: `Type = Anomaly detection policy`.
3. Dla każdej z poniższych: kliknij **+ Create policy from template**, ustaw scope `Apps: NEXUS ATS`, severity `High`, save.

| Policy | Threshold (default OK) | Action | Severity |
|---|---|---|---|
| **Impossible travel** | 2 sign-iny z różnych krajów w czasie krótszym niż możliwy najszybszy lot | Alert + email | High |
| **Activity from infrequent country** | Sign-in z kraju nie używanego przez tego usera w ciągu ostatnich **30 dni** | Alert + email | Medium |
| **Mass download** | > **50 plików** pobrane przez 1 usera w **10 min** | Alert + email | High |
| **Multiple failed login attempts** | > **10 failed logins** w **5 min** dla 1 usera | Alert + email | High |

Optional 5. policy (zalecana ale wymaga tuningu po pierwszych tygodniach false-positives):

| Policy | Threshold | Action | Severity |
|---|---|---|---|
| **Unusual administrative activity** | Admin action poza zwykłymi godzinami pracy usera (baseline learning, 7-dniowy uczący się model) | Alert | Medium |

**Polityki które celowo pomijamy w MVP** (zostawiamy default-disabled):
- *Suspicious inbox forwarding rules* — dot. Exchange, nie NEXUS.
- *Data exfiltration to unsanctioned apps* — wymaga Cloud Discovery z firewall log shipping (nie mamy).
- *Ransomware activity* — wymaga MDA for Endpoint (osobna licencja).

### Step 4 — Custom activity policies (opcjonalne, skip w MVP)

Tylko jeśli NEXUS emituje activity logs do MDA (patrz [§ NEXUS-emitted activity logs](#nexus-emitted-activity-logs-phase-2-opcjonalne)). W MVP **pomiń**.

Future use-case: blokada "user exports > 100 candidates in 10 min" (CV bulk export to surface attack):

1. **Policies** → **+ Create policy** → **Activity policy**.
2. Filter: `App equals NEXUS ATS AND Activity type equals BULK_EXPORT AND Object count > 100 AND TimeWindow = 10 min`.
3. Action: `Suspend user` (wymaga AAD admin consent dla `User.Manage.All`) + Alert.
4. Severity: High.

### Step 5 — Configure notifications

Cel: alerty trafiają do `it-security@b2bnet.pl` (plus opcjonalnie Slack channel).

1. **Settings** → **Cloud apps** → **Email notifications**.
2. **From email**: pozostaw default (`noreply@notification.cloudappsecurity.com`).
3. **Email recipients**: dodaj `it-security@b2bnet.pl`.
4. **Daily alert summary**: ON (digest godzinowy z low/medium alerts; high alerts trafiają natychmiast osobnymi mailami).

Opcjonalnie — Slack via Power Automate (NEXUS ma już SLA escalation hooki w Slacku, można rozbudować):

1. https://make.powerautomate.com → New flow → **Automated cloud flow**.
2. Trigger: `When a Microsoft Defender XDR alert is generated`.
3. Filter: `Alert severity = High`.
4. Action: `Slack — Post message` → channel `#security-alerts`.
5. Body: `{alertTitle} — {category} — user: {affectedUser} — IP: {sourceIp}`.

### Step 6 — Smoke test (impossible travel)

Cel: potwierdzić że alerty faktycznie się generują i trafiają na email.

1. Pierwszy login: zaloguj się do NEXUS (`https://nexus.dynaminds.pl`) bez VPN, z biura PL.
2. Drugi login w ciągu < 1h: użyj VPN z exit-node w innym kraju (np. Mullvad US-NY albo NordVPN AU-SYD).
3. Wyloguj się z obu sesji.
4. Po **~1h** (MDA processing delay) sprawdź:
   - https://security.microsoft.com → **Cloud apps** → **Alerts** → expected entry: *"Impossible travel — <user> signed in from PL and AU within 47 min"*.
   - Email do `it-security@b2bnet.pl` z tym samym alertem.
5. Triage: **Resolve alert** → reason `Test by IT-Security` (żeby nie zostawić wiszącego incidentu).

Jeśli alert NIE przyszedł po 2h — patrz [§ Troubleshooting](#troubleshooting).

## NEXUS-emitted activity logs (Phase 2, opcjonalne)

W MVP pomijamy. Future enhancement:

- Hook w `backend/app/api/candidates.py` po bulk export → fire async event do MDA via Microsoft Graph Activity API: `POST /security/auditLogs` (preview).
- Metadata: `{user_id, action: "bulk_export", count, timestamp, ip, user_agent}`.
- Implementacja: dodać `app/services/m365/mda_emitter.py` analogicznie do `app/services/autenti/*` (kill-switched przez `MDA_ACTIVITY_LOGS_ENABLED=false` default).
- Wartość: custom activity policies (Step 4) — np. block + suspend przy >100 CV exportów w 10 min.
- Trigger do wdrożenia: jeśli kiedyś będzie incydent typu "ktoś wyciekł bazę kandydatów" → wtedy włączamy.

## Troubleshooting

### Alert "Impossible travel" nie przychodzi po 2h

1. **AAD connector status**: Settings → Connected apps → Microsoft Entra ID → status MUSI być `Connected`. Jeśli `Error` — kliknij `Reconnect`, ponów consent.
2. **Activity log puste**: Cloud apps → Activity log → filter na swój email. Jeśli brak eventów `Logged in` — AAD connector nie sync'uje. Verify w AAD: Azure portal → Microsoft Entra ID → Sign-in logs — Twoje 2 sign-iny tam są? Jeśli nie, to NEXUS nie kompletuje OAuth flow (innym problem, sprawdź `M365_CLIENT_ID` i Coolify env vault).
3. **Policy disabled**: Cloud apps → Policies → Impossible travel — status MUSI być `Enabled`. Po stworzeniu z template czasem zostaje `Disabled` (draft).
4. **Scope mismatch**: Policy → Edit → Scope → app MUSI zawierać `NEXUS ATS`. Default scope = wszystkie sanctioned apps, ale jeśli ktoś zawęził → fix.
5. **MDA learning period**: pierwsze 7 dni po włączeniu policy MDA "uczy się" baselineu i może suppress'ować alerty. Jeśli to świeżo włączone — poczekaj tydzień, ponów smoke test.

### False positives — admin action z infrequent country

Scenario: TAC podróżuje, loguje się z hotelu w Madrycie, dostaje alert. Whitelist:

1. **Cloud apps** → **Alerts** → znajdź alert → **Resolve** → `Benign — known user activity`.
2. MDA "uczy się" — kolejny sign-in z PL po dniu w Madrycie nie zaalertuje.
3. Stricter: **Cloud apps** → **Policies** → edycja "Activity from infrequent country" → **Exclude users** → dodaj usera-podróżnika.

### Email notifications nie przychodzą mimo alertu w UI

1. Settings → Email notifications → verify `it-security@b2bnet.pl` w `Email recipients`.
2. Spam folder usera odbiorczego (sender: `noreply@notification.cloudappsecurity.com`).
3. M365 Admin → Exchange → Mail flow → quarantine — możliwe że flagged jako phish.
4. Workaround: użyj Power Automate flow (Step 5 — Slack) zamiast email.

## Renewal & maintenance

- **Renewal**: 2027-05-05 (Partner Center). Dodaj reminder do `it-security@b2bnet.pl` calendar na **2027-04-05** (30 dni przed).
- **Annual review** (Q4 każdego roku, ~30 min):
  - [ ] Zweryfikuj że AAD connector dalej `Connected`.
  - [ ] Sprawdź czy nadal 4 anomaly policies są `Enabled` i scope obejmuje `NEXUS ATS`.
  - [ ] Review listy resolved alerts za ostatni rok — czy są wzorce false-positive które uzasadniają tightening/loosening thresholds.
  - [ ] Smoke test impossible travel (Step 6) — potwierdza że pipeline alertowy działa.
  - [ ] Email distribution list `it-security@b2bnet.pl` ma poprawnych członków.

## Privacy / GDPR

- MDA przetwarza sign-in metadata (IP, kraj, czas, device, user) wszystkich userów NEXUS. To są dane osobowe w rozumieniu RODO Art. 4.
- **Podstawa prawna**: legitymny interes administratora (Art. 6 ust. 1 lit. f) — bezpieczeństwo systemu ATS przetwarzającego dane kandydatów.
- **Retencja**: MDA trzyma activity log 180 dni (default). Po wygaśnięciu — purge automatyczny.
- **Processing register entry** (jeśli prowadzony):
  - *Cel*: detekcja anomalii bezpieczeństwa w dostępie do NEXUS ATS.
  - *Kategorie danych*: dane osobowe userów (email/UPN), metadata sesji (IP, kraj, device, czas).
  - *Odbiorcy*: Microsoft Corp. (subprocessor, DPA podpisana w ramach M365 Business Premium).
  - *Transfer*: EU (Microsoft Defender XDR data residency `Europe`).
  - *Okres retencji*: 180 dni.

## References

- [Microsoft Defender for Cloud Apps — overview](https://learn.microsoft.com/en-us/defender-cloud-apps/what-is-defender-for-cloud-apps)
- [Anomaly detection policies](https://learn.microsoft.com/en-us/defender-cloud-apps/anomaly-detection-policy)
- [Connect Microsoft Entra ID (Azure AD) to MDA](https://learn.microsoft.com/en-us/defender-cloud-apps/connect-azure-active-directory)
- [Activity policies — custom](https://learn.microsoft.com/en-us/defender-cloud-apps/user-activity-policies)
- [MDA data residency (EU/US/AU)](https://learn.microsoft.com/en-us/defender-cloud-apps/data-residency)

## See also

- `~/.claude/rules/observability.md` — pełny standard observability (Sentry + Grafana + Cloudflare). MDA dopina się jako **4. warstwa** (CASB nad AAD audit logs).
- `docs/RBAC.md` — Phase 7.2 AAD group RBAC synergia: MDA + RBAC = pełna audit trail kto-co-zrobił + automatic block na anomalie.
- `~/.claude/plans/elegant-percolating-thimble.md` Phase 7.10.
