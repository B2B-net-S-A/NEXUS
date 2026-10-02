/**
 * `JobReadinessDock` (krok 01 „Lista" i krok 02 „Zlecenie i Champion",
 * program „flow w języku C2", PR 4/7 i PR 5/7).
 *
 * Stany widoku dla `GET /api/jobs/{id}` (odczyt PIERWSZORZĘDNY — widoczny dla
 * każdej roli): pusto (brak zaznaczenia) / 403 / awaria / dane. Osobno:
 * `GET /api/jobs/{id}/readiness` (bramka „Przekaż do searchu", DRUGORZĘDNA —
 * tylko z uprawnieniem „Rekrutacje: zakładanie, zamykanie, wysyłka CV do
 * klienta”, więc dla większości kont KOŃCZY SIĘ 403 i to NIE jest błąd do
 * ukrycia).
 *
 * `variant="champion"` (krok 02) dokłada zakładkę „Zespół”
 * (zakładka „Wyszukiwania (AI)” usunięta 25.09.2026) — dzieci doku
 * (`ChampionVerificationChecklist`, `JobSettingsPanel`, `JobOwnershipPanel`,
 * `HiringManagerPicker`, `JobPriorityContext`, `JobHandoffButton`) są tu
 * ZAMOCKOWANE: ten plik testuje WIRING doku (który wariant/zakładka renderuje
 * co i z jakimi propsami), nie powtarza ich własnych testów/logiki.
 *
 * Od 02.10.2026 rola przy rekrutacji nazywa się „Rekruter” (dawniej
 * „Właściciel projektu”): warunek gotowości spełnia osoba, która nad
 * rekrutacją PRACUJE — sama propozycja automatu to za mało.
 */

import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JobReadinessDock,
  type JobReadinessDockListNav,
  type JobReadinessDockVariant,
} from "@/components/v2/jobs/JobReadinessDock";
import { ToastProvider } from "@/components/Toast";
import { useAuthStore, type User } from "@/store/auth";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

const getMock = vi.fn();
const postMock = vi.fn();
const championGetMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    post: (...args: unknown[]) => postMock(...args),
  },
  championApi: {
    get: (...args: unknown[]) => championGetMock(...args),
  },
  EMPTY_CHAMPION_VERIFICATION: {
    client: { status: "pending", key_corrections: "", confirmed_as_is: false },
    consultant: { status: "pending", insights: "", skip_reason: "" },
  },
}));

vi.mock("@/components/AppShell", () => ({
  EditJobModal: () => null,
}));

vi.mock("@/components/v2/modals/AddCandidatesQuickModal", () => ({
  AddCandidatesQuickModal: () => null,
}));

// ── Krok 02 — dzieci zakładek doku, zamockowane (patrz nagłówek pliku) ──────
// `championVerificationDone` NIE jest komponentem — dok liczy z niej trzy
// warunki weryfikacji do licznika „kompletność zlecenia". Mock musi ją
// dostarczyć, inaczej import jest `undefined` i dok wywala się przy renderze.
vi.mock("@/components/ChampionVerificationChecklist", () => ({
  ChampionVerificationChecklist: (props: {
    canEdit: boolean;
    variant?: string;
  }) => (
    <div
      data-testid="mock-verification-checklist"
      data-can-edit={String(props.canEdit)}
      data-variant={props.variant ?? "section"}
    />
  ),
  championVerificationDone: (
    verification?: { client?: { status?: string }; consultant?: { status?: string } } | null,
    briefing?: { status?: string } | null,
  ) => ({
    client: verification?.client?.status === "verified",
    consultant:
      verification?.consultant?.status !== undefined &&
      verification.consultant.status !== "pending",
    briefing: briefing?.status === "attached",
  }),
}));
vi.mock("@/components/RequestHistorySection", () => ({
  RequestHistorySection: (props: { jobId: number; maxItems?: number }) => (
    <div
      data-testid="mock-request-history"
      data-job-id={String(props.jobId)}
      data-max-items={String(props.maxItems ?? "")}
    />
  ),
}));
vi.mock("@/components/v2/jobs/JobOwnershipPanel", () => ({
  JobOwnershipPanel: (props: {
    job: { primary_owner?: { name: string } | null };
    canEdit: boolean;
  }) => (
    <div
      data-testid="mock-ownership-panel"
      data-owner={props.job.primary_owner?.name ?? ""}
      data-can-edit={String(props.canEdit)}
    />
  ),
}));
// Karta zespołu dostaje wiersz „Rekruter” jako treść (`recruiters`) — mock ją
// renderuje, żeby było widać, że panel obsady siedzi W karcie.
vi.mock("@/components/v2/jobs/JobSettingsPanel", () => ({
  JobSettingsPanel: (props: {
    canEdit: boolean;
    canSetPriority: boolean;
    priorityLevel: string;
    categoryId: number | null;
    recruiters?: ReactNode;
  }) => (
    <div
      data-testid="mock-settings-panel"
      data-can-edit={String(props.canEdit)}
      data-can-set-priority={String(props.canSetPriority)}
      data-priority-level={props.priorityLevel}
      data-category-id={String(props.categoryId)}
    >
      {props.recruiters}
    </div>
  ),
}));
vi.mock("@/components/jobs/HiringManagerPicker", () => ({
  HiringManagerPicker: (props: { canEdit: boolean }) => (
    <div data-testid="mock-hm-picker" data-can-edit={String(props.canEdit)} />
  ),
}));
vi.mock("@/components/v2/priority-work", () => ({
  JobPriorityContext: () => <div data-testid="mock-priority-context" />,
}));
vi.mock("@/components/v2/jobs/JobHandoffButton", () => ({
  JobHandoffButton: (props: { priorityLevel?: string }) => (
    <div
      data-testid="mock-handoff-button"
      data-priority-level={props.priorityLevel ?? ""}
    />
  ),
}));

const recruiterWrite = {
  id: 7,
  name: "Marta Kowalska",
  email: "marta@example.com",
  role: "recruiter",
  roles: ["recruiter"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "write" },
} satisfies User;

