/**
 * Krok 07 „Rozmowy i decyzja" — co ta zakładka MUSI mówić prawdę o.
 *
 * Najważniejsze asercje dotyczą weta hiring managera. Weto nie jest wierszem
 * w bazie: `services/hiring_manager_verdicts` wyprowadza je z odrzucenia
 * powodem oznaczonym `disqualifies_person`. Formularz feedbacku ma więc
 * POKAZYWAĆ, czy wybrany powód w ogóle może zablokować — a nie oferować
 * przełącznik, który niczego nie zapisze.
 */

import type { ComponentProps } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listFeedback = vi.fn();
const recordFeedback = vi.fn();
const getForStage = vi.fn();
const createShareToken = vi.fn();
const apiGet = vi.fn();
const apiPost = vi.fn();
const templatesGet = vi.fn();
const templatesList = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
  hiringManagerFeedbackApi: {
    list: (...a: unknown[]) => listFeedback(...a),
    record: (...a: unknown[]) => recordFeedback(...a),
  },
  screeningApi: {
    getForStage: (...a: unknown[]) => getForStage(...a),
    createShareToken: (...a: unknown[]) => createShareToken(...a),
  },
  pipelineTemplatesApi: {
    get: (...a: unknown[]) => templatesGet(...a),
    list: (...a: unknown[]) => templatesList(...a),
  },
  CONTRACT_FIELD_LABELS: {},
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

// Arkusz screeningu i modal odrzucenia mają WŁASNE zapytania — zakładka tylko
// je otwiera, więc do jej testów wystarczy stub.
vi.mock("@/components/v2/modals/ScreeningSheet", () => ({
  ScreeningSheet: () => <div data-testid="screening-sheet-stub" />,
}));
vi.mock("@/components/v2/modals/RejectionV2", () => ({
  RejectionV2: () => <div data-testid="rejection-stub" />,
}));

import { JobInterviewsTab } from "@/components/v2/jobs/JobInterviewsTab";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 900,
    candidate_id: 42,
    stage: "client_interview",
    name: "Grzegorz",
    lastname: "Żebrowski",
    days_in_stage: 2,
    verification_status: "active",
    ...overrides,
  };
}

function columns(overrides: Partial<KanbanColumn>[] = []): KanbanColumn[] {
  const base: KanbanColumn[] = [
    {
      stage: "client_interview",
      name: "Interview Klient",
      category: "external",
      count: 1,
      items: [item()],
      stage_def_id: 6,
    },
    {
      stage: "acceptance",
      name: "Akceptacja",
      category: "external",
      count: 0,
      items: [],
      stage_def_id: 7,
    },
    {
      stage: "cv_sent",
      name: "CV Wysłane",
      category: "internal",
      count: 0,
      items: [],
      stage_def_id: 5,
    },
    {
      stage: "rejected",
      name: "Odrzucony",
      category: "terminal",
      count: 0,
      items: [],
      stage_def_id: 11,
      terminal_type: "rejected",
    },
  ];
  return overrides.length > 0
    ? base.map((c, i) => ({ ...c, ...(overrides[i] ?? {}) }))
    : base;
}

type Props = ComponentProps<typeof JobInterviewsTab>;

function renderTab(overrides: Partial<Props> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const props: Props = {
    jobId: 10,
    jobTitle: "Programista Python",
    columns: columns(),
    readOnly: false,
    ...overrides,
  };
  render(
    <QueryClientProvider client={qc}>
      <JobInterviewsTab {...props} />
    </QueryClientProvider>,
  );
  return props;
}

beforeEach(() => {
  vi.clearAllMocks();
  listFeedback.mockResolvedValue([]);
  recordFeedback.mockResolvedValue({
    id: 1,
    job_id: 10,
    candidate_id: 42,
    decision: "reject",
    rejection_reason_id: 3,
    rejection_reason_name: "Nie spełnia wymagań technicznych",
    note: null,
    technical_fit: null,
    soft_fit: null,
    overall_fit: null,
    hiring_manager_contact_id: 5,
    hiring_manager_name: "Anna Nowak",
    blocks_future_proposals: true,
    veto_recorded: false,
    veto_blockers: ["Kandydat nie został jeszcze odrzucony na tej rekrutacji."],
  });
  getForStage.mockResolvedValue({ data: { screening_answers: null } });
  createShareToken.mockResolvedValue({
    data: { token: "t", expires_at: "", share_url_suffix: "/share/x" },
  });
  apiGet.mockResolvedValue({ data: { pipeline_template_id: 1 } });
  apiPost.mockResolvedValue({ data: {} });
  templatesGet.mockResolvedValue({
    data: {
      stages: [],
      rejection_reasons: [
        {
          id: 3,
          template_id: 1,
          stage_def_id: null,
          name: "Nie spełnia wymagań technicznych",
          order: 0,
          category: "rejected",
          active: true,
          disqualifies_person: true,
          created_at: "",
          updated_at: "",
        },
        {
          id: 4,
          template_id: 1,
          stage_def_id: null,
          name: "Za wysokie oczekiwania finansowe",
          order: 1,
          category: "rejected",
          active: true,
          disqualifies_person: false,
          created_at: "",
          updated_at: "",
        },
      ],
    },
  });
  templatesList.mockResolvedValue({ data: [] });
});

