# Kontrakt API: publikacja na RocketJobs i JustJoin.IT (Etap 1, 25.09.2026)

Jedno API dostawcy (Employer Public API 1EP, `integrations.rocketjobs.com/docs/1ep`)
obsługuje oba portale — pole `jobBoard` = `rocketjobs` | `justjoinit`. W NEXUSIE
to dwa portale (`Portal.rocketjobs`, `Portal.justjoinit`) z jednym adapterem
i jednym połączonym kontem firmy (OAuth `authorization_code` + refresh token).
Wszystko za flagami `PORTAL_ROCKETJOBS_ENABLED` / `PORTAL_JJIT_ENABLED` (domyślnie OFF).

## Typy wspólne

```ts
type JobPortal = "pracuj_pl" | "justjoinit" | "rocketjobs";
type PortalState = "disabled" | "misconfigured" | "not_connected" | "ready";
type PendingAction = "publish" | "update" | "close" | null;

interface PortalSalary { from: number; to: number; unit: "hour" | "month" } // netto B2B, PLN; to <= 3 × from
interface PortalListingOptions {
  category: string | null;          // klucz ze słownika portalu (wymagany do publikacji)
  experience_level: string | null;  // junior | mid | senior | c_level
  working_time: string | null;      // full_time | part_time | freelance | ...
  workplace_type: string | null;    // remote | office | hybrid
  office_days: number | null;       // tylko hybrid, 1–4
  city: string | null;              // wymagane (portal wymaga ≥ 1 lokalizacji)
  salary: PortalSalary | null;      // null = bez widełek (decyzja 25.09: nigdy z budżetu)
}
```

## Trasy

| Metoda i ścieżka | Kto | Odpowiedź |
|---|---|---|
| `GET /api/job-portals/config` | zalogowany | `{portals: [{portal, label, state, enabled}], any_ready}` — `state` ma nową wartość `not_connected` (flaga i klucze są, konto niepołączone) |
| `GET /api/job-boards/jjit/connection` | admin | `JobBoardConnectionRead` (niżej) |
| `GET /api/job-boards/jjit/authorize` | admin | `{authorize_url}` → front robi `window.location.href = …` |
| `DELETE /api/job-boards/jjit/connection` | admin | 204 |
| `GET /api/job-boards/jjit/callback` | publiczna | 302 na `/settings?item=job-boards&status=success|error&message=` |
| `GET /api/job-boards/{board}/dictionaries` | zalogowany, sekcja Sourcing | `{categories, experience_levels, working_times, workplace_types}` — każde `[{key, name}]`; `board` = `rocketjobs` / `justjoinit`; 409 gdy konto niepołączone |
| `GET /api/jobs/{id}/portal-listing-defaults` | odczyt rekrutacji | `PortalListingOptions` wyliczone z rekrutacji (kategoria zawsze `null`) |
| `GET /api/jobs/{id}/portals` | odczyt rekrutacji | `JobPostingRead[]` |
| `POST /api/jobs/{id}/portals/{portal}/publish` body `{options?: PortalListingOptions}` | edytor rekrutacji | `JobPostingRead`; 422 `{code:"listing_invalid", message, problems: string[]}` przy brakach |
| `PATCH /api/jobs/{id}/portals/{portal}/options` body `{options}` | edytor rekrutacji | `JobPostingRead` (żywe ogłoszenie dostaje `pending_action="update"`) |
| `POST /api/jobs/{id}/portals/{portal}/unpublish` | edytor rekrutacji | `JobPostingRead` |
| `POST /api/job-intake/public-draft` | admin / DL | `PublicDraftRead` (niżej); 503 gdy AI niedostępne |

```ts
interface JobPostingRead {
  id: number; portal: JobPortal; status: "draft"|"publishing"|"published"|"expired"|"removed"|"failed";
  external_id: string | null; url: string | null;
  published_at: string | null; last_synced_at: string | null; last_error: string | null;
  attempts: number; created_at: string | null; updated_at: string | null;
  options: PortalListingOptions | null;   // NOWE
  pending_action: PendingAction;          // NOWE
}

interface JobBoardBalance {
  codes: { name: string; remaining: number; expires_at: string | null; plan_key: string | null }[];
  subscriptions: { id: string; remaining: number; end_date: string | null; plan_key: string | null; active: boolean }[];
}
interface JobBoardConnectionRead {
  oauth_configured: boolean;            // JJIT_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI
  status: "not_connected" | "active" | "reconnect_required";
  connected_by_name: string | null; connected_at: string | null; last_error: string | null;
  boards: { board: "rocketjobs" | "justjoinit"; label: string; enabled: boolean;
            organization_unit_id: string | null;
            balance: JobBoardBalance | null; balance_error: string | null }[];
}

// POST /api/job-intake/public-draft — body
interface PublicDraftRequest {
  title: string; client_id: number | null;
  description?: string | null;           // tekst requestu
  must_skills?: string[]; nice_skills?: string[];
  location?: string | null; remote_policy?: "onsite"|"hybrid"|"remote"|null;
  onsite_days_per_week?: number | null;
  champion_profile?: Record<string, unknown> | null;  // to samo co PUT champion-profile
}
interface PublicDraftRead {
  public_title: string; subtitle: string; about: string;
  findings: { code: "client_name"|"money"|"contact"|"person_name"; message: string; excerpt: string }[];
}
```

## Przepływ na `/jobs/new` (po kroku „publikuj rekrutację”)

Istniejące trasy, w tej kolejności, dla zaznaczonych portali:
1. `PUT /api/jobs/{id}/public-profile` `{public_title, subtitle, about}`
2. `POST /api/jobs/{id}/public-profile/approve` (422 = uwagi kontroli)
3. `careerLinksApi.createInviteLink` (`POST /api/invite-links`, `CreateInviteLinkInput` z `job_id`, bez terminu; pomiń, gdy rekrutacja ma już aktywny link) (link `/r/<slug>` — kandydaci z portalu aplikują przez niego)
4. `POST /api/jobs/{id}/portals/{portal}/publish` `{options}` dla każdego portalu

Porażka po utworzeniu rekrutacji = toast + przejście na zakładkę udostępniania; rekrutacja zostaje.
