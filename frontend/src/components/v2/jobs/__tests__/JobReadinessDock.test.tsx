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
vi.mock("@/components/ChampionVerificationChecklist", () => ({
  ChampionVerificationChecklist: (props: { canEdit: boolean }) => (
    <div
      data-testid="mock-verification-checklist"
      data-can-edit={String(props.canEdit)}
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
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

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

  it("licznik checklisty nazywa się „kompletność zlecenia”, nie „gotowość do searchu” — to inny zbiór niż bramka", async () => {
    const { container } = renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(container.textContent).toContain("kompletność zlecenia");
    expect(container.textContent).not.toContain("gotowość zlecenia do searchu");
  });
});

describe("JobReadinessDock — variant domyślny (\"list\", krok 01) bez zmian", () => {
  it("nie renderuje zakładek ani zakładkowej treści kroku 02 — dok wygląda dokładnie jak przed PR 5/7", async () => {
    renderDock(501);
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mock-handoff-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mock-ownership-panel")).not.toBeInTheDocument();
    // `championApi.get` w ogóle nie jest odpytywane poza wariantem "champion".
    expect(championGetMock).not.toHaveBeenCalled();
  });
});

describe("JobReadinessDock — variant=\"champion\" (krok 02)", () => {
  it("domyślna zakładka to „Gotowość” — checklista + ChampionVerificationChecklist (weryfikacja + briefing) widoczne", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText("Programista Python (ZOB-2947)");

    expect(screen.getByRole("tab", { name: "Gotowość" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("Właściciel projektu")).toBeInTheDocument();
    const checklist = await screen.findByTestId("mock-verification-checklist");
    expect(checklist).toHaveAttribute("data-can-edit", "true");
    // Zakładki drugorzędne NIE renderują się, dopóki nie są aktywne.
    expect(screen.queryByTestId("mock-ownership-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mock-recommended-searches")).not.toBeInTheDocument();
  });

  it("zakładka „Zespół i priorytet” pokazuje JobOwnershipPanel / HiringManagerPicker / JobPriorityContext, chowa checklistę gotowości", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText("Programista Python (ZOB-2947)");

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

  it("zakładka „Wyszukiwania (AI)” pokazuje ChampionRecommendedSearches z propozycjami z champion-profile", async () => {
    useAuthStore.setState({ user: deliveryLead });
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText("Programista Python (ZOB-2947)");

    await user.click(screen.getByRole("tab", { name: "Wyszukiwania (AI)" }));

    const searches = await screen.findByTestId("mock-recommended-searches");
    expect(searches).toHaveAttribute("data-can-edit", "true");
    // `data-count` zależy od `championQuery` (osobne zapytanie od `jobQuery`,
    // które ten test dotąd nie czekał) — `waitFor`, żeby nie złapać renderu
    // sprzed rozwiązania promisa.
    await waitFor(() => expect(searches).toHaveAttribute("data-count", "1"));
  });

  it("JobHandoffButton (główna akcja) widoczny dla Delivery Lead", async () => {
    useAuthStore.setState({ user: deliveryLead });
    renderDock(501, undefined, true, "champion");
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(await screen.findByTestId("mock-handoff-button")).toBeInTheDocument();
  });

  it("JobHandoffButton NIE renderuje się dla recruitera — handoff to decyzja DL/admina", async () => {
    // Domyślny user w beforeEach to `recruiterWrite`.
    renderDock(501, undefined, true, "champion");
    await screen.findByText("Programista Python (ZOB-2947)");
    expect(screen.queryByTestId("mock-handoff-button")).not.toBeInTheDocument();
    // Checklista Championa też jest tylko do odczytu dla recruitera.
    const checklist = await screen.findByTestId("mock-verification-checklist");
    expect(checklist).toHaveAttribute("data-can-edit", "false");
  });

  it("recruiter widzi zakładkę „Zespół i priorytet”, ale HiringManagerPicker jest read-only (`job.update` = TacPlus)", async () => {
    const user = userEvent.setup();
    renderDock(501, undefined, true, "champion");
    await screen.findByText("Programista Python (ZOB-2947)");

    await user.click(screen.getByRole("tab", { name: "Zespół i priorytet" }));

    expect(await screen.findByTestId("mock-hm-picker")).toHaveAttribute(
      "data-can-edit",
      "false",
    );
  });
});
