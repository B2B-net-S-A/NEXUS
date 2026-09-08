/**
 * `JobReadinessDock` (krok 01 „Lista" i krok 02 „Zlecenie i Champion",
 * program „flow w języku C2", PR 4/7 i PR 5/7).
 *
 * Stany widoku dla `GET /api/jobs/{id}` (odczyt PIERWSZORZĘDNY — widoczny dla
 * każdej roli): pusto (brak zaznaczenia) / 403 / awaria / dane. Osobno:
 * `GET /api/jobs/{id}/readiness` (bramka „Przekaż do searchu", DRUGORZĘDNA —
 * `DeliveryLeadPlus` tylko, więc dla większości ról KOŃCZY SIĘ 403 i to NIE
 * jest błąd do ukrycia).
 *
 * `variant="champion"` (krok 02) dokłada zakładki „Zespół i priorytet" /
 * „Wyszukiwania (AI)" — dzieci tych zakładek (`ChampionVerificationChecklist`,
 * `ChampionRecommendedSearches`, `JobOwnershipPanel`, `HiringManagerPicker`,
 * `JobPriorityContext`, `JobHandoffButton`) są tu ZAMOCKOWANE: ten plik testuje
 * WIRING doku (który wariant/zakładka renderuje co i z jakimi propsami), nie
 * powtarza ich własnych testów/logiki.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JobReadinessDock,
  type JobReadinessDockListNav,
  type JobReadinessDockVariant,
} from "@/components/v2/jobs/JobReadinessDock";
import { ToastProvider } from "@/components/Toast";
import { useAuthStore, type User } from "@/store/auth";

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
vi.mock("@/components/ChampionRecommendedSearches", () => ({
  ChampionRecommendedSearches: (props: {
    canEdit: boolean;
    searches?: unknown[];
  }) => (
    <div
      data-testid="mock-recommended-searches"
      data-can-edit={String(props.canEdit)}
      data-count={String((props.searches ?? []).length)}
    />
  ),
}));
vi.mock("@/components/v2/jobs/JobOwnershipPanel", () => ({
  JobOwnershipPanel: (props: { primaryOwner: { name: string } | null }) => (
    <div
      data-testid="mock-ownership-panel"
      data-owner={props.primaryOwner?.name ?? ""}
    />
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
  JobHandoffButton: () => <div data-testid="mock-handoff-button" />,
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

// `DeliveryLeadPlus` — jedyna (poza adminem) rola, dla której backend w ogóle
// odpowiada na GET /readiness.
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
  recruitment_type: "body_leasing",
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
    // Bramka Championa/właściciela NIE renderuje się na błędzie — nie ma
    // z czego jej zbudować, a pokazanie pustej checklisty udawałoby dane.
    expect(screen.queryByText("Właściciel projektu")).not.toBeInTheDocument();
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
      screen.getByText("PKO Bank Polski · Body leasing · 16/9/2026/MW/4903"),
    ).toBeInTheDocument();

    // 5/5 — wszystkie pozycje checklisty spełnione w fixture.
    expect(screen.getByText("5")).toBeInTheDocument();

    expect(screen.getByText("Właściciel projektu")).toBeInTheDocument();
    expect(screen.getByText("Marta Kowalska")).toBeInTheDocument();

    expect(screen.getByText("Profil Championa")).toBeInTheDocument();
    expect(
      screen.getByText("Zweryfikowany z klientem i konsultantem."),
    ).toBeInTheDocument();

    expect(screen.getByText("Budżet kandydacki")).toBeInTheDocument();
    expect(screen.getByText("do 122.5 PLN/h")).toBeInTheDocument();

    expect(screen.getByText("Must / nice zsynchronizowane")).toBeInTheDocument();
    expect(
      screen.getByText("2 must · 1 nice · zasilają C2 i filtry."),
    ).toBeInTheDocument();

    expect(screen.getByText("Hiring manager (klient)")).toBeInTheDocument();
    expect(screen.getByText("Jan Nowak")).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: /Otwórz warsztat \(C2\)/ }),
    ).toHaveAttribute("href", "/jobs/501?tab=similar");
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
    // 3 + 2 + 1 = 6 w sześciu grupach; `rejected` jest terminalny i POZA nimi.
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

  it("brak ownera pokazuje przycisk Claim, który woła POST /api/jobs/{id}/claim", async () => {
    postMock.mockResolvedValue({ data: {} });
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, primary_owner: null } }),
    });
    renderDock(501);

    expect(
      await screen.findByText(
        "Nieprzypisany — nikt nie dostanie alertów deadline'u.",
      ),
    ).toBeInTheDocument();
    const claimButton = screen.getByRole("button", { name: "Claim" });

    claimButton.click();

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith("/api/jobs/501/claim"),
    );
  });

  it("head_of_recruitment ma zapis w pipeline, ale NIE dostaje przycisku Claim (backend: 403 „Read-only viewers cannot claim jobs”)", async () => {
    useAuthStore.setState({ user: headOfRecruitmentWrite });
    mockGetByUrl({
      job: () => Promise.resolve({ data: { ...jobFixture, primary_owner: null } }),
    });
    renderDock(501);

    expect(
      await screen.findByText(
        "Nieprzypisany — nikt nie dostanie alertów deadline'u.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Claim" })).not.toBeInTheDocument();
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

    await screen.findByText("Właściciel projektu");
    expect(screen.queryByRole("button", { name: "Claim" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Dodaj kandydata" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edytuj rekrutację" }),
    ).not.toBeInTheDocument();
    // Odczyt (checklista, nawigacja) NIE jest wyłączony przez readOnly.
    expect(
      screen.getByRole("link", { name: /Otwórz warsztat \(C2\)/ }),
    ).toBeInTheDocument();
  });
});

describe("JobReadinessDock — bramka „Przekaż do searchu”", () => {
  it("403 na GET /readiness pokazuje notatkę o widoczności dla DL/admina, nie błąd", async () => {
    mockGetByUrl({ readiness: () => Promise.reject(apiError(403)) });
    const { container } = renderDock(501);

    await screen.findByText("Programista Python (ZOB-2947)");
    // Substring z JEDNEJ linii JSX źródła — nie przechodzi przez łamanie
    // wiersza, żeby nie zależeć od dokładnego sposobu, w jaki JSX zwija
    // białe znaki na granicy linii.
    await waitFor(() =>
      expect(container.textContent).toContain(
        "widoczna dla Delivery Lead / admina",
      ),
    );
    expect(container.textContent).toContain("przypisanego do tego klienta");
  });

  it("recruiter NIE wysyła GET /readiness (backend: DeliveryLeadPlus) — notatka renderuje się bez sieci", async () => {
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(container.textContent).toContain("widoczna dla Delivery Lead / admina");
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
    // „Wyszukiwania (AI)" to zakładka kroku 02 — na liście jej nie ma.
    expect(
      screen.queryByRole("tab", { name: "Wyszukiwania (AI)" }),
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
    expect(screen.queryByText("Zatrudnieni")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Pipeline" }));

    // …a pełny rozkład pokazuje je wszystkie.
    for (const label of [
      "Nowi",
      "Screening",
      "Zweryfikowani",
      "U klienta",
      "Umowa",
      "Zatrudnieni",
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
    expect(screen.getByText("Właściciel projektu")).toBeInTheDocument();
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

  it("zakładka „Zespół i priorytet” pokazuje JobOwnershipPanel / HiringManagerPicker / JobPriorityContext, chowa checklistę gotowości", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    // Radix `Tabs.Trigger` aktywuje się na pełnej sekwencji zdarzeń
    // wskaźnika — goły `.click()` (sam event `click`) nie przełącza stanu;
    // `userEvent` odtwarza sekwencję tak jak w prawdziwej przeglądarce.
    await user.click(screen.getByRole("tab", { name: "Zespół i priorytet" }));

    expect(await screen.findByTestId("mock-ownership-panel")).toHaveAttribute(
      "data-owner",
      "Marta Kowalska",
    );
    expect(screen.getByTestId("mock-hm-picker")).toHaveAttribute(
      "data-can-edit",
      "true",
    );
    expect(screen.getByTestId("mock-priority-context")).toBeInTheDocument();
    expect(screen.queryByText("Właściciel projektu")).not.toBeInTheDocument();
  });

  it("„Gotowość” pokazuje TRZY pierwsze propozycje inline, a pełna zakładka „Wyszukiwania (AI)” — komplet", async () => {
    useAuthStore.setState({ user: deliveryLead });
    championGetMock.mockResolvedValue({
      data: {
        job_id: 501,
        champion_profile: {
          ...championProfileFixture.champion_profile,
          recommended_searches: [
            { id: "s1", name: "a", status: "proposed" },
            { id: "s2", name: "b", status: "proposed" },
            { id: "s3", name: "c", status: "proposed" },
            { id: "s4", name: "d", status: "proposed" },
          ],
        },
      },
    });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    const inline = await screen.findByTestId("mock-recommended-searches");
    await waitFor(() => expect(inline).toHaveAttribute("data-count", "3"));

    await user.click(screen.getByRole("tab", { name: "Wyszukiwania (AI)" }));
    const full = await screen.findByTestId("mock-recommended-searches");
    await waitFor(() => expect(full).toHaveAttribute("data-count", "4"));
  });

  it("JobHandoffButton (główna akcja) widoczny dla Delivery Lead", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(await screen.findByTestId("mock-handoff-button")).toBeInTheDocument();
  });

  it("„Dodaj kandydata” i „Edytuj rekrutację” zostają na kroku 02 (makieta ich nie rysuje, ale dziś tam są)", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.getByRole("button", { name: "Dodaj kandydata" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Edytuj rekrutację" }),
    ).toBeInTheDocument();
  });

  it("JobHandoffButton NIE renderuje się dla recruitera — handoff to decyzja DL/admina", async () => {
    // Domyślny user w beforeEach to `recruiterWrite`.
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);
    expect(screen.queryByTestId("mock-handoff-button")).not.toBeInTheDocument();
    // Checklista Championa też jest tylko do odczytu dla recruitera.
    const checklist = await screen.findByTestId("mock-verification-checklist");
    expect(checklist).toHaveAttribute("data-can-edit", "false");
  });

  it("recruiter widzi zakładkę „Zespół i priorytet”, ale HiringManagerPicker jest read-only (`job.update` = TacPlus)", async () => {
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText(CHAMPION_DOCK_LABEL);

    await user.click(screen.getByRole("tab", { name: "Zespół i priorytet" }));

    expect(await screen.findByTestId("mock-hm-picker")).toHaveAttribute(
      "data-can-edit",
      "false",
    );
  });
});