const readOnlyUser = {
  ...recruiterWrite,
  effective_section_access: { pipeline: "read" },
} satisfies User;

// Delivery Lead ma domyślnie uprawnienie do prowadzenia rekrutacji — bez niego
// backend w ogóle nie odpowiada na GET /readiness. Profil bez migawki
// uprawnień liczy się z domyślnych uprawnień roli.
const deliveryLead = {
  ...recruiterWrite,
  id: 8,
  name: "Piotr Zieliński",
  role: "delivery_lead",
  roles: ["delivery_lead"],
} satisfies User;

// Zapis w sekcji pipeline, ale POZA `_OWNERSHIP_ELIGIBLE_ROLES` backendu —
// `POST /claim` odpowiada tej roli zawsze 403.
const headOfRecruitmentWrite = {
  ...recruiterWrite,
  id: 9,
  name: "Anna Wiśniewska",
  role: "head_of_recruitment",
  roles: ["head_of_recruitment"],
} satisfies User;

const jobFixture = {
  id: 501,
  title: "Programista Python (ZOB-2947)",
  client_id: 42,
  client_name: "PKO Bank Polski",
  reference_number: "16/9/2026/MW/4903",
  must_skills: ["Python", "Django"],
  nice_skills: ["AWS"],
  has_budget_hourly: true,
  rate_budget_hourly: 122.5,
  hiring_manager_contact_id: null,
  hiring_manager_name: "Jan Nowak",
  primary_owner: {
    id: 7,
    name: "Marta Kowalska",
    email: "marta@example.com",
    role: "recruiter",
  },
  collaborators: [],
  // `JobResponse.updated_at` — stopka doku listy („Ostatnia zmiana: …").
  updated_at: "2026-09-07T10:00:00Z",
  champion_profile: {
    verification: {
      client: { status: "verified" },
      consultant: { status: "verified" },
    },
  },
};

// Reużywana w testach `variant="champion"` — kształt `GET …/champion-profile`
// (`ChampionProfileResponse`), osobny od `jobFixture.champion_profile`
// (kształt `GET /api/jobs/{id}`) bo dok czyta je z DWÓCH różnych zapytań pod
// tym samym kluczem `["champion-profile", jobId]`.
const championProfileFixture = {
  job_id: 501,
  champion_profile: {
    verification: {
      client: { status: "verified" },
      consultant: { status: "verified" },
    },
    briefing: { status: "pending" },
    recommended_searches: [{ id: "s1", name: "Python + Kafka", status: "proposed" }],
  },
};

const readinessReady = {
  job_id: 501,
  ready: true,
  blockers: [],
  closed: false,
  already_handed_off: false,
};

function apiError(status: number) {
  const err: any = new Error(`request failed with status ${status}`);
  err.response = { status };
  return err;
}

/** Routes `api.get` by URL suffix so job-detail and readiness can be mocked independently. */
function mockGetByUrl(handlers: {
  job?: () => Promise<any>;
  readiness?: () => Promise<any>;
}) {
  getMock.mockImplementation((url: string) => {
    if (url.includes("/readiness")) {
      return (handlers.readiness ?? (() => Promise.resolve({ data: readinessReady })))();
    }
    return (handlers.job ?? (() => Promise.resolve({ data: jobFixture })))();
  });
}

function renderDock(
  jobId: number | null,
  stageBreakdown?: Record<string, number>,
  canOpen?: boolean,
  variant?: JobReadinessDockVariant,
  listNav?: JobReadinessDockListNav,
  collapsed?: boolean,
  onCollapsedChange?: (next: boolean) => void,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <JobReadinessDock
          jobId={jobId}
          stageBreakdown={stageBreakdown}
          canOpen={canOpen}
          variant={variant}
          listNav={listNav}
          collapsed={collapsed}
          onCollapsedChange={onCollapsedChange}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/** Kotwica „dane doszły" dla wariantu champion — tam nie ma tytułu zlecenia
 *  (nagłówek strony stoi tuż nad dokiem), więc czekamy na etykietę nagłówka. */
const CHAMPION_DOCK_LABEL = "Zlecenie · gotowość do searchu";

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  championGetMock.mockReset();
  championGetMock.mockResolvedValue({ data: championProfileFixture });
  useAuthStore.setState({
    user: recruiterWrite,
    realUser: null,
    token: "token",
    hydrated: true,
  });
  mockGetByUrl({});
});

describe("JobReadinessDock — pusto", () => {
  it("bez zaznaczonej rekrutacji pokazuje zachętę, nie pustkę bez wyjaśnienia", () => {
    renderDock(null);
    expect(
      screen.getByText(
        "Wybierz rekrutację z listy, aby zobaczyć gotowość zlecenia.",
      ),
    ).toBeInTheDocument();
    expect(getMock).not.toHaveBeenCalled();
  });
});

describe("JobReadinessDock — 403", () => {
  it("403 na GET /api/jobs/{id} renderuje 'Brak uprawnień', nie pustkę", async () => {
    mockGetByUrl({ job: () => Promise.reject(apiError(403)) });
    renderDock(501);

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Twoja rola nie ma dostępu do tej rekrutacji — poproś o dodanie Cię do jej zespołu.",
      ),
    ).toBeInTheDocument();
    // Checklista (Champion, rekruter) NIE renderuje się na błędzie — nie ma
    // z czego jej zbudować, a pokazanie pustej udawałoby dane.
    expect(screen.queryByText("Rekruter")).not.toBeInTheDocument();
  });
});

describe("JobReadinessDock — awaria", () => {
  it("500 (lub błąd sieci) renderuje 'Nie udało się pobrać danych' z Ponów", async () => {
    mockGetByUrl({ job: () => Promise.reject(apiError(500)) });
    renderDock(501);

    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Spróbuj ponownie/i }),
    ).toBeInTheDocument();
  });
});

