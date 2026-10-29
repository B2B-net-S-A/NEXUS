# Kontrakt API wtyczki LinkedIn → NEXUS

Wszystkie trasy pod `/api/extension/*`. Wtyczka wysyła nagłówek
`X-Extension-Key: nxe_v1_<id>_<sekret>` (bez `Authorization`). Odpowiedzi
błędów: `{"detail": "<kod albo zdanie po polsku>"}`.

- `401 {"detail": "extension_key_invalid"}` → panel pokazuje „Połącz z NEXUSEM”.
- `403` → zdanie po polsku w `detail` (brak uprawnień).
- `429 {"detail": "extension_daily_limit"}` → „Dzisiejszy limit odczytów wyczerpany, wróć jutro”.
- `409 {"detail": {"code": "off_limits_confirmation_required", ...}}` → pytanie „Jak się do nas zgłosił?”.

## Połączenie (strona NEXUSA, nie wtyczka)

Wtyczka otwiera kartę `https://<front>/extension/connect?ext=<chrome.runtime.id>&v=<wersja>`.
Strona najpierw pyta wtyczkę `chrome.runtime.sendMessage(ext, {type: "nexus-ping"})`
→ `{ok: true, version}`; bez odpowiedzi nie prosi NEXUSA o klucz (nowe połączenie
odwołuje poprzednie, więc wejście bez wtyczki odłączyłoby działającą).
Potem (zalogowany użytkownik NEXUSA) woła `POST /api/extension/connect`
(JWT) i przekazuje klucz do wtyczki:
`chrome.runtime.sendMessage(ext, {type: "nexus-extension-key", key, apiBase})`.
Wtyczka przyjmuje to w `chrome.runtime.onMessageExternal` (manifest:
`externally_connectable.matches` = domeny frontu NEXUSA), zapisuje w
`chrome.storage.local` i zamyka kartę.

## Trasy z kluczem wtyczki

### `GET /api/extension/me`
```json
{"user": {"id": 26, "name": "Malwina Jobda", "initials": "MJ"},
 "usage": {"reads_today": 34, "reads_limit": 150, "adds_today": 6},
 "frontend_url": "https://nexus.b2bnetwork.pl",
 "latest_version": "1.0.3"}
```
`latest_version` = najnowsza wtyczka (stała w backendzie, równa `manifest.json`).
Starsza wersja w panelu → baner „Jest nowa wersja” z linkiem do `<frontend>/wtyczka`.

### Profil odczytany ze strony (`ProfileRead`) — wejście kilku tras
```json
{"page_kind": "profile | recruiter_profile",
 "page_url": "https://www.linkedin.com/talent/profile/AEMAA…",
 "public_url": "https://www.linkedin.com/in/jan-kowalski",
 "full_name": "Jan Kowalski",
 "headline": "Senior Java Developer · Spring",
 "location": "Kraków",
 "current_company": "Comarch", "current_title": "Senior Java Developer",
 "experience": [{"title": "…", "company": "…", "start": "2022-03", "end": null, "current": true}],
 "skills": ["Java", "Spring Boot"],
 "about": "…"}
```
`public_url` może być pusty (Recruiter nie zawsze pokazuje publiczny link);
wtedy NEXUS szuka po imieniu, nazwisku i firmie.

