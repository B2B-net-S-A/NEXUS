import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const brandedGet = vi.fn();
const originalGet = vi.fn();
const removeFromRecruitment = vi.fn();
const suggestedRender = vi.fn();

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({
  candidatesApi: {
    setRecruitmentExpectedRate: vi.fn(),
    setRecruitmentClientRate: vi.fn(),
    removeFromRecruitment: (...a: unknown[]) => removeFromRecruitment(...a),
  },
  candidateStageCvApi: {
    branded: { get: (...a: unknown[]) => brandedGet(...a) },
    original: {
      get: (...a: unknown[]) => originalGet(...a),
      refresh: vi.fn(),
    },
  },
}));
vi.mock("next/dynamic", () => ({
  default: () =>
    function EditorStub() {
      return null;
    },
}));
// Zaślepki mówią, z jakimi propsami komponent dostał montaż — tu sprawdzamy
// układ zakładki, nie same widżety (mają własne testy).
vi.mock("@/components/feedback/CandidateInterviewFeedbackPanel", () => ({
  CandidateInterviewFeedbackPanel: (props: {
    jobId?: number;
    excludeJobIds?: ReadonlySet<number>;
  }) => (
    <div data-testid="feedback">
      {props.jobId != null
        ? `feedback:${props.jobId}`
        : `feedback-poza:${[...(props.excludeJobIds ?? [])].sort((a, b) => a - b).join(",")}`}
    </div>
  ),
}));
vi.mock("@/components/SuggestedJobsWidget", () => ({
  SuggestedJobsWidget: (props: { candidateId: number }) => {
    suggestedRender(props);
    return <div data-testid="suggested-widget">sugestie</div>;
  },
}));
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({
  DopasowanieTab: (props: { jobId?: number }) => (
    <div data-testid="match-score">{`ocena:${props.jobId}`}</div>
  ),
}));
vi.mock("@/components/v2/rate-change/RateChangeLatest", () => ({ RateChangeLatest: () => null }));
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({ CvGeneratorDialog: () => null }));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({ CVOriginalPreviewModal: () => null }));
vi.mock("@/components/v2/modals/CVShareLinkModal", () => ({ CVShareLinkModal: () => null }));
vi.mock("@/components/CandidatePipelinesWidget", () => ({
  candidatePipelinesQueryKey: (id: number) => ["candidate-pipelines", id],
}));

import { RecruitmentsTab, type ClientRateAccess } from "../RecruitmentsTab";
import { useAuthStore } from "@/store/auth";

const daysAgo = (days: number) =>
  new Date(Date.now() - days * 86_400_000 - 3_600_000).toISOString();

/**
 * „W toku” jako tabela (E3, 13.10.2026): wiersz = rekrutacja, etap, kto ma
 * ruch, dni bez ruchu, stawki; klik rozwija kartę procesu, ocenę dopasowania
 * i feedback tej rekrutacji.
 */
function history() {
  return [
    {
      job_id: 7,
      job_title: "Programista Python",
      client_name: "Bank A",
      job_status: "published",
      latest_stage: "cv_sent",
      latest_stage_id: 21,
      last_seen: daysAgo(2),
      next_action_owner: "client",
      expected_rate: { value: 150, unit: "hourly", currency: "PLN" },
      client_rate: { value: 190, unit: "hourly", currency: "PLN" },
      stages: [{ stage: "cv_sent", moved_at: daysAgo(2) }],
    },
    {
      job_id: 11,
      job_title: "Tester QA",
      client_name: "Firma D",
      job_status: "published",
      latest_stage: "verified",
      latest_stage_id: 31,
      last_seen: daysAgo(12),
      next_action_owner: "recruiter",
      expected_rate: null,
      client_rate: null,
      expected_rate_hint: {
        amount_hourly: 120,
        raw: "120 zł/h",
        at: daysAgo(20),
        source: "screening",
        author_name: "Anna Nowak",
      },
      stages: [{ stage: "verified", moved_at: daysAgo(12) }],
    },
    {
      job_id: 12,
      job_title: "DevOps",
      client_name: "Firma E",
      job_status: "published",
      latest_stage: "client_interview",
      latest_stage_id: 41,
      last_seen: daysAgo(5),
      next_action_owner: "delivery",
      stages: [{ stage: "client_interview", moved_at: daysAgo(5) }],
    },
    {
      job_id: 8,
      job_title: "Java Lead",
      client_name: "Telekom B",
      job_status: "closed",
      latest_stage: "rejected",
      latest_stage_id: 51,
      last_seen: daysAgo(100),
      stages: [{ stage: "rejected", moved_at: daysAgo(100) }],
    },
  ];
}

