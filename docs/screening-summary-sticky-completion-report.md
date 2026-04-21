# Sticky Screening Summary — Raport wdrożenia

**Data:** 2026-04-21  
**Autor:** Claude (asystent), na zlecenie Artura  
**Feature:** Podsumowanie screeningów widoczne bez scrollowania i bez zmiany taba na profilu kandydata.  
**Plan źródłowy:** [~/.claude/plans/zbieranie-w-jedno-miejsce-podsumowanie-reflective-spring.md](../../../.claude/plans/zbieranie-w-jedno-miejsce-podsumowanie-reflective-spring.md)

## Cel
Zastąpić scrollowanie i przeklikiwanie się między 7 tabami — pokazać kluczowe fakty ze **wszystkich** screeningów kandydata w jednym miejscu na szczycie profilu.

## Zakres (wybór użytkownika)
- **Miejsce:** sticky card na górze profilu (widoczny niezależnie od aktywnego taba)
- **Forma:** strukturyzowane badge'e + listy (bez LLM)
- **Zakres danych:** tylko `screening_notes` (general notes, calls, Fireflies — osobny feature)

## Pliki zmienione

| Plik | Zmiana |
|------|--------|
| `backend/app/api/screenings.py` | Rozszerzenie `get_candidate_ai_profile` o nowe pola w response |
| `frontend/src/components/v2/pages/CandidateDetailV2.tsx` | Dodanie komponentu `ScreeningSummary` + integracja nad Tabs |

Brak migracji bazy — wszystkie nowe pola są obliczane w runtime z istniejących rekordów `screening_notes`.

## Zmiany backend

**`GET /api/candidates/{candidate_id}/ai-profile`** — nowe pola w response:

- `screening_count: int` (pre-existing)
- `motivation_top: string | null` — najczęstsza `motivation_primary` (mode)
- `salary_summary: { min, max, latest, currency, negotiable } | null` — zakres oczekiwań z trendu
- `red_flags_unique: string[]` — split po `,` i `\n`, dedup case-insensitive z zachowaniem oryginalnej pisowni
- `counteroffer_risk_dominant: "low" | "medium" | "high" | null` — mode z dystrybucji
- `last_screening: { id, created_at, author_id, screening_type, overall_impression } | null` — meta ostatniego wpisu

Pozostałe pola bez zmian: `motivation_trend`, `salary_trend`, `verified_skills_aggregate`, `warnings`, `overall_impression_avg`, `readiness_avg`, `counteroffer_risk_distribution`.

## Zmiany frontend

**`CandidateDetailV2.tsx`:**

1. Nowe importy ikon z `lucide-react`: `AlertTriangle`, `ChevronDown`, `ChevronUp`, `Gauge`, `ShieldAlert`, `Target`, `Wallet`
2. Integracja w JSX po sekcji "AI summary", przed `<SuggestedJobsWidget>` i `<Tabs>`:
   ```tsx
   {aiProfile && aiProfile.screening_count > 0 && (
     <ScreeningSummary
       aiProfile={aiProfile}
       onOpenScreenings={() => setActiveTab("screeningi")}
     />
   )}
   ```
3. Nowa inline funkcja `ScreeningSummary({ aiProfile, onOpenScreenings })` (~220 linii na końcu pliku):
   - `sticky top-0 z-20` — przyklejony do góry scroll-containera (main element w AppShellV2)
   - **Collapsed (default):** header (ikona Sparkles, "Podsumowanie screeningów · N rozmów · ostatnia X dni temu", przycisk "Rozwiń/Zwiń") + 5-6 badge'ów (Motywacja, Wynagrodzenie, Gotowość X/5, Counteroffer, Wrażenie X/5, Red flags N)
   - **Expanded:** Red flags list (chipy danger) + Verified skills top 5 (chipy success/soft) + Motivation trend (chronologia chipów outline) + CTA "Zobacz wszystkie screeningi →" (setActiveTab("screeningi"))
4. Typowane interfejsy: `AiProfile`, `VerifiedSkillAgg`, `SalarySummary`, `LastScreeningMeta`
5. Mapowania PL: `MOTIVATION_LABEL_PL` (money→Pieniądze, growth→Rozwój…), `RISK_LABEL_PL` (low→Niskie), `RISK_VARIANT` (low→success badge, medium→warning, high→danger)
6. Helper `pluralScreenings(n)` dla poprawnej polskiej odmiany (1 rozmowa / 2-4 rozmowy / 5+ rozmów)

Stylistyka: klasyczne Tailwind + CSS vars z `globals.css` (`hsl(var(--accent))`, `hsl(var(--text-muted))`, `hsl(var(--border-subtle))`, itd.) — naturalne w kontekście v2 shell'a, zerowy konflikt z burgundy/plum palette Dynaminds.

## Weryfikacja