describe("JobInterviewsTab", () => {
  it("pokazuje kandydatów z etapów zewnętrznych i wybiera pierwszego", async () => {
    renderTab();
    // Nazwisko pada w trzech miejscach naraz: lewa lista, karta rozmowy i dok.
    expect(
      (await screen.findAllByText("Grzegorz Żebrowski")).length,
    ).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Rozmowa u klienta")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Feedback klienta po rozmowie" }),
    ).toBeTruthy();
  });

  /** Słownik powodów dociąga się osobnym zapytaniem — bez tego `select` ma
   *  wyłącznie opcję „Wczytywanie słownika…". */
  async function reasonSelect() {
    const select = await screen.findByLabelText("Powód (gdy odrzuca)");
    await screen.findByRole("option", {
      name: "Nie spełnia wymagań technicznych",
    });
    return select;
  }

  it("powód-werdykt o osobie mówi, że weto POWSTANIE — nie że już jest", async () => {
    renderTab();
    await userEvent.selectOptions(await reasonSelect(), "3");

    expect(
      screen.getByText(/weto powstanie, gdy kandydat zostanie odrzucony/i),
    ).toBeTruthy();
  });

  it("powód sytuacyjny mówi wprost, że NIE zablokuje", async () => {
    renderTab();
    await userEvent.selectOptions(await reasonSelect(), "4");

    expect(
      screen.getByText(/opisuje sytuację, nie osobę/i),
    ).toBeTruthy();
  });

  it("zapisuje werdykt przez `POST /jobs/{id}/hiring-manager-feedback`", async () => {
    renderTab();
    await userEvent.click(await screen.findByRole("button", { name: "Odrzuca" }));
    await userEvent.selectOptions(await reasonSelect(), "3");
    await userEvent.type(
      screen.getByLabelText("Notatka z feedbacku"),
      "Nie przekonał przy Kafce.",
    );
    await userEvent.click(screen.getByRole("button", { name: /Zapisz feedback/ }));

    await waitFor(() => expect(recordFeedback).toHaveBeenCalledTimes(1));
    expect(recordFeedback).toHaveBeenCalledWith(10, {
      candidate_id: 42,
      decision: "reject",
      rejection_reason_id: 3,
      note: "Nie przekonał przy Kafce.",
    });
  });

  it("readOnly wyłącza formularz i chowa zapis, ale zostawia odczyt", async () => {
    renderTab({ readOnly: true });
    expect(await screen.findByLabelText("Powód (gdy odrzuca)")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Zapisz feedback/ })).toBeNull();
    expect(screen.getByText(/Tylko do odczytu/)).toBeTruthy();
  });

  it("„CV Wysłane” jest wyszarzone z powodem — jego modal mieszka na tablicy", async () => {
    renderTab();
    const pill = await screen.findByRole("button", { name: "CV Wysłane" });
    expect(pill).toBeDisabled();
    expect(pill.getAttribute("title")).toMatch(/stawkę do klienta/);
  });

  it("weto HM wyszarza ruchy nie-terminalne, ale NIE odrzucenie", async () => {
    const withVeto = columns();
    withVeto[0] = {
      ...withVeto[0],
      items: [
        item({
          hm_veto: {
            hiring_manager_contact_id: 5,
            hiring_manager_name: "Anna Nowak",
            source_job_id: 3,
            source_job_title: "Inny projekt",
            rejected_at: "2026-05-04T10:00:00Z",
            rejection_reason_name: "Nie pasuje kulturowo",
          },
        }),
      ],
    };
    renderTab({ columns: withVeto });

    const acceptance = await screen.findByRole("button", { name: "Akceptacja" });
    expect(acceptance).toBeDisabled();
    expect(acceptance.getAttribute("title")).toMatch(/Hiring manager/);

    // Terminalne ZAWSZE przechodzą — inaczej kandydata z wetem nie dałoby się
    // domknąć z tej powierzchni.
    const rejected = screen.getByRole("button", { name: "Odrzucony" });
    expect(rejected).not.toBeDisabled();
  });

  it("pusty pipeline mówi „nikt nie jest u klienta”, a nie renderuje pustki", async () => {
    const empty = columns().map((c) => ({ ...c, items: [], count: 0 }));
    renderTab({ columns: empty, columnsSuccess: true });
    expect(
      await screen.findByText("Nikt nie jest jeszcze u klienta"),
    ).toBeTruthy();
  });

  it("awaria kanbana NIE udaje pustego kroku", async () => {
    // Pipeline przychodzi propsem, więc bez jawnego błędu 500 wyglądałoby
    // stąd identycznie jak „nikt nie jest u klienta".
    renderTab({
      columns: [],
      columnsSuccess: false,
      columnsError: { response: { status: 500 } },
    });
    expect(screen.getByText("Nie udało się pobrać danych")).toBeTruthy();
    expect(screen.queryByText("Nikt nie jest jeszcze u klienta")).toBeNull();
  });

  it("403 na kanbanie to brak uprawnień, nie zero kandydatów", async () => {
    renderTab({
      columns: [],
      columnsSuccess: false,
      columnsError: { response: { status: 403 } },
    });
    expect(screen.getByText("Brak uprawnień")).toBeTruthy();
    expect(screen.queryByText("Nikt nie jest jeszcze u klienta")).toBeNull();
  });

  it("awaria pobierania werdyktów renderuje się jako awaria, nie jako brak feedbacku", async () => {
    listFeedback.mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500 } }),
    );
    renderTab();
    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeTruthy();
  });
});
