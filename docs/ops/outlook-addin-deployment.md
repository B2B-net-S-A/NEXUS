# NEXUS Outlook Add-in — deployment

Faza 7.4 z planu `~/.claude/plans/elegant-percolating-thimble.md` dodaje Outlook
Add-in który w bocznym panelu Outlooka pokazuje czy nadawca wiadomości istnieje
w bazie NEXUS i, jeśli tak, linkuje do profilu.

Wszystkie pliki statyczne są w `frontend/public/outlook-addin/` i serwowane
przez Next.js z hosta `nexus.dynaminds.pl`:

| URL | Plik |
|---|---|
| `https://nexus.dynaminds.pl/outlook-addin/manifest.xml` | manifest dla Office |
| `https://nexus.dynaminds.pl/outlook-addin/taskpane.html` | taskpane (sidebar) |
| `https://nexus.dynaminds.pl/outlook-addin/taskpane.js` | logika add-in |
| `https://nexus.dynaminds.pl/outlook-addin/taskpane.css` | style |
| `https://nexus.dynaminds.pl/outlook-addin/commands.html` | placeholder commands |
| `https://nexus.dynaminds.pl/outlook-addin/icons/icon-*.png` | ikony 16/32/64/80/128 |

Endpoint backendu: `GET https://api.nexus.dynaminds.pl/api/candidates/check-exists?email=<addr>`
(wymaga `Authorization: Bearer <NEXUS JWT>`).

## 1. Sideloading (testowanie pojedynczego użytkownika)

Najszybsza ścieżka sprawdzenia że manifest działa.

1. Otwórz <https://outlook.office.com> i zaloguj się kontem z domeny `b2bnet.pl`
   (lub innej zarejestrowanej w NEXUS).
2. Otwórz dowolną wiadomość.
3. Pasek narzędzi → **Akcje (...)** → **Pobierz dodatki** (ang. *Get Add-ins*).
4. Lewa kolumna → **Moje dodatki** → sekcja **Niestandardowe dodatki** →
   przycisk **+ Dodaj niestandardowy dodatek** → **Dodaj z adresu URL...**
5. Wklej: `https://nexus.dynaminds.pl/outlook-addin/manifest.xml`.
6. Potwierdź ostrzeżenie o niestandardowym dodatku.
7. Wróć do skrzynki, kliknij dowolną wiadomość. Sidebar **NEXUS Candidate
   Lookup** powinien się pojawić w `Akcje (...)` w czytniku wiadomości.

Pierwszy raz pojawi się ekran logowania — wpisz swoje credentials NEXUS
(te same co do `nexus.dynaminds.pl`). Token zostaje w `localStorage` dodatku
do wylogowania.

## 2. Tenant-wide deployment (produkcja, wszyscy w organizacji)

Po przetestowaniu sideloadingiem, deploy dla całego tenanta:

1. Zaloguj się do <https://admin.microsoft.com> kontem administratora globalnego.
2. Lewa nawigacja → **Ustawienia** → **Aplikacje zintegrowane**
   (*Integrated apps*).
3. Górny pasek → **Przekaż aplikację niestandardową** (*Upload custom apps*).
4. Wybierz **Plik manifestu Office Add-in (.xml)** → kliknij **Choose File** →
   pobierz `manifest.xml` z `https://nexus.dynaminds.pl/outlook-addin/manifest.xml`
   na dysk i wybierz lokalnie. Alternatywnie: wklej URL manifestu.
5. **Wdrażanie**:
   - **Cała organizacja** — wszyscy widzą dodatek w Outlook.
   - **Określone użytkownicy lub grupy** — wybierz grupę AAD (np.
     `recruiters@b2bnet.pl`).
6. **Zaakceptuj uprawnienia** — manifest deklaruje `ReadItem` (czytanie
   nagłówków wiadomości). Żadne pisanie ani dostęp do treści załączników.
7. **Wdróż**. Propagacja do skrzynek użytkowników: 1–6h, najczęściej < 1h.

## 3. Weryfikacja po deploy

```bash
# Manifest dostępny (200 + content-type XML)
curl -fsSI https://nexus.dynaminds.pl/outlook-addin/manifest.xml | grep -E "HTTP/|content-type"

# Backend endpoint odpowiada (po zalogowaniu)
curl -s "https://api.nexus.dynaminds.pl/api/candidates/check-exists?email=test@example.com" \
  -H "Authorization: Bearer $NEXUS_JWT" | jq .
```

Smoke test E2E (Chrome MCP):

1. Otwórz Outlook Web jako `claude-admin@b2bnet.pl`.
2. Kliknij wiadomość od znanego kandydata (najlepiej `artur@b2bnet.pl` lub
   przeszłego kandydata z bazy).
3. Akcje (`...`) → **NEXUS Candidate Lookup**.
4. Po zalogowaniu sidebar powinien pokazać kartę z imieniem kandydata, etapem
   pipeline i linkiem do profilu.

## 4. Aktualizacje add-in

Sama zmiana w `taskpane.js` / `taskpane.html` / `taskpane.css` propaguje się
**natychmiast** po deploy NEXUS — manifest jest stabilny i ładuje pliki świeże
z hosta. Wystarczy `git push origin main` → Coolify deploy frontu.

Zmiana wymagająca update manifestu (nowy permission, nowa ribbon command,
zmiana hostów, nowa wersja Office API):

1. Inkrementuj `<Version>` w `manifest.xml` (np. `1.0.0.0` → `1.0.0.1`).
2. Commit + push + deploy.
3. Microsoft 365 Admin Center → Integrated apps → wybierz dodatek →
   **Aktualizuj manifest** → wklej nowy URL lub plik.
4. Office automatycznie sprawdza wersję manifestu raz na ~24h. Force refresh:
   admin może użyć opcji *Update now*.

## 5. Wycofanie

Microsoft 365 Admin Center → Integrated apps → dodatek → **Usuń**. Dezaktywuje
dla wszystkich użytkowników w ciągu ~6h.

Sideloaded entry użytkownik usuwa sam: Outlook → Akcje → Pobierz dodatki →
Moje dodatki → **X** przy `NEXUS Candidate Lookup`.

## 6. Znane ograniczenia (MVP)

- **Auth bazuje na NEXUS email+password.** Office SSO (`Office.context.auth.getAccessToken`)
  wymaga ekspozycji nowego scopu w AAD app i `WebApplicationInfo` w manifest —
  follow-up gdy potrzebne. Token JWT siedzi w `localStorage` dodatku do
  manualnego wylogowania.
- **Outlook Mobile** — `ItemChanged` event może nie być obsługiwane, więc
  pierwszy klik renderuje, ale przełączanie między wiadomościami wymaga
  ponownego otwarcia panelu.
- **Klasyczny Outlook desktop (Office 2019/2021 COM)** — obsługa Mailbox 1.5,
  ale niektóre starsze buildy mają ograniczone `Office.context.mailbox.item.from`.
  Sprawdź na 2 stacjach przed tenant-wide rollout.

## 7. Bezpieczeństwo i RODO

- Manifest deklaruje wyłącznie `ReadItem` — żadne write/send/calendar.
- Add-in **nie przesyła treści maila** — tylko adres email nadawcy do endpointu
  NEXUS, który już zna ten adres (kandydat = ta sama tożsamość).
- Brak telemetrii w `taskpane.js`. Sentry add-in nie używa.
- JWT w `localStorage` — usuwany przy *Wyloguj* lub po 401 z backendu.