### Zrealizowane ✅
- **Backend import smoke test:** `python3 -c "from app.api.screenings import get_candidate_ai_profile"` → OK
- **Frontend type-check:** `npm run type-check` → czysty dla `CandidateDetailV2.tsx` (5 pre-existing błędów w innych plikach, niezwiązane)
- **Endpoint live test:** `GET /api/candidates/1/ai-profile` (zalogowany admin) zwrócił wszystkie nowe pola, m.in.
  ```json
  {
    "screening_count": 1,
    "motivation_top": "money",
    "salary_summary": {"min":23000,"max":23000,"latest":23000,"currency":"PLN","negotiable":true},
    ...
  }
  ```
- **UI nawigacja:** login przez formularz, cookie `nexus_access` + localStorage (`access_token`, `nexus_user`), navigate na `/candidates/1`, CandidateDetailV2 ładuje się z Hero Card, tabami, widgetami.

### Odroczone ⏳
- **Finalny screenshot sticky card:** docker frontend build (nawet z `--no-cache`) uporczywie nie zabierał nowego kodu — `grep -c 'Podsumowanie screening' .next/server/app/candidates/[id]/page.js` zwracał 0 po każdym rebuild'zie. Hipoteza: tag `latest` mapowany do starego obrazu w lokalnym buildx registry (sprawdzono: `<none>:<none> 9 minutes ago 194MB` obok `nexusats-frontend:latest 3 days ago 332MB`). Pod koniec sesji docker daemon padł. **Zalecenie:** restart Docker Desktop, `docker image rm nexusats-frontend:latest`, potem `docker compose build --no-cache frontend && docker compose up -d --force-recreate frontend` lub alternatywnie odpalić `cd frontend && npm run dev` lokalnie (po poprawie pre-existing duplicate declaration `savedSearchesApi` w `src/lib/api.ts`).
- **Unit testy (Jest + RTL):** `CandidateDetailV2.test.tsx` z happy path + edge cases (0 screeningów, brak red_flags, 1 vs 4 screeningi) — do dodania w follow-up.
- **Backend test (pytest):** rozszerzenie `test_screenings.py` o nowe pola — do dodania.

## Napotkane pre-existing issues (poza zakresem feature'u, odnotowane)

1. **`backend/app/api/procedures.py:213`** — FastAPI AssertionError przy starcie: `status_code=204` z `-> None`. Auto-naprawione przez hook/linter dodaniem `response_model=None` w dekoratorze. Niezwiązane z tym feature'em, ale blokowało uvicorn startup więc zostało.
2. **`backend/app/api/public_share.py:207`** — FastAPI error z `ForwardRef('UploadFile')`. Auto-naprawione przez hook dodaniem `response_model=None`.
3. **Alembic multi-head** (`0029 duplicate` / `0031_candidate_invite_links` / `0031_champion_profile_notification_type`) — fallback do `Base.metadata.create_all` działa, nie blokuje startupu ostatecznie.
4. **Backend crash loop** (~1 min uptime między "Application startup complete" a "Shutting down"). Scheduled background tasks wpływają — niezwiązane z endpointem ai-profile ani frontendem. Utrudnia E2E verification (trzeba łapać okno uptime), ale nie zagraża produkcji w stabilnej infrze.

## Ograniczenia feature'u

- `motivation_top` to **mode** — dla 2 screeningów z różnymi motywacjami pokazuje tylko jeden (najstarszy z Counter). Akceptowalne dla MVP; jeśli potrzeba pokazywać wieloma równymi - badge "Motywacja: rozwój + pieniądze".
- `red_flags_unique` dedup jest case-insensitive po trim — "brak chęci zmiany" vs "brak chęci zmian" nadal duplikują się (fuzzy match Levenshtein poza zakresem).
- Sticky `top-0` w kontekście `<main class="overflow-y-auto">` AppShellV2 — przykleja się tuż pod TopbarV2 (56px) przez naturalny layout, ale nie testowane z bardzo małym viewport mobile.
- Brak LLM narracji — tylko strukturyzowane badge'e. Jeśli w przyszłości potrzeba narracji (`"Kandydat miał N rozmów, głównie zmotywowany przez X..."`) — osobny endpoint z cache'em i Anthropic API.

## Rekomendacje follow-up

1. Zrobić ostateczny screenshot UI po finalnym rebuild frontendu i dołączyć do tego raportu lub PR description.
2. Dodać unit testy (Jest + pytest) — szczególnie edge case `screening_count === 0` (komponent nie renderuje się).
3. Rozważyć rozszerzenie agregacji o general notes + Fireflies meetings (osobna decyzja produktowa).
4. Naprawić backend scheduled tasks crash loop — niezależny od tej zmiany, ale wpływa na ogólną UX.

## Commit (do wywołania przez użytkownika)

Gdy zechcesz zacommit'ować:
```
feat(candidates): sticky screening summary card on candidate profile

- backend: extend /ai-profile with motivation_top, salary_summary,
  red_flags_unique (dedup), counteroffer_risk_dominant, last_screening
- frontend: new ScreeningSummary component (sticky top-0) above tabs
  showing key screening data at a glance with collapsible details
- visible on all tabs; only renders when screening_count > 0
```
