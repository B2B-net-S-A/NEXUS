# Dokumenty kontraktów z SharePointa — konfiguracja (ticket 9)

NEXUS czyta folder „Umowy pracowników” (podfolder „Nazwisko Imię” na osobę),
zapisuje PDF/JPG w zakładce Dokumenty kontraktów i — po włączeniu
synchronizacji — wysyła dokumenty dodane w NEXUSIE do folderu osoby.

Link udostępnienia z ticketu działa tylko po zalogowaniu do firmy, więc NEXUS
potrzebuje własnego dostępu do witryny. Zakładamy **osobną** rejestrację
z uprawnieniem `Sites.Selected` — widzi wyłącznie witrynę, której dostęp jej
nadamy, i nic poza nią (ani poczty, ani innych witryn).

## 1. Rejestracja w Entra ID (admin M365, ~5 min)

1. Entra ID → App registrations → New registration → nazwa
   **NEXUS Contract Documents**, konto: *Single tenant*, bez Redirect URI.
2. API permissions → Add → Microsoft Graph → **Application permissions** →
   `Sites.Selected` → Add → **Grant admin consent**.
3. Certificates & secrets → New client secret (24 miesiące) → skopiuj wartość.
4. Zapisz: *Application (client) ID* i sekret.

## 2. Dostęp do jednej witryny (admin M365, ~5 min)

Witryna: `https://b2bnetsa.sharepoint.com/sites/Share_B2B`.
Uprawnienie `write` — synchronizacja w obie strony zakłada foldery osób
i wgrywa pliki. Tylko odczyt = `read` (wtedy NEXUS nie wyśle nic do folderu).

PowerShell (PnP):

```powershell
Connect-PnPOnline -Url https://b2bnetsa.sharepoint.com/sites/Share_B2B -Interactive
Grant-PnPAzureADAppSitePermission -AppId <CLIENT_ID> -DisplayName "NEXUS Contract Documents" -Permissions Write
```

albo Graph Explorer (konto administratora):

```http
GET https://graph.microsoft.com/v1.0/sites/b2bnetsa.sharepoint.com:/sites/Share_B2B?$select=id
POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
{
  "roles": ["write"],
  "grantedToIdentities": [
    {"application": {"id": "<CLIENT_ID>", "displayName": "NEXUS Contract Documents"}}
  ]
}
```

## 3. Serwer NEXUSA

Workflow **„Coolify set env”** (bez redeployu), potem zwykły deploy:

| Zmienna | Wartość |
|---|---|
| `CONTRACT_DOCS_SP_CLIENT_ID` | Application (client) ID |
| `CONTRACT_DOCS_SP_CLIENT_SECRET` | sekret z kroku 1 |
| `CONTRACT_DOCS_SP_SYNC_ENABLED` | `false` — włącz po pierwszym pobraniu |

Tenant bierze się z istniejącego `M365_MAIL_TENANT_ID`.
Sprawdzenie: `/api/health` → `checks.contract_docs_sharepoint = configured`.

## 4. Pierwsze pobranie

Ustawienia → Umowy i stawki → **Dokumenty kontraktów z SharePointa**:
wklej link do folderu → „Czytaj folder” → przejrzyj podgląd (niepewne
przypisania można odznaczyć) → „Pobierz i zapisz” → raport XLSX. „Cofnij
zapis” usuwa dokumenty tego przebiegu (pliki w SharePoincie zostają).

## 5. Synchronizacja

`CONTRACT_DOCS_SP_SYNC_ENABLED=true` (co `CONTRACT_DOCS_SP_SYNC_MINUTES`,
domyślnie 60):

- nowy PDF/JPG w folderze osoby → dokument na każdym jej kontrakcie; przy
  niepewnym dopasowaniu → kolejka „Do przypisania” w tym samym panelu;
- dokument dodany w NEXUSIE po pierwszym pobraniu (poza PDF-ami zamówień) →
  podfolder osoby (brak folderu = NEXUS go zakłada jako „Nazwisko Imię”;
  folder pasujący do dwóch osób o tym samym nazwisku = pominięcie);
- usunięcie po którejkolwiek stronie niczego nie kasuje po drugiej;
- Filip Jabłoński jest pomijany w obu kierunkach.

Sonda: `checks.contract_docs_sharepoint` (`degraded` = ostatni bieg padł albo
brak biegu przez 3 odstępy).

## Jednorazowy zapis sekretu bez dostępu operatora do panelu Coolify

Gdy operator może uruchamiać istniejące operacje Coolify, ale nie ma prawa
zapisywać GitHub Actions Secrets, workflow **Contract docs secure provisioning**
przyjmuje wyłącznie zaszyfrowaną kopertę dla tej konkretnej rejestracji. Nie zmienia
uprawnień bota, nie odczytuje sekretów GitHuba i nie wykonuje deployu.

1. Na `main` uruchom `operation=receive`. Pobierz artefakt
   `contract-docs-key-<run-id>-1` zawierający `offer.json`.
2. Po utworzeniu sekretu aplikacji zaszyfruj JSON o polach `identity`, `challenge`
   (z oferty), `client_id` (z oferty), `secret` (wartość nowego sekretu). Użyj
   klucza publicznego oferty, RSA-OAEP z SHA-256 i MGF1-SHA256. Wynik zakoduj Base64.
   Wartości jawnej nie zapisuj do plików repozytorium, logów ani inputów workflow.
3. Przed upływem 15 minut uruchom ten sam workflow z `operation=submit`,
   `receiver_identity=<run-id>-1` i `ciphertext=<zaszyfrowana koperta Base64>`.
   Oba przebiegi muszą mieć tego samego operatora i SHA `main`.
4. Poczekaj na sukces odbiorcy. Sprawdza on token z **wyłącznie Sites.Selected**,
   dostęp do Share_B2B, zgodność tenanta/client ID, wyłączony sync i zapis sekretu
   w Coolify. Odmawia nadpisania innego istniejącego sekretu. Klucz prywatny
   odbiorcy jest usuwany po użyciu/wygaśnięciu; nie trafia do artefaktów.
5. Uruchom zwykły workflow **Deploy**, wykonaj pierwszy import, następnie włącz
   synchronizację przez **Coolify set env** zgodnie z sekcją wyżej.

Artefakty zawierają tylko klucz publiczny i szyfrogram (retencja 1 dzień). Ta
ścieżka nie przechowuje kopii sekretu w GitHub Actions Secrets; sekret pozostaje
w Coolify. Kolejny zapis wymaga nowego przebiegu odbiorcy, a rotacja istniejącego
sekretu wymaga standardowej procedury administracyjnej.