describe("JobReadinessDock — dane", () => {
  it("renderuje checklistę gotowości (5/5) z tytułem, podtytułem i akcją Otwórz warsztat", async () => {
    renderDock(501);

    expect(await screen.findByText("Programista Python (ZOB-2947)")).toBeInTheDocument();
    expect(
      screen.getByText("PKO Bank Polski · 16/9/2026/MW/4903"),
    ).toBeInTheDocument();

    // 5/5 — wszystkie pozycje checklisty spełnione w fixture.
    expect(screen.getByText("5")).toBeInTheDocument();

    expect(screen.getByText("Rekruter")).toBeInTheDocument();
    expect(screen.getByText("Marta Kowalska")).toBeInTheDocument();
    expect(screen.queryByText("Właściciel projektu")).not.toBeInTheDocument();

    expect(screen.getByText("Profil Championa")).toBeInTheDocument();
    expect(
      screen.getByText("Zweryfikowany z klientem i konsultantem."),
    ).toBeInTheDocument();

    expect(screen.getByText("Budżet kandydacki")).toBeInTheDocument();
    expect(screen.getByText("do 122.5 PLN/h")).toBeInTheDocument();

    expect(screen.getByText("Must / nice zsynchronizowane")).toBeInTheDocument();
    expect(
      screen.getByText("2 must · 1 nice · zasilają AI Matching i filtry."),
    ).toBeInTheDocument();

    expect(screen.getByText("Hiring manager (klient)")).toBeInTheDocument();
    expect(screen.getByText("Jan Nowak")).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: /Otwórz propozycje z bazy/ }),
    ).toHaveAttribute("href", "/jobs/501?tab=people&seg=proposals");
  });

  it("bez stageBreakdown (spoza wczytanej strony) NIE renderuje sekcji Pipeline", async () => {
    renderDock(501, undefined);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(screen.queryByText(/^Pipeline ·/)).not.toBeInTheDocument();
  });

  it("stopka listy podaje datę ostatniej zmiany z `updated_at`, bez zmyślania autora", async () => {
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    // Makieta pisze „Klaudia U. zmieniła etap" — `JobResponse` nie niesie
    // autora zmiany, więc stopka mówi tylko to, co wie.
    expect(container.textContent).toContain("Ostatnia zmiana:");
    expect(container.textContent).not.toContain("zmieniła etap");
  });

  it("bez `updated_at` stopka po prostu się nie renderuje (zamiast «Ostatnia zmiana: —»)", async () => {
    const { updated_at: _drop, ...withoutUpdatedAt } = jobFixture;
    mockGetByUrl({ job: () => Promise.resolve({ data: withoutUpdatedAt }) });
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(container.textContent).not.toContain("Ostatnia zmiana:");
  });

  it("ze stageBreakdown z wiersza listy renderuje skrót pipeline'u, bez dodatkowego zapytania", async () => {
    renderDock(501, { new: 3, screening: 2, hired: 1, rejected: 4 });
    // 3 + 2 + 1 = 6 w ośmiu kolumnach; `rejected` jest terminalny i POZA nimi.
    expect(await screen.findByText("Pipeline · 6 kandydatów")).toBeInTheDocument();
    // Zero wywołań poza detalem — `stageBreakdown` przyszedł z propsa, a
    // bramki `/readiness` recruiter NIE pobiera (backend odpowiedziałby 403).
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));
    expect(getMock).toHaveBeenCalledWith("/api/jobs/501");
  });

  it("`canOpen={false}` (wiersz z `can_open: false`) — notatka o dostępie BEZ żadnego zapytania", async () => {
    renderDock(501, undefined, false);
    expect(
      await screen.findByText(
        "Nie masz dostępu do tej rekrutacji — poproś o dodanie Cię do jej zespołu.",
      ),
    ).toBeInTheDocument();
    // Dok nie strzela w GET /api/jobs/{id} → 403 na każdym wejściu na /jobs.
    expect(getMock).not.toHaveBeenCalled();
    expect(screen.queryByText("Brak uprawnień")).not.toBeInTheDocument();
  });

  it("konsultant POMINIĘTY (skipped) domyka pozycję Championa, ale opis nie twierdzi, że był zweryfikowany", async () => {
    mockGetByUrl({
      job: () =>
        Promise.resolve({
          data: {
            ...jobFixture,
            champion_profile: {
              verification: {
                client: { status: "verified" },
                consultant: { status: "skipped", skip_reason: "brak konsultanta" },
              },
            },
          },
        }),
    });
    renderDock(501);
    expect(
      await screen.findByText(
        "Zweryfikowany z klientem; konsultant pominięty — brak konsultanta.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("Champion częściowo zweryfikowany (tylko klient) pokazuje odpowiedni opis", async () => {
    mockGetByUrl({
      job: () =>
        Promise.resolve({
          data: {
            ...jobFixture,
            champion_profile: {
              verification: {
                client: { status: "verified" },
                consultant: { status: "pending" },
              },
            },
          },
        }),
    });
    renderDock(501);

    expect(
      await screen.findByText(
        "Częściowo zweryfikowany — brakuje drugiej strony (klient/konsultant).",
      ),
    ).toBeInTheDocument();
  });

  it("bez rekrutera pokazuje „Biorę”, które woła POST /api/jobs/{id}/claim i odświeża rekrutację", async () => {
    const user = userEvent.setup();
    postMock.mockResolvedValue({ data: {} });
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, primary_owner: null } }),
    });
    renderDock(501);

    expect(
      await screen.findByText(
        "Bez rekrutera — nikt jeszcze nie pracuje nad tą rekrutacją.",
      ),
    ).toBeInTheDocument();
    // Warunek „Rekruter” niespełniony: 4 z 5.
    expect(screen.getByText("4")).toBeInTheDocument();
    const jobReads = () =>
      getMock.mock.calls.filter(([url]) => url === "/api/jobs/501").length;
    const readsBefore = jobReads();

    await user.click(screen.getByRole("button", { name: "Biorę" }));

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith("/api/jobs/501/claim"),
    );
    // Odpowiedź zapisu nie niesie obsady — dok czyta rekrutację od nowa.
    await waitFor(() => expect(jobReads()).toBeGreaterThan(readsBefore));
    expect(
      await screen.findByText("Od teraz pracujesz nad tą rekrutacją."),
    ).toBeInTheDocument();
  });

  it("odmowa przy „Biorę” (ktoś był szybszy) pokazuje zdanie serwera i też odświeża rekrutację", async () => {
    const user = userEvent.setup();
    const refused: any = new Error("conflict");
    refused.response = { status: 409, data: { detail: "Ta rekrutacja ma już rekrutera" } };
    postMock.mockRejectedValue(refused);
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, primary_owner: null } }),
    });
    renderDock(501);
    await screen.findByText("Bez rekrutera — nikt jeszcze nie pracuje nad tą rekrutacją.");
    const jobReads = () =>
      getMock.mock.calls.filter(([url]) => url === "/api/jobs/501").length;
    const readsBefore = jobReads();

    await user.click(screen.getByRole("button", { name: "Biorę" }));

    expect(await screen.findByText("Ta rekrutacja ma już rekrutera")).toBeInTheDocument();
    await waitFor(() => expect(jobReads()).toBeGreaterThan(readsBefore));
  });

  it("pierwszy rekruter z nieaktywnym kontem: opis mówi o koncie i jest „Biorę” (R9-V2-2)", async () => {
    const user = userEvent.setup();
    postMock.mockResolvedValue({ data: {} });
    mockGetByUrl({
      job: () =>
        Promise.resolve({
          data: {
            ...jobFixture,
            primary_owner: { ...jobFixture.primary_owner, is_active: false },
          },
        }),
    });
    renderDock(501);

    expect(
      await screen.findByText("Bez rekrutera — Marta Kowalska ma nieaktywne konto."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Biorę" }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith("/api/jobs/501/claim"),
    );
  });

  it("sama propozycja automatu to jeszcze nie rekruter — warunek zostaje niespełniony", async () => {
    mockGetByUrl({
      job: () =>
        Promise.resolve({
          data: {
            ...jobFixture,
            primary_owner: null,
            recruiters: [
              {
                user_id: 31,
                name: "Anna Przykładowa",
                role: "recruiter",
                via: "assignment",
                proposed: true,
                assigned_by_name: null,
              },
            ],
          },
        }),
    });
    renderDock(501);

    expect(
      await screen.findByText(
        "Bez rekrutera — propozycja automatu (Anna Przykładowa) czeka na akceptację Head of Recruitment.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("lista `recruiters` z serwera wygrywa: wszystkie pracujące osoby, bez propozycji", async () => {
    mockGetByUrl({
      job: () =>
        Promise.resolve({
          data: {
            ...jobFixture,
            recruiters: [
              { user_id: 7, name: "Marta Kowalska", role: "recruiter", via: "owner", proposed: false, assigned_by_name: null },
              { user_id: 33, name: "Celina Wzorcowa", role: "sourcer", via: "collaborator", proposed: false, assigned_by_name: null },
              { user_id: 31, name: "Anna Przykładowa", role: "recruiter", via: "assignment", proposed: true, assigned_by_name: null },
            ],
          },
        }),
    });
    renderDock(501);

    expect(
      await screen.findByText("Marta Kowalska, Celina Wzorcowa"),
    ).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("zamkniętej rekrutacji nikt już nie bierze", async () => {
    mockGetByUrl({
      job: () =>
        Promise.resolve({
          data: { ...jobFixture, primary_owner: null, status: "closed" },
        }),
    });
    renderDock(501);

    await screen.findByText("Bez rekrutera — nikt jeszcze nie pracuje nad tą rekrutacją.");
    expect(screen.queryByRole("button", { name: "Biorę" })).not.toBeInTheDocument();
  });

  it("head_of_recruitment ma zapis w pipeline, ale NIE dostaje „Biorę” — przydziela innych, sam rekruterem nie zostaje", async () => {
    useAuthStore.setState({ user: headOfRecruitmentWrite });
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, primary_owner: null } }),
    });
    renderDock(501);

    expect(
      await screen.findByText(
        "Bez rekrutera — nikt jeszcze nie pracuje nad tą rekrutacją.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Biorę" })).not.toBeInTheDocument();
    // Inne mutacje sekcji pipeline (dodaj kandydata, edycja) zostają.
    expect(screen.getByRole("button", { name: "Dodaj kandydata" })).toBeInTheDocument();
  });
});