### `POST /api/extension/lookup` (liczy 1 odczyt strony)
Wejście: `ProfileRead`. Wyjście:
```json
{"status": "found | not_found | ambiguous",
 "matched_by": "linkedin | name_company | null",
 "candidate": {"id": 1, "name": "…", "headline": "…", "city": "…", "url": "https://…/candidates/1", "in_nexus_since": "2024-03-02"},
 "ambiguous": [{"id": 2, "name": "…", "company": "…", "url": "…"}],
 "owner": {"user_id": 85, "name": "Katarzyna", "is_me": false, "last_contact_at": "…"},
 "processes": [{"job_id": 1, "job_title": "…", "client_name": "Nordea", "stage_label": "Screening", "recruiter_name": "Katarzyna", "closed": false, "close_label": null, "updated_at": "…"}],
 "contacts": [{"at": "…", "user_name": "Katarzyna", "channel_label": "telefon", "note": "…"}],
 "rate": {"label": "150 zł/h B2B", "as_of": "2025-05-01"},
 "rodo": {"status": "valid | expired | none", "label": "zgoda do 03.2027"},
 "off_limits": {"client_name": "PKO BP", "company": "PKO Bank Polski"},
 "contractor": {"client_name": "Nordea", "end_date": "2027-03-31", "delivery_lead_name": "Michał"},
 "job_change": {"page_company": "Allegro", "nexus_company": "Sabre"},
 "matches": [{"job_id": 763073, "title": "…", "client_name": "Nordea", "recruiter_name": "Katarzyna", "score": 81}],
 "usage": {"reads_today": 35, "reads_limit": 150}}
```
Pola obiektowe mogą być `null`, listy puste. `rate` jest `null`, gdy rola nie widzi stawek.

### `POST /api/extension/lookup-batch` (liczy 1 odczyt strony)
Wejście: `{"people": [{"full_name": "…", "public_url": "…|null", "headline": "…", "current_company": "…"}]}` (do 50 osób).
Wyjście: `{"items": [{"index": 0, "status": "new | in_process | in_base | off_limits | contractor", "candidate_id": 1, "label": "Screening · Nordea · Katarzyna", "score": null}], "usage": {…}}`.
Bez procentu dopasowania: z listy jest tylko nagłówek, a liczenie kosztowałoby wywołanie Voyage na każdą osobę.

### `GET /api/extension/jobs?q=java`
Otwarte rekrutacje do wyboru: `{"items": [{"id": 1, "title": "…", "client_name": "…", "recruiter_name": "…"}]}`.

### `POST /api/extension/candidates`
Wejście: `{"profile": ProfileRead, "job_ids": [763073], "off_limits_how": null}`.
`off_limits_how` = klucz z NEXUSA (`client_off_limits.HOW_LABELS`): `linkedin_inbound`, `job_ad`,
`phone_or_email`, `sent_cv_before`, `referral`, `left_company`, albo `skip` („Nie, to my”).
Wyjście `201`: `{"candidate_id": 1, "url": "…", "created": true, "assigned_job_ids": [763073], "skipped": [{"job_id": 1, "reason": "…"}]}`.
Gdy osoba już jest (ten sam link) — `200` z `created: false`.
`409 off_limits_confirmation_required`, gdy firma jest off-limits, a `off_limits_how` brak.
`off_limits_how = "skip"` = rekruter odpowiada „Nie, to my” → osoba trafia do bazy bez rekrutacji.

### `POST /api/extension/candidates/{id}/jobs`
`{"job_ids": [..], "off_limits_how": …}` → `{"assigned_job_ids": [...], "skipped": [...]}`.

### `POST /api/extension/candidates/{id}/refresh`
`{"profile": ProfileRead}` → zapisuje bieżącą firmę i stanowisko z LinkedIna. `{"updated": ["current_company", "current_title"]}`.

### `POST /api/extension/candidates/{id}/contacts`
`{"channel": "inmail | invitation | linkedin_message | phone", "job_id": 1|null, "note": "…", "remind_in_days": 3|null}` → `{"id": …, "reminder_id": …|null}`.

### `POST /api/extension/candidates/{id}/notes`
`{"text": "…"}` → `{"id": …}`.

### `POST /api/extension/candidates/{id}/profile-pdf`
`multipart/form-data`, pole `file` (PDF z „Zapisz jako PDF” na LinkedInie) → `{"document_id": …}`.

### `POST /api/extension/draft-message`
`{"job_id": 1, "kind": "inmail | invitation | linkedin_message", "profile": ProfileRead}` →
`{"text": "…", "ai": true}`. Gdy AI nie odpowie: `ai: false` i szablon z rekrutacji.
Zaproszenie ≤ 300 znaków.