function renderTab({
  items = history(),
  focusedJobId = null,
  defaultJobId = null,
  view = "list",
  readOnly = false,
  clientRateAccess = { canView: true, canWrite: true },
}: {
  items?: unknown[];
  focusedJobId?: number | null;
  defaultJobId?: number | null;
  view?: "list" | "matching";
  readOnly?: boolean;
  clientRateAccess?: ClientRateAccess;
} = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RecruitmentsTab
        candidateId={121}
        candidateName="Grzegorz Żebrowski"
        history={items as never[]}
        isPending={false}
        error={null}
        refetch={vi.fn()}
        refreshing={false}
        focusedJobId={focusedJobId}
        defaultJobId={defaultJobId}
        view={view}
        readOnly={readOnly}
        clientRateAccess={clientRateAccess}
      />
    </QueryClientProvider>,
  );
}

const activeTable = () => screen.getByRole("table", { name: "Rekrutacje w toku" });
const rowButton = (title: string) =>
  within(activeTable()).getByRole("button", { name: new RegExp(`^${title}`) });

beforeEach(() => {
  brandedGet.mockReset();
  brandedGet.mockResolvedValue({ data: { status: "none", edit_revision: 0, version: 1 } });
  originalGet.mockReset();
  originalGet.mockResolvedValue({ data: { has_snapshot: true } });
  removeFromRecruitment.mockReset();
  removeFromRecruitment.mockResolvedValue({ data: {} });
  suggestedRender.mockReset();
  useAuthStore.setState({ user: { id: 5, role: "recruiter" } } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RecruitmentsTab — „W toku” jako tabela", () => {
  it("ma kolumny rekrutacji, etapu, ruchu, dni i stawek; najdłużej bez ruchu na górze", () => {
    renderTab();
    expect(screen.getByText("W toku · 3")).toBeInTheDocument();
    const headers = within(activeTable())
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual(["Rekrutacja", "Etap", "Ruch", "Dni", "Stawka", "Do klienta", "Akcje"]);

    const rows = within(activeTable()).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual([
      "Tester QAFirma D",
      "DevOpsFirma E",
      "Programista PythonBank A",
    ]);
    expect(rows[0]).toHaveTextContent("Rekruter");
    expect(rows[0]).toHaveTextContent("12");
    // Stawka z notatek, jeszcze niewpisana — z tyldą, nie jako stawka.
    expect(rows[0]).toHaveTextContent("~120 zł/h");
    expect(rows[1]).toHaveTextContent("Delivery");
    expect(rows[2]).toHaveTextContent("Klient");
    expect(rows[2]).toHaveTextContent("150 zł/h");
    expect(rows[2]).toHaveTextContent("190 zł/h");
  });

  it("bez prawa wglądu nie ma kolumny „Do klienta” ani kwoty do klienta", () => {
    renderTab({ clientRateAccess: { canView: false, canWrite: false } });
    const headers = within(activeTable())
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).not.toContain("Do klienta");
    expect(activeTable()).not.toHaveTextContent("190 zł/h");
    expect(activeTable()).toHaveTextContent("150 zł/h");
  });

  it("zwinięte wiersze nie pytają o CV; klik w wiersz rozwija kartę, ocenę i feedback tej rekrutacji", async () => {
    const user = userEvent.setup();
    renderTab();
    expect(originalGet).not.toHaveBeenCalled();
    expect(brandedGet).not.toHaveBeenCalled();
    expect(document.getElementById("candidate-recruitment-11")).toBeNull();

    await user.click(rowButton("Tester QA"));
    expect(rowButton("Tester QA")).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById("candidate-recruitment-11")).not.toBeNull();
    expect(await screen.findByRole("button", { name: "Pokaż CV oryginalne" })).toBeInTheDocument();
    await waitFor(() => expect(originalGet).toHaveBeenCalledWith(31));
    expect(originalGet).not.toHaveBeenCalledWith(21);
    expect(screen.getByText("feedback:11")).toBeInTheDocument();

    // Ocena dopasowania zwinięta — liczy się dopiero po „Pokaż”.
    expect(screen.queryByTestId("match-score")).toBeNull();
    const matchToggle = screen.getByRole("button", { name: /Ocena dopasowania/ });
    expect(matchToggle).toHaveAttribute("aria-expanded", "false");
    await user.click(matchToggle);
    expect(screen.getByTestId("match-score")).toHaveTextContent("ocena:11");

    // Ponowny klik zwija wiersz; klik w komórkę wiersza też rozwija.
    await user.click(rowButton("Tester QA"));
    expect(document.getElementById("candidate-recruitment-11")).toBeNull();
    const devopsRow = rowButton("DevOps").closest("tr")!;
    await user.click(within(devopsRow).getByText("Delivery"));
    expect(rowButton("DevOps")).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById("candidate-recruitment-12")).not.toBeNull();
  });

  it("wiersz z adresu jest rozwinięty od pierwszego renderu i dostaje fokus", async () => {
    renderTab({ focusedJobId: 12 });
    const card = document.getElementById("candidate-recruitment-12");
    expect(card).not.toBeNull();
    expect(rowButton("DevOps")).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(document.activeElement).toBe(card));
  });

  it("rekrutacja, z której otwarto profil, jest rozwinięta od wejścia", () => {
    renderTab({ defaultJobId: 7 });
    expect(rowButton("Programista Python")).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById("candidate-recruitment-7")).not.toBeNull();
  });

  it("jedyny proces w toku jest rozwinięty od razu", () => {
    renderTab({ items: [history()[0]] });
    expect(rowButton("Programista Python")).toHaveAttribute("aria-expanded", "true");
  });

  it("„⋯” wiersza ma tylko Tablicę i „Usuń z rekrutacji” z potwierdzeniem", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(screen.getByRole("button", { name: "Akcje rekrutacji: DevOps" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["Tablica", "Usuń z rekrutacji"]);
    expect(items[0]).toHaveAttribute("href", "/jobs/12?candidate=121");

    await user.click(items[1]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Usunąć kandydata z tej rekrutacji?");
    expect(removeFromRecruitment).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Usuń z rekrutacji" }));
    await waitFor(() => expect(removeFromRecruitment).toHaveBeenCalledWith(121, 12));
    // Okno i menu z portalu nie rozwijają wiersza.
    expect(rowButton("DevOps")).toHaveAttribute("aria-expanded", "false");
  });

  it("tylko do odczytu: w „⋯” zostaje Tablica", async () => {
    const user = userEvent.setup();
    renderTab({ readOnly: true });
    await user.click(screen.getByRole("button", { name: "Akcje rekrutacji: DevOps" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["Tablica"]);
  });

  it("feedback rekrutacji z listy siedzi w wierszach; na dole zostaje reszta", () => {
    renderTab();
    expect(screen.getByText("feedback-poza:7,8,11,12")).toBeInTheDocument();
  });
});

describe("RecruitmentsTab — pasujące rekrutacje i stary adres „Dopasowanie”", () => {
  it("pasujące rekrutacje pobierają się dopiero po „Pokaż”", async () => {
    const user = userEvent.setup();
    renderTab();
    const block = screen.getByRole("region", { name: "Pasujące rekrutacje" });
    expect(suggestedRender).not.toHaveBeenCalled();
    expect(within(block).queryByTestId("suggested-widget")).toBeNull();

    const show = within(block).getByRole("button", { name: "Pokaż" });
    expect(show).toHaveAttribute("aria-expanded", "false");
    await user.click(show);
    expect(within(block).getByTestId("suggested-widget")).toBeInTheDocument();
    expect(suggestedRender).toHaveBeenCalledWith(expect.objectContaining({ candidateId: 121 }));
  });

  it("sekcji „Dopasowanie do rekrutacji” już nie ma", () => {
    renderTab();
    expect(screen.queryByText("Dopasowanie do rekrutacji")).toBeNull();
    expect(screen.queryByTestId("match-score")).toBeNull();
  });

  it("?recruitments=matching rozwija pierwszy wiersz w toku z otwartą oceną i przewija do niej", async () => {
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    renderTab({ view: "matching" });
    expect(rowButton("Tester QA")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("match-score")).toHaveTextContent("ocena:11");
    expect(screen.getByRole("button", { name: /Ocena dopasowania/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    const target = document.getElementById("candidate-recruitment-11-match");
    await waitFor(() =>
      expect(scroll.mock.instances).toContain(target),
    );
  });

  it("?recruitments=matching z rekrutacji otwiera ocenę tej rekrutacji", () => {
    renderTab({ view: "matching", defaultJobId: 7 });
    expect(rowButton("Programista Python")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("match-score")).toHaveTextContent("ocena:7");
  });

  it("?recruitments=matching bez rekrutacji otwiera pasujące rekrutacje", async () => {
    renderTab({ view: "matching", items: [] });
    await waitFor(() => expect(screen.getByTestId("suggested-widget")).toBeInTheDocument());
  });
});