describe("JobReadinessDock — readOnly (RBAC)", () => {
  it("sesja bez zapisu do pipeline'u NIE pokazuje akcji mutujących, ale checklista zostaje", async () => {
    useAuthStore.setState({ user: readOnlyUser });
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, primary_owner: null } }),
    });
    renderDock(501);

    await screen.findByText("Rekruter");
    expect(screen.queryByRole("button", { name: "Biorę" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Dodaj kandydata" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edytuj rekrutację" }),
    ).not.toBeInTheDocument();
    // Odczyt (checklista, nawigacja) NIE jest wyłączony przez readOnly.
    expect(
      screen.getByRole("link", { name: /Otwórz propozycje z bazy/ }),
    ).toBeInTheDocument();
  });
});

describe("JobReadinessDock — bramka „Przekaż do searchu”", () => {
  // Notatka „kto to widzi” nazywa uprawnienie, o które można poprosić
  // administratora — nie rolę.
  const GATE_NOTICE =
    "widoczna z uprawnieniem „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”";

  it("403 na GET /readiness (Delivery Lead poza swoim klientem) pokazuje notatkę o widoczności, nie błąd", async () => {
    useAuthStore.setState({ user: deliveryLead });
    mockGetByUrl({ readiness: () => Promise.reject(apiError(403)) });
    const { container } = renderDock(501);

    await screen.findByText("Programista Python (ZOB-2947)");
    await waitFor(() => expect(container.textContent).toContain(GATE_NOTICE));
    expect(container.textContent).toContain("(Delivery Lead: u swoich klientów)");
    expect(container.textContent).not.toContain("Nie udało się sprawdzić bramki");
    expect(getMock).toHaveBeenCalledWith("/api/jobs/501/readiness");
  });

  it("recruiter bez uprawnienia NIE wysyła GET /readiness — notatka renderuje się bez sieci", async () => {
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(container.textContent).toContain(GATE_NOTICE);
    expect(container.textContent).not.toContain("widoczna dla Delivery Lead / admina");
    expect(getMock).not.toHaveBeenCalledWith("/api/jobs/501/readiness");
  });

  it("recruiter z nadanym uprawnieniem widzi bramkę jak Delivery Lead", async () => {
    useAuthStore.setState({
      user: {
        ...recruiterWrite,
        effective_action_access: permissionSnapshot("recruitment_manage"),
      },
    });
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    await waitFor(() =>
      expect(container.textContent).toContain("Bramka „Przekaż do searchu”: gotowa"),
    );
    expect(getMock).toHaveBeenCalledWith("/api/jobs/501/readiness");
  });

  it("Delivery Lead z wyłączonym uprawnieniem nie pyta o bramkę mimo roli", async () => {
    useAuthStore.setState({
      user: {
        ...deliveryLead,
        effective_action_access: permissionSnapshot("delivery_view", "clients_edit"),
      },
    });
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(container.textContent).toContain(GATE_NOTICE);
    expect(getMock).not.toHaveBeenCalledWith("/api/jobs/501/readiness");
  });

  it("uprawnienie bez dostępu do sekcji rekrutacji nie wysyła zapytania o bramkę", async () => {
    useAuthStore.setState({
      user: { ...deliveryLead, effective_section_access: { pipeline: "none" } },
    });
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(container.textContent).toContain(GATE_NOTICE);
    expect(getMock).not.toHaveBeenCalledWith("/api/jobs/501/readiness");
  });

  it("Delivery Lead widzi bramkę: status „gotowa” z GET /readiness", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    await waitFor(() =>
      expect(container.textContent).toContain(
        "Bramka „Przekaż do searchu”: gotowa",
      ),
    );
    expect(getMock).toHaveBeenCalledWith("/api/jobs/501/readiness");
  });

  it("zablokowana bramka to JEDNA linia z licznikiem braków — lista jest o jedno kliknięcie, nic nie znika", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const user = userEvent.setup();
    mockGetByUrl({
      readiness: () =>
        Promise.resolve({
          data: {
            ...readinessReady,
            ready: false,
            blockers: ["Brak kontekstu projektu", "Za mało pytań screeningowych"],
          },
        }),
    });
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");

    const toggle = await screen.findByRole("button", {
      name: /Bramka „Przekaż do searchu”: zablokowana/,
    });
    expect(toggle).toHaveTextContent("2 braki");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Zwinięta — treść blokerów jeszcze nie jest w dokumencie…
    expect(container.textContent).not.toContain("Brak kontekstu projektu");

    await user.click(toggle);

    // …a po kliknięciu jest, w całości.
    expect(await screen.findByText("Brak kontekstu projektu")).toBeInTheDocument();
    expect(screen.getByText("Za mało pytań screeningowych")).toBeInTheDocument();
  });

  it("licznik checklisty nazywa się „kompletność zlecenia”, nie „gotowość do searchu” — to inny zbiór niż bramka", async () => {
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(container.textContent).toContain("kompletność zlecenia");
    expect(container.textContent).not.toContain("gotowość zlecenia do searchu");
  });
});

describe("JobReadinessDock — variant \"list\" (krok 01), zakładki fali 3", () => {
  it("ma cztery zakładki listy i NIE montuje treści kroku 02", async () => {
    renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");

    for (const label of ["Gotowość", "Pipeline", "Zespół", "Historia"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    // „Wyszukiwania (AI)” usunięte 25.09.2026 — nie ma jej nigdzie.
    expect(
      screen.queryByRole("tab", { name: "Wyszukiwania" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("mock-handoff-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mock-ownership-panel")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("mock-verification-checklist"),
    ).not.toBeInTheDocument();
    // `championApi.get` w ogóle nie jest odpytywane poza wariantem "champion".
    expect(championGetMock).not.toHaveBeenCalled();
  });

  it("zakładka „Pipeline” pokazuje WSZYSTKIE grupy, także zerowe (rozkład, nie skrót)", async () => {
    const user = userEvent.setup();
    renderDock(501, { new: 3, screening: 2, rejected: 4 });
    await screen.findByText("Programista Python (ZOB-2947)");

    // Skrót w „Gotowość" pomija grupy zerowe…
    expect(screen.queryByText("Zatrudniony")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Pipeline" }));

    // …a pełny rozkład pokazuje je wszystkie — te same osiem kolumn co
    // Tablica i wiersz listy (lista v5).
    for (const label of [
      "Nowi",
      "Screening",
      "Zweryfikowany",
      "QC CV",
      "CV wysłane",
      "Rozmowa u klienta",
      "Umowa",
      "Zatrudniony",
      "Odrzuceni / wycofani",
    ]) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
  });

  it("zakładka „Zespół” na liście niesie DOKŁADNIE tę samą treść co na kroku 02", async () => {
    const user = userEvent.setup();
    renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");

    await user.click(screen.getByRole("tab", { name: "Zespół" }));

    expect(await screen.findByTestId("mock-ownership-panel")).toBeInTheDocument();
    expect(screen.getByTestId("mock-hm-picker")).toBeInTheDocument();
    expect(screen.getByTestId("mock-priority-context")).toBeInTheDocument();
  });

  it("zakładka „Historia” montuje RequestHistorySection w trybie kompaktowym", async () => {
    const user = userEvent.setup();
    renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");

    await user.click(screen.getByRole("tab", { name: "Historia" }));

    const history = await screen.findByTestId("mock-request-history");
    expect(history).toHaveAttribute("data-job-id", "501");
    expect(history).toHaveAttribute("data-max-items", "3");
  });
});

describe("JobReadinessDock — `listNav` (przewijanie po wierszach strony)", () => {
  const nav = (over: Partial<JobReadinessDockListNav> = {}) => ({
    index: 1,
    total: 12,
    onPrev: vi.fn(),
    onNext: vi.fn(),
    ...over,
  });

  it("bez `listNav` nagłówek nie udaje nawigacji", async () => {
    renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(screen.queryByTestId("dock-list-nav")).not.toBeInTheDocument();
  });

  it("z `listNav` pokazuje „N z M” i woła onNext", async () => {
    const user = userEvent.setup();
    const listNav = nav();
    renderDock(501, undefined, true, "list", listNav);
    await screen.findByText("Programista Python (ZOB-2947)");

    expect(screen.getByText("1 z 12")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Następna rekrutacja" }));
    expect(listNav.onNext).toHaveBeenCalledTimes(1);
  });

  it("na pierwszym wierszu „Poprzednia” jest wyłączona, na ostatnim „Następna”", async () => {
    const { unmount } = renderDock(501, undefined, true, "list", nav({ index: 1 }));
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(screen.getByRole("button", { name: "Poprzednia rekrutacja" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Następna rekrutacja" })).toBeEnabled();
    unmount();

    renderDock(501, undefined, true, "list", nav({ index: 12 }));
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(screen.getByRole("button", { name: "Następna rekrutacja" })).toBeDisabled();
  });
});

describe("JobReadinessDock — variant=\"champion\" (krok 02)", () => {
  it("domyślna zakładka to „Gotowość” — jedna lista: trzy wiersze weryfikacji + cztery warunki zlecenia", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    expect(screen.getByRole("tab", { name: "Gotowość" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("Rekruter")).toBeInTheDocument();
    const checklist = await screen.findByTestId("mock-verification-checklist");
    expect(checklist).toHaveAttribute("data-can-edit", "true");
    // Weryfikacja jest teraz WIERSZAMI tej samej listy, nie osobnym blokiem.
    expect(checklist).toHaveAttribute("data-variant", "rows");
    // Zakładka „Zespół i priorytet” NIE renderuje się, dopóki nie jest aktywna.
    expect(screen.queryByTestId("mock-ownership-panel")).not.toBeInTheDocument();
  });

  it("na kroku 02 nie ma wiersza „Profil Championa” — jego treścią są trzy wiersze weryfikacji", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.queryByText("Profil Championa")).not.toBeInTheDocument();
    // Za to jest wiersz o stacku pod nazwą z makiety.
    expect(screen.getByText("Stack → must / nice")).toBeInTheDocument();
  });

  it("pusty stack starego profilu nie przykrywa kolumn rekrutacji (M04-B02)", async () => {
    useAuthStore.setState({ user: deliveryLead });
    championGetMock.mockResolvedValue({
      data: {
        ...championProfileFixture,
        champion_profile: {
          ...championProfileFixture.champion_profile,
          // Kształt z API po migracji leniwej: obiekt stacku JEST, ale pusty.
          stack: { must: [], nice: [], notes: "" },
        },
      },
    });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(
      await screen.findByText("2 must · 1 nice · zasilają AI Matching i filtry."),
    ).toBeInTheDocument();
  });

  it("wypełniony stack Championa nadal wygrywa z kolumnami", async () => {
    useAuthStore.setState({ user: deliveryLead });
    championGetMock.mockResolvedValue({
      data: {
        ...championProfileFixture,
        champion_profile: {
          ...championProfileFixture.champion_profile,
          stack: { must: [{ name: "Go" }], nice: [], notes: "" },
        },
      },
    });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(
      await screen.findByText("1 must · 0 nice · zasilają AI Matching i filtry."),
    ).toBeInTheDocument();
  });

  it("licznik liczy SIEDEM warunków (4 zlecenia + 3 weryfikacji), gdy profil Championa się wczytał", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const { container } = renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    // Fixture: klient + konsultant zweryfikowani, briefing `pending` →
    // 4 warunki zlecenia + 2 weryfikacji = 6 z 7.
    await waitFor(() => expect(container.textContent).toContain("/ 7 · kompletność zlecenia"));
    expect(container.textContent).toContain("(86%)");
  });

  it("gdy profil Championa się NIE wczytał, mianownik NIE udaje wiedzy o trzech brakujących warunkach", async () => {
    useAuthStore.setState({ user: deliveryLead });
    championGetMock.mockRejectedValue(apiError(500));
    const { container } = renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    await waitFor(() =>
      expect(container.textContent).toContain("Nie udało się pobrać Profilu Championa."),
    );
    // Cztery warunki, o których wiemy — nie siedem z trzema fałszywymi brakami.
    expect(container.textContent).toContain("/ 4 · kompletność zlecenia");
  });

  it("zakładka „Zespół” pokazuje JobOwnershipPanel / HiringManagerPicker / JobPriorityContext, chowa checklistę gotowości", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    // Radix `Tabs.Trigger` aktywuje się na pełnej sekwencji zdarzeń
    // wskaźnika — goły `.click()` (sam event `click`) nie przełącza stanu;
    // `userEvent` odtwarza sekwencję tak jak w prawdziwej przeglądarce.
    await user.click(screen.getByRole("tab", { name: "Zespół" }));

    expect(await screen.findByTestId("mock-ownership-panel")).toHaveAttribute(
      "data-owner",
      "Marta Kowalska",
    );
    expect(screen.getByTestId("mock-hm-picker")).toHaveAttribute(
      "data-can-edit",
      "true",
    );
    expect(screen.getByTestId("mock-priority-context")).toBeInTheDocument();
    // Checklista gotowości (z wierszem „Rekruter”) znika razem z zakładką.
    expect(screen.queryByText("Budżet kandydacki")).not.toBeInTheDocument();
    expect(screen.queryByText("Rekruter")).not.toBeInTheDocument();
  });

  it("krok 02 nie ma już rekomendowanych wyszukiwań (AI) — ani zakładki, ani podglądu", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.queryByRole("tab", { name: "Wyszukiwania" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Zespół" })).toBeInTheDocument();
  });

  it("JobHandoffButton (główna akcja) widoczny dla Delivery Lead", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(await screen.findByTestId("mock-handoff-button")).toBeInTheDocument();
  });

  it("na kroku 02 nie ma „Dodaj kandydata”, „Edytuj rekrutację” ani „Otwórz propozycje” — są w nagłówku i menu „⋯”", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.queryByRole("button", { name: "Dodaj kandydata" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edytuj rekrutację" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Otwórz propozycje z bazy/ })).not.toBeInTheDocument();
  });

  it("panel zlecenia ma zakładki Gotowość, Zespół, Ogłoszenie — „Historia” przeszła do edycji Championa", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.getByRole("tab", { name: "Ogłoszenie" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Historia" })).not.toBeInTheDocument();
  });

  it("zakładka „Ogłoszenie” niesie opis z AI, link aplikacyjny i portale", async () => {
    const user = userEvent.setup();
    const onWrite = vi.fn();
    const onLink = vi.fn();
    useAuthStore.setState({ user: deliveryLead });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <JobReadinessDock
            jobId={501}
            canOpen
            variant="champion"
            onWriteAnnouncement={onWrite}
            onGenerateInviteLink={onLink}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );
    await screen.findByText(CHAMPION_DOCK_LABEL);
    await user.click(screen.getByRole("tab", { name: "Ogłoszenie" }));
    await user.click(await screen.findByRole("button", { name: "Napisz ogłoszenie z AI" }));
    expect(onWrite).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Wygeneruj link aplikacyjny" }));
    expect(onLink).toHaveBeenCalledOnce();
  });

  it("zakładkę panelu da się otworzyć z adresu (`panelTab`) — skrót zlecenia prowadzi wprost do „Zespołu”", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <JobReadinessDock jobId={501} canOpen variant="champion" panelTab="team" />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("mock-priority-context")).toBeInTheDocument();
  });

  it("JobHandoffButton NIE renderuje się dla recruitera bez uprawnienia do prowadzenia rekrutacji", async () => {
    // Domyślny user w beforeEach to `recruiterWrite`.
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.queryByTestId("mock-handoff-button")).not.toBeInTheDocument();
    // Checklista Championa też jest tylko do odczytu dla recruitera.
    const checklist = await screen.findByTestId("mock-verification-checklist");
    expect(checklist).toHaveAttribute("data-can-edit", "false");
  });

  it("recruiter z nadanym uprawnieniem do prowadzenia rekrutacji dostaje „Przekaż do searchu”", async () => {
    useAuthStore.setState({
      user: {
        ...recruiterWrite,
        effective_action_access: permissionSnapshot("recruitment_manage"),
      },
    });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(await screen.findByTestId("mock-handoff-button")).toBeInTheDocument();
  });

  it("Delivery Lead z wyłączonym uprawnieniem nie dostaje „Przekaż do searchu” mimo roli", async () => {
    useAuthStore.setState({
      user: {
        ...deliveryLead,
        effective_action_access: permissionSnapshot("delivery_view", "clients_edit"),
      },
    });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.queryByTestId("mock-handoff-button")).not.toBeInTheDocument();
  });

  it("w podglądzie jako inny użytkownik nie ma „Przekaż do searchu”", async () => {
    useAuthStore.setState({ user: deliveryLead, realUser: recruiterWrite });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.queryByTestId("mock-handoff-button")).not.toBeInTheDocument();
  });

  it("recruiter z prawem edycji treści (`can_edit`) też NIE dostaje „Przekaż do searchu” — to osobne uprawnienie", async () => {
    // Do 28.09.2026 przycisk wisiał na `canEditChampion`, a `can_edit` z
    // serwera dostaje też rekruter prowadzący: widział aktywny przycisk,
    // /readiness odpowiadało mu 403, a klik kończył się drugim 403.
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, can_edit: true } }),
    });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    const checklist = await screen.findByTestId("mock-verification-checklist");
    // Edycja Championa zostaje — odbieramy wyłącznie przekazanie do searchu.
    expect(checklist).toHaveAttribute("data-can-edit", "true");
    expect(screen.queryByTestId("mock-handoff-button")).not.toBeInTheDocument();
  });

  it("recruiter widzi zakładkę „Zespół”, ale HiringManagerPicker jest read-only (`job.update` = TacPlus)", async () => {
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    await user.click(screen.getByRole("tab", { name: "Zespół" }));

    expect(await screen.findByTestId("mock-hm-picker")).toHaveAttribute(
      "data-can-edit",
      "false",
    );
    // JobSettingsPanel dzieli TĘ SAMĄ bramkę co HiringManagerPicker
    // (`canWritePipeline && canUpdateJob`) — jedna kopia `job.update`, nie dwie.
    expect(screen.getByTestId("mock-settings-panel")).toHaveAttribute(
      "data-can-edit",
      "false",
    );
  });

  it("zakładka „Zespół”: wiersz „Rekruter” siedzi W karcie zespołu, nad hiring managerem, z `canEdit` DL-a", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    await user.click(screen.getByRole("tab", { name: "Zespół" }));

    const card = await screen.findByTestId("mock-settings-panel");
    expect(card).toHaveAttribute("data-can-edit", "true");
    expect(within(card).getByTestId("mock-ownership-panel")).toBeInTheDocument();
    expect(
      card.compareDocumentPosition(screen.getByTestId("mock-hm-picker")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("karta zespołu dostaje kategorię i priorytet rekrutacji; okno przekazania — ten sam priorytet", async () => {
    useAuthStore.setState({ user: deliveryLead });
    mockGetByUrl({
      job: () =>
        Promise.resolve({
          data: { ...jobFixture, competence_category_id: 2, priority_level: "accepting" },
        }),
    });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(await screen.findByTestId("mock-handoff-button")).toHaveAttribute(
      "data-priority-level",
      "accepting",
    );

    await user.click(screen.getByRole("tab", { name: "Zespół" }));

    const card = await screen.findByTestId("mock-settings-panel");
    expect(card).toHaveAttribute("data-category-id", "2");
    expect(card).toHaveAttribute("data-priority-level", "accepting");
  });

  it.each([
    ["Delivery Lead (rola)", deliveryLead, {}, "true"],
    ["Head of Recruitment (rola)", headOfRecruitmentWrite, {}, "true"],
    ["rekruter", recruiterWrite, {}, "false"],
    ["Delivery Lead spoza zakresu (`can_set_priority: false` z serwera)", deliveryLead, { can_set_priority: false }, "false"],
    ["rekruter, któremu serwer pozwala (`can_set_priority: true`)", recruiterWrite, { can_set_priority: true }, "true"],
  ] as const)("priorytet ustawia: %s → %s", async (_name, as, flags, expected) => {
    useAuthStore.setState({ user: as });
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, ...flags } }),
    });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    await user.click(screen.getByRole("tab", { name: "Zespół" }));

    expect(await screen.findByTestId("mock-settings-panel")).toHaveAttribute(
      "data-can-set-priority",
      expected,
    );
  });

  it("Head of Recruitment: priorytet tak, Delivery Lead i termin nie (to pełna edycja), kolejne osoby — jak każdy redagujący", async () => {
    useAuthStore.setState({ user: headOfRecruitmentWrite });
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, can_edit: true } }),
    });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    await user.click(screen.getByRole("tab", { name: "Zespół" }));

    const card = await screen.findByTestId("mock-settings-panel");
    expect(card).toHaveAttribute("data-can-edit", "false");
    expect(card).toHaveAttribute("data-can-set-priority", "true");
    expect(screen.getByTestId("mock-ownership-panel")).toHaveAttribute(
      "data-can-edit",
      "true",
    );
  });

  it("sesja bez zapisu w sekcji nie ustawia priorytetu, nawet gdy serwer mówi `can_set_priority: true`", async () => {
    useAuthStore.setState({ user: { ...deliveryLead, effective_section_access: { pipeline: "read" } } });
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, can_set_priority: true } }),
    });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    await user.click(screen.getByRole("tab", { name: "Zespół" }));

    expect(await screen.findByTestId("mock-settings-panel")).toHaveAttribute(
      "data-can-set-priority",
      "false",
    );
  });
});

describe("JobReadinessDock — zwijanie doku (krok 02)", () => {
  it('bez `onCollapsedChange` renderuje się w pełni niezależnie od `collapsed` (np. `variant="list"`)', async () => {
    renderDock(501, undefined, true, "list", undefined, true, undefined);
    expect(await screen.findByText(jobFixture.title)).toBeInTheDocument();
    expect(
      screen.queryByTestId("job-readiness-dock-collapsed"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("job-readiness-dock-full")).not.toHaveClass(
      "xl:hidden",
    );
  });

  it('`collapsed=true` na `variant="champion"` renderuje pasek 44 px z przyciskiem „Rozwiń" i licznikiem done/total', async () => {
    const onCollapsedChange = vi.fn();
    renderDock(501, undefined, true, "champion", undefined, true, onCollapsedChange);

    const strip = await screen.findByTestId("job-readiness-dock-collapsed");
    expect(
      within(strip).getByRole("button", { name: "Rozwiń dok gotowości" }),
    ).toBeInTheDocument();
    // 4 wiersze doku (must/nice, budżet, właściciel, HM) + 3 warunki
    // weryfikacji Championa (klient/konsultant zweryfikowani, briefing
    // „pending") = 6 z 7 — liczone z TYCH SAMYCH zapytań, które karmią pełny
    // widok (patrz komentarz przy `JobReadinessDockProps.collapsed`).
    expect(within(strip).getByText("6/7")).toBeInTheDocument();
    // Pasek widać WYŁĄCZNIE na `xl`; wężej zostaje pełny dok (jsdom nie liczy
    // media queries, więc kontrakt pilnujemy na klasach).
    expect(strip).toHaveClass("hidden", "xl:flex");
    expect(screen.getByTestId("job-readiness-dock-full")).toHaveClass("xl:hidden");
  });

  it('kliknięcie „Rozwiń dok gotowości" woła `onCollapsedChange(false)`', async () => {
    const user = userEvent.setup();
    const onCollapsedChange = vi.fn();
    renderDock(501, undefined, true, "champion", undefined, true, onCollapsedChange);

    await user.click(
      await screen.findByRole("button", { name: "Rozwiń dok gotowości" }),
    );
    expect(onCollapsedChange).toHaveBeenCalledWith(false);
  });

  it('rozwinięty dok (krok 02) pokazuje „Zwiń dok gotowości" obok kopiowania linku TYLKO z `onCollapsedChange`', async () => {
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(
      screen.queryByRole("button", { name: "Zwiń dok gotowości" }),
    ).not.toBeInTheDocument();

    const onCollapsedChange = vi.fn();
    renderDock(501, undefined, true, "champion", undefined, false, onCollapsedChange);
    expect(
      await screen.findByRole("button", { name: "Zwiń dok gotowości" }),
    ).toBeInTheDocument();
  });

  it('kliknięcie „Zwiń dok gotowości" woła `onCollapsedChange(true)`', async () => {
    const user = userEvent.setup();
    const onCollapsedChange = vi.fn();
    renderDock(501, undefined, true, "champion", undefined, false, onCollapsedChange);
    await screen.findByText(CHAMPION_DOCK_LABEL);

    await user.click(
      await screen.findByRole("button", { name: "Zwiń dok gotowości" }),
    );
    expect(onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it('„Zwiń dok gotowości" NIE renderuje się na `variant="list"` (kolumna listy nie zwija się)', async () => {
    const onCollapsedChange = vi.fn();
    renderDock(501, undefined, true, "list", undefined, false, onCollapsedChange);
    expect(await screen.findByText(jobFixture.title)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Zwiń dok gotowości" }),
    ).not.toBeInTheDocument();
  });
});

describe("JobReadinessDock — szczegóły z wiersza listy (02.10.2026)", () => {
  it("`listDetails` stoi na górze „Gotowości”, a podtytuł pokazuje samego klienta", async () => {
    mockGetByUrl({});
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <JobReadinessDock
            jobId={501}
            canOpen
            listDetails={<div data-testid="details">Nasz numer 16/9/2026/MW/4903</div>}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );

    const details = await screen.findByTestId("details");
    // Numer stoi w sekcji szczegółów, więc nagłówek go nie powtarza.
    expect(screen.getByText("PKO Bank Polski")).toBeInTheDocument();
    expect(
      screen.queryByText("PKO Bank Polski · 16/9/2026/MW/4903"),
    ).not.toBeInTheDocument();
    // Szczegóły przed licznikiem kompletności.
    const score = screen.getByText(/kompletność zlecenia/);
    expect(
      details.compareDocumentPosition(score) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
