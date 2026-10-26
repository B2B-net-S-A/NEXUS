/**
 * KanbanBoardV2 — testy powierzchni renderu i akcji tablicy.
 *
 * Drag-and-drop nie jest odpalalny w jsdom (repo-precedens: weryfikacja dnd
 * unit testami + realnym Chrome), więc ruchy wyzwalamy pigułkami doku:
 * - od 17.09.2026 żadna bramka nie blokuje przepływu — karta niesie odznaki
 *   („ponad budżet", „Uzupełnij screening"), a weto HM / czarna lista / NDA /
 *   konkurent to ostrzeżenie serwera z „Przenieś mimo to",
 * - ruch zbiorczy POMIJA z wyjaśnieniem karty z ostrzeżeniem (weto HM),
 * - okno stawki do klienta tylko dla `can_write_client_rate`.
 */

import * as React from "react";
import { act, cleanup as rtlCleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const kanban = vi.fn();
const post = vi.fn();
const get = vi.fn();
const move = vi.fn();
const toastError = vi.fn();
const toastSuccess = vi.fn();
const toastInfo = vi.fn();
const toastAction = vi.fn();
const hmRecord = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
  candidatesApi: {
    removeFromRecruitment: vi.fn(),
    setRecruitmentClientRate: vi.fn(),
  },
  hiringManagerFeedbackApi: {
    record: (...a: unknown[]) => hmRecord(...a),
    list: () => Promise.resolve({ can_record: true, items: [] }),
  },
  pipelineApi: {
    kanban: (...a: unknown[]) => kanban(...a),
    move: (...a: unknown[]) => move(...a),
  },
  pipelineTemplatesApi: {
    get: vi.fn(() =>
      Promise.resolve({ data: { stages: [], rejection_reasons: [] } }),
    ),
    list: vi.fn(() => Promise.resolve({ data: [] })),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showActionToast: toastAction,
    showSuccess: toastSuccess,
    showError: toastError,
    showInfo: toastInfo,
  }),
}));

vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));
// Okno QC CV (F2) ma własne zapytania — tu sprawdzamy tylko, KTÓRY etap
// otwiera i dokąd prowadzi jego „Przesuń dalej”.
const qcResultCandidate = { id: 0 };
vi.mock("@/components/v2/recruitment/CvQcDialog", () => ({
  CvQcDialog: ({
    stageId,
    open,
    onMoveNext,
  }: {
    stageId: number | null;
    open: boolean;
    onMoveNext?: (result: { candidate_id: number }) => void;
  }) =>
    open ? (
      <div data-testid="cv-qc-dialog" data-stage-id={String(stageId)}>
        {onMoveNext ? (
          <button type="button" onClick={() => onMoveNext({ candidate_id: qcResultCandidate.id })}>
            QC: przesuń dalej
          </button>
        ) : null}
      </div>
    ) : null,
}));

// Przeciągnięcie: prawdziwa biblioteka, ale test może sam wywołać upuszczenie
// (jsdom nie umie przeciągać).
const dnd = vi.hoisted(() => ({
  onDragEnd: null as null | ((result: Record<string, unknown>) => void),
}));
vi.mock("@hello-pangea/dnd", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@hello-pangea/dnd")>();
  const Actual = actual.DragDropContext;
  return {
    ...actual,
    DragDropContext: (props: React.ComponentProps<typeof Actual>) => {
      dnd.onDragEnd = props.onDragEnd as never;
      return <Actual {...props} />;
    },
  };
});

// Przegląd przed wysłaniem do klienta ma własne testy (`DlReviewPanel.test`) —
// tu liczy się, KOMU tablica go otwiera, dla którego wiersza etapu i że
// otwiera się W panelu osoby (jeden panel osoby, 04.10.2026).
vi.mock("@/components/v2/recruitment/DlReviewPanel", () => ({
  DlReviewBody: ({
    task,
    canSendToClient,
    onClose,
    layout,
    onDecided,
    sequence,
  }: {
    task: {
      stage_id: number;
      verified_by_name?: string | null;
      cv_stage_id?: number | null;
      target_stage_def_id?: number | null;
      cpro?: boolean;
    };
    canSendToClient?: boolean;
    onClose: () => void;
    layout: string;
    onDecided?: (action: string, task: unknown) => void;
    sequence?: { position: number; total: number; onSkip: () => void; onFinish: () => void };
  }) => (
    <div
      data-testid="dl-review-panel"
      data-layout={layout}
      data-stage-id={String(task.stage_id)}
      data-verified-by={task.verified_by_name ?? ""}
      data-cv-stage-id={String(task.cv_stage_id ?? "")}
      data-can-send={String(canSendToClient)}
      data-target-stage-def-id={String(task.target_stage_def_id ?? "")}
      data-cpro={String(task.cpro === true)}
    >
      <button type="button" onClick={onClose}>
        zamknij przegląd
      </button>
      {/* Jak prawdziwy przegląd: po udanej decyzji `onDecided` ZAMIAST `onClose`. */}
      <button type="button" onClick={() => (onDecided ? onDecided("send", task) : onClose())}>
        decyzja: wyślij
      </button>
      {sequence ? (
        <p data-testid="dl-review-sequence">
          <span>
            {sequence.position} z {sequence.total}
          </span>
          <button type="button" onClick={sequence.onSkip}>
            pomiń
          </button>
          <button type="button" onClick={sequence.onFinish}>
            zakończ kolejkę
          </button>
        </p>
      ) : null}
    </div>
  ),
}));

// Pełne narzędzia osoby mają własne testy (`PersonWorkbenchTabs.test`) — tu
// liczy się, że „Rozwiń” pokazuje je w TYM SAMYM panelu, na właściwej zakładce.
vi.mock("@/components/v2/person/PersonWorkbenchTabs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/v2/person/PersonWorkbenchTabs")>();
  return {
    ...actual,
    PersonWorkbenchTabs: ({
      section,
      row,
      onSectionChange,
      workbenchContext,
    }: {
      section: string;
      row: { candidateId: number };
      onSectionChange: (section: string) => void;
      workbenchContext?: {
        rejectFollowUp?: (
          candidateId: number,
        ) => { onMoved: (info: { reasonLabel: string | null }) => void } | undefined;
        onForwarded?: (candidateId: number) => void;
        forwardedCandidateId?: number | null;
        nextInColumn?: (
          candidateId: number,
          column: string,
        ) => { candidateId: number; name: string; detail?: string | null } | null;
        openPerson?: (candidateId: number) => void;
        noteFill?: unknown;
      };
    }) => (
      <div
        data-testid="person-workbench-stub"
        data-section={section}
        data-candidate={row.candidateId}
        data-forwarded={String(workbenchContext?.forwardedCandidateId ?? "")}
        data-note-fill={workbenchContext?.noteFill ? "yes" : "no"}
      >
        <input aria-label="pole warsztatu" defaultValue="" />
        <button type="button" onClick={() => onSectionChange("contract")}>
          zakładka umowa
        </button>
        {/* Jak „Odrzuć” w formularzu screeningu: migawka przy kliknięciu, potem udany ruch. */}
        <button
          type="button"
          onClick={() =>
            workbenchContext?.rejectFollowUp?.(row.candidateId)?.onMoved({ reasonLabel: "Brak Azure" })
          }
        >
          formularz: odrzucono
        </button>
        {/* Jak „Zapisz i przekaż dalej”: udany ruch, potem przejście panelu. */}
        <button type="button" onClick={() => workbenchContext?.onForwarded?.(row.candidateId)}>
          formularz: przekazano
        </button>
        {(() => {
          const next = workbenchContext?.nextInColumn?.(row.candidateId, "new") ?? null;
          return next ? (
            <button type="button" onClick={() => workbenchContext?.openPerson?.(next.candidateId)}>
              {`następna w Nowych: ${next.name}${next.detail ? ` · ${next.detail}` : ""}`}
            </button>
          ) : (
            <span>brak następnej w Nowych</span>
          );
        })()}
      </div>
    ),
  };
});

import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthStore } from "@/store/auth";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";
import { useUiStore } from "@/store/ui";
import { KANBAN_VIEW_MODE_STORAGE_KEY } from "@/lib/kanban-view-preferences";
import { PIPELINE_VERSION_CONFLICT_CODE } from "@/lib/pipeline-version-conflict";
import { ADDED_BY_ALL, type AddedByFilter } from "@/lib/board-added-by";

beforeAll(() => {
  // Radix Select uses pointer-capture APIs that jsdom does not implement.
  if (!HTMLElement.prototype.hasPointerCapture) {
    HTMLElement.prototype.hasPointerCapture = () => false;
    HTMLElement.prototype.setPointerCapture = () => {};
    HTMLElement.prototype.releasePointerCapture = () => {};
  }
});

// Domyślne odpowiedzi — `mockResolvedValue` w teście nie może przeciekać do
// kolejnych opisów (vi.clearAllMocks nie zdejmuje implementacji).
beforeEach(() => {
  get.mockImplementation(() =>
    Promise.resolve({ data: { effective_budget_hourly: null, pipeline_template_id: null } }),
  );
  move.mockImplementation(() => Promise.resolve({ data: {} }));
});

/** Kolumna „Zweryfikowany" z kartami ze stawką godzinową w PLN. */
function rateColumns(
  cards: Array<{
    id: number;
    candidate_id: number;
    name: string;
    lastname: string;
    rate: number;
    extra?: Record<string, unknown>;
  }>,
) {
  return [
    {
      stage: "verified",
      name: "Zweryfikowany",
      category: "internal",
      stage_def_id: null,
      count: cards.length,
      items: cards.map((c) => ({
        id: c.id,
        candidate_id: c.candidate_id,
        name: c.name,
        lastname: c.lastname,
        stage: "verified",
        days_in_stage: 1,
        verification_status: "active",
        expected_rate_value: c.rate,
        expected_rate_unit: "hourly",
        expected_rate_currency: "PLN",
        ...c.extra,
      })),
    },
  ] as never;
}

/** Karta sprzed 17.09.2026 z `verification_status: "pending"` — ma wyglądać jak zwykła. */
function pendingColumns() {
  return [
    {
      stage: "verified",
      name: "Zweryfikowany",
      category: "internal",
      stage_def_id: null,
      count: 1,
      items: [
        {
          id: 777,
          candidate_id: 5,
          name: "Anna",
          lastname: "Kowalska",
          stage: "verified",
          days_in_stage: 1,
          verification_status: "pending",
          expected_rate_value: 150,
          expected_rate_unit: "hourly",
          expected_rate_currency: "PLN",
          budget_max_at_move: 20000,
        },
      ],
    },
  ] as never;
}

function focusColumns() {
  const names = [
    "Nowy",
    "Screening",
    "Zweryfikowany",
    "Przedstawiony",
    "Rozmowa HR",
    "Rozmowa techniczna",
    "Rozmowa z klientem",
    "Feedback",
    "Oferta",
    "Negocjacje",
    "Akceptacja",
    "Onboarding",
    "Wycofany",
    "Odrzucony",
    "Zatrudniony",
  ];

  return names.map((name, index) => ({
    // Custom stages deliberately share the legacy enum. Stable navigation and
    // DnD identity must come from stage_def_id, not from this fallback value.
    stage: "new",
    name,
    category: index >= 12 ? "terminal" : "internal",
    stage_def_id: 201 + index,
    count: index === 1 ? 4 : 0,
    items: [],
    terminal_type:
      index === 12
        ? "withdrawn"
        : index === 13
          ? "rejected"
          : index === 14
            ? "hired"
            : null,
  })) as never;
}

function overviewColumns() {
  const columns = focusColumns() as unknown as Array<Record<string, unknown>>;
  columns[0] = {
    ...columns[0],
    count: 1,
    items: [
      {
        id: 901,
        candidate_id: 90,
        name: "Aleksandra",
        lastname: "Nowakowska",
        stage: "new",
        days_in_stage: 5,
        rating: 4.5,
        verification_status: null,
        added_to_job_by_name: "Ewa Nowak",
        added_to_job_at: "2026-08-20T08:15:00Z",
      },
    ],
  };
  return columns as never;
}

// 17 kolumn: próg pełnego układu to 16 (15 „Default B2B" + „Ogłoszenia").
function overflowColumns() {
  const columns = focusColumns() as unknown as Array<Record<string, unknown>>;
  return [
    ...columns,
    {
      stage: "new",
      name: "Do decyzji",
      category: "internal",
      stage_def_id: 216,
      count: 0,
      items: [],
      terminal_type: null,
    },
    {
      stage: "new",
      name: "Archiwum",
      category: "terminal",
      stage_def_id: 217,
      count: 0,
      items: [],
      terminal_type: "withdrawn",
    },
  ] as never;
}

function renderBoard(
  columns = pendingColumns(),
  scoreMap?: Map<number, number>,
  readOnly = false,
  cproEnabled = false,
  viewerOwnsDlReview = false,
  criticalGapMap?: Map<number, string[]>,
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <KanbanBoardV2
          columns={columns}
          jobId={10}
          scoreMap={scoreMap}
          criticalGapMap={criticalGapMap}
          readOnly={readOnly}
          cproEnabled={cproEnabled}
          viewerOwnsDlReview={viewerOwnsDlReview}
        />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

// Szkic notatki z doku żyje w `sessionStorage` (12.10.2026) — nie może
// przechodzić między testami.
beforeEach(() => {
  sessionStorage.clear();
});

describe("KanbanBoardV2 — karta: odznaki zamiast bramek (17.09.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("stawka ponad budżet godzinowy rekrutacji daje odznakę „ponad budżet”, w budżecie — nie", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    get.mockResolvedValue({
      data: { effective_budget_hourly: 100, pipeline_template_id: null },
    });

    renderBoard(
      rateColumns([
        { id: 781, candidate_id: 11, name: "Adam", lastname: "Drogi", rate: 150 },
        { id: 782, candidate_id: 12, name: "Beata", lastname: "Tania", rate: 80 },
      ]),
    );

    const expensive = (
      await screen.findByRole("link", { name: "Adam Drogi" })
    ).closest("[data-kanban-card]") as HTMLElement;
    await waitFor(() =>
      expect(within(expensive).getByText("ponad budżet")).toBeInTheDocument(),
    );
    const cheap = screen
      .getByRole("link", { name: "Beata Tania" })
      .closest("[data-kanban-card]") as HTMLElement;
    expect(within(cheap).queryByText("ponad budżet")).toBeNull();
  });

  it("brak krytycznej to plakietka obok pierścienia, nie zniknięcie wyniku (16.10.2026)", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    get.mockResolvedValue({ data: { pipeline_template_id: null } });

    renderBoard(
      rateColumns([
        { id: 781, candidate_id: 11, name: "Adam", lastname: "Bezpłatności", rate: 80 },
        { id: 782, candidate_id: 12, name: "Beata", lastname: "Pełna", rate: 80 },
      ]),
      new Map([
        [11, 64.2],
        [12, 76.5],
      ]),
      false,
      false,
      false,
      new Map([[11, ["płatności"]]]),
    );

    const gap = (
      await screen.findByRole("link", { name: "Adam Bezpłatności" })
    ).closest("[data-kanban-card]") as HTMLElement;
    expect(within(gap).getByLabelText("Dopasowanie AI: 64 na 100")).toBeInTheDocument();
    const chip = within(gap).getByTestId("card-critical-gap");
    expect(chip).toHaveTextContent("brak: płatności");
    expect(chip.getAttribute("title")).toContain("bez śladu w profilu, CV i notatkach: płatności");

    const full = screen
      .getByRole("link", { name: "Beata Pełna" })
      .closest("[data-kanban-card]") as HTMLElement;
    expect(within(full).getByLabelText("Dopasowanie AI: 77 na 100")).toBeInTheDocument();
    expect(within(full).queryByTestId("card-critical-gap")).toBeNull();
  });

  it("karta mówi, że osoba u nas pracuje, i rysuje ostrzeżenia pary z serwera", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    get.mockResolvedValue({
      data: { effective_budget_hourly: 200, pipeline_template_id: null },
    });

    renderBoard(
      rateColumns([
        {
          id: 791,
          candidate_id: 21,
          name: "Anna",
          lastname: "Przykładowa",
          rate: 150,
          extra: {
            warnings: ["client_nda"],
            employment_marker: {
              phase: "working",
              source: "contract",
              elsewhere: true,
              clients: [
                {
                  client_id: 4,
                  client_name: "Bank Przykładowy",
                  contract_id: 40,
                  phase: "working",
                  order_end_date: "2026-12-31",
                },
              ],
            },
          },
        },
        { id: 792, candidate_id: 22, name: "Jan", lastname: "Testowy", rate: 150 },
      ]),
    );

    const employed = (
      await screen.findByRole("link", { name: "Anna Przykładowa" })
    ).closest("[data-kanban-card]") as HTMLElement;
    // Data bez roku — karta ma ~176 px; pełna treść jest w dymku i w opisie.
    expect(within(employed).getByTestId("card-employment")).toHaveTextContent(
      "Pracuje u nas · Bank Przykładowy · do 31.12",
    );
    expect(within(employed).getByTestId("card-warning-client_nda")).toHaveTextContent("NDA z klientem");
    const description = document.getElementById(
      screen.getByRole("link", { name: "Anna Przykładowa" }).getAttribute("aria-describedby") ?? "",
    );
    expect(description).toHaveTextContent(
      "Ostrzeżenie: NDA z klientem. Pracuje u nas · Bank Przykładowy · do 31.12.2026.",
    );

    const other = screen
      .getByRole("link", { name: "Jan Testowy" })
      .closest("[data-kanban-card]") as HTMLElement;
    expect(within(other).queryByTestId("card-employment")).toBeNull();
    expect(within(other).queryByTestId(/^card-warning-/)).toBeNull();
  });

  it("karta w „Odrzuconych” pokazuje powód; komentarz i kto — w dymku i opisie (19.10.2026)", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    get.mockResolvedValue({ data: { pipeline_template_id: null } });

    renderBoard([
      {
        stage: "new",
        name: "Nowi",
        category: "internal",
        stage_def_id: null,
        count: 1,
        items: [
          { id: 901, candidate_id: 31, name: "Jan", lastname: "Otwarty", stage: "new", days_in_stage: 1, notes: "Notatka ruchu" },
        ],
      },
      {
        stage: "rejected",
        name: "Odrzucony",
        category: "terminal",
        stage_def_id: null,
        count: 2,
        terminal_type: "rejected",
        items: [
          {
            id: 902,
            candidate_id: 32,
            name: "Krzysztof",
            lastname: "Odrzucony",
            stage: "rejected",
            days_in_stage: 2,
            moved_at: "2026-10-16T10:00:00Z",
            rejection_reason_name: "Za wysokie oczekiwania finansowe",
            closed_by_name: "Julia Swidkiewicz",
            notes: "Oczekuje 190 zł/h.",
          },
          { id: 903, candidate_id: 33, name: "Maciej", lastname: "Traffit", stage: "rejected", days_in_stage: 30 },
        ],
      },
    ] as never);

    // Zamknięci stoją zwinięci obok Tablicy — rozwijamy kolumnę odrzuconych.
    const closedColumn = await screen.findByRole("region", { name: "Zamknięci" });
    await userEvent.click(within(closedColumn).getAllByRole("button", { name: /Odrzucon/ })[0]);
    const rejected = (
      await screen.findByRole("link", { name: "Krzysztof Odrzucony" })
    ).closest("[data-kanban-card]") as HTMLElement;
    const line = within(rejected).getByTestId("card-closed-reason");
    expect(line).toHaveTextContent("Za wysokie oczekiwania finansowe");
    expect(line).toHaveAttribute("data-tone", "danger");
    expect(line).toHaveAttribute(
      "title",
      "Odrzucony: Za wysokie oczekiwania finansowe — Oczekuje 190 zł/h.\nJulia Swidkiewicz · 16.10.2026",
    );
    const description = document.getElementById(
      screen.getByRole("link", { name: "Krzysztof Odrzucony" }).getAttribute("aria-describedby") ?? "",
    );
    expect(description).toHaveTextContent("Odrzucony: Za wysokie oczekiwania finansowe — Oczekuje 190 zł/h.");

    const unknown = screen
      .getByRole("link", { name: "Maciej Traffit" })
      .closest("[data-kanban-card]") as HTMLElement;
    expect(within(unknown).getByTestId("card-closed-reason")).toHaveTextContent("Powód nie zapisany");
    expect(within(unknown).getByTestId("card-closed-reason")).toHaveAttribute("data-tone", "neutral");

    const open = screen
      .getByRole("link", { name: "Jan Otwarty" })
      .closest("[data-kanban-card]") as HTMLElement;
    expect(within(open).queryByTestId("card-closed-reason")).toBeNull();
  });

  it("stara karta „pending” renderuje się jak zwykła — bez „Pending” i bez akceptacji", async () => {
    useAuthStore.setState({
      user: { role: "admin", roles: ["admin"] } as never,
    });

    renderBoard();

    expect(await screen.findByRole("link", { name: "Anna Kowalska" })).toBeTruthy();
    expect(screen.queryByText(/Pending/)).toBeNull();
    expect(screen.queryByText(/Oczekuje/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Akceptuj/ })).toBeNull();
    expect(screen.queryByTitle("Akceptuj weryfikację")).toBeNull();
    expect(screen.queryByTitle("Odrzuć weryfikację")).toBeNull();
  });

  it("pokazuje wynik dopasowania na karcie", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });

    renderBoard(pendingColumns(), new Map([[5, 77]]));

    expect(
      await screen.findByLabelText("Dopasowanie AI: 77 na 100"),
    ).toBeTruthy();
  });

  it("karta na „Zweryfikowany” bez zapisanego screeningu pokazuje „Uzupełnij screening”", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });

    renderBoard(
      rateColumns([
        {
          id: 783,
          candidate_id: 13,
          name: "Celina",
          lastname: "Arkusz",
          rate: 90,
          extra: { screening_done: false },
        },
        {
          id: 784,
          candidate_id: 14,
          name: "Dawid",
          lastname: "Gotowy",
          rate: 90,
          extra: { screening_done: true },
        },
      ]),
    );

    expect(
      await screen.findByRole("button", {
        name: "Uzupełnij screening dla Celina Arkusz",
      }),
    ).toHaveTextContent("Uzupełnij screening");
    const done = screen.getByRole("button", {
      name: "Screening Championa dla Dawid Gotowy",
    });
    expect(done).toHaveTextContent("Screening");
    expect(done).not.toHaveTextContent("Uzupełnij");
  });

  it("wiersz właściciela mówi o braku danych, zamiast udawać nazwisko", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });

    renderBoard();
    const candidate = await screen.findByRole("link", { name: "Anna Kowalska" });
    // Fala 3: wiersz właściciela to awatar + imię, a brak danych mówi o sobie
    // wprost zamiast udawać nazwisko.
    expect(screen.getByText("Brak danych")).toBeTruthy();
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(document.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Brak danych o osobie dodającej.",
    );
  });

  it("w trybie tylko do odczytu ukrywa mutacje, ale zachowuje eksport CV", async () => {
    useAuthStore.setState({
      user: { role: "admin", roles: ["admin"] } as never,
    });

    renderBoard(pendingColumns(), undefined, true);

    expect(await screen.findByRole("link", { name: "Anna Kowalska" })).toBeTruthy();
    const checkbox = screen.getByRole("checkbox", { name: "Zaznacz Anna Kowalska" });
    expect(checkbox).toBeInTheDocument();
    await userEvent.click(checkbox);
    expect(screen.getByRole("button", { name: /CV \(ZIP\)/ })).toBeInTheDocument();
    // Pasek akcji zbiorczych: bez prawa zapisu zostaje sam eksport — ani
    // przenoszenia, ani skrótu „Odrzuć".
    expect(screen.queryByText(/Przenieś na etap/)).toBeNull();
    expect(screen.queryByRole("button", { name: /^Odrzuć$/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Usuń Anna Kowalska z rekrutacji" }),
    ).toBeNull();
  });
});

/**
 * Ruch z doku = `moveBlockedReason` (od 17.09.2026 blokuje wyłącznie brak
 * prawa zapisu) + ostrzeżenia serwera. Weto HM, czarna lista, NDA i konkurent
 * kończą się 409 `ELIGIBILITY_WARNING`, a tablica pyta „Przenieś mimo to"
 * i powtarza TEN SAM ruch z `acknowledge_eligibility: true`.
 */
describe("KanbanBoardV2 — ruch z doku i ostrzeżenia serwera", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
    move.mockResolvedValue({ data: {} });
    useAuthStore.setState({
      user: { role: "admin", roles: ["admin"] } as never,
    });
  });

  function gateColumns(extra: Record<string, unknown>) {
    return [
      {
        stage: "screening",
        name: "Screening",
        category: "internal",
        stage_def_id: 301,
        count: 1,
        items: [
          {
            id: 801,
            candidate_id: 61,
            name: "Jan",
            lastname: "Bramka",
            stage: "screening",
            days_in_stage: 2,
            verification_status: "active",
            ...extra,
          },
        ],
      },
      {
        stage: "verified",
        name: "Zweryfikowany",
        category: "internal",
        stage_def_id: 302,
        count: 0,
        items: [],
      },
      {
        stage: "cv_sent",
        name: "CV Wysłane",
        category: "internal",
        stage_def_id: 303,
        count: 0,
        items: [],
      },
      {
        stage: "rejected",
        name: "Odrzucony",
        category: "terminal",
        stage_def_id: 304,
        count: 0,
        items: [],
        terminal_type: "rejected",
      },
    ] as never;
  }

  async function openDock() {
    const card = await waitFor(() => {
      const el = document.querySelector("[data-kanban-card]");
      expect(el).toBeTruthy();
      return el as HTMLElement;
    });
    fireEvent.click(card);
    return screen.findByRole("complementary", { name: "Panel osoby" });
  }

  async function openDockStageMenu() {
    await openDock();
    await userEvent.click(screen.getByRole("button", { name: "Inny etap…" }));
    return screen.findByRole("menu");
  }

  const VETO = {
    hm_veto: {
      hiring_manager_contact_id: 5,
      source_job_id: 2,
      rejected_at: "2026-01-01",
      rejection_reason_name: "Brak bankowości",
    },
  };

  function moveCalls() {
    return post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");
  }

  function eligibilityWarning409() {
    return {
      response: {
        status: 409,
        data: {
          detail: {
            code: "ELIGIBILITY_WARNING",
            reason_code: "hm_veto",
            reason: "Hiring manager odrzucił już tego kandydata — Brak bankowości.",
            message: "Hiring manager odrzucił już tego kandydata — Brak bankowości.",
            can_acknowledge: true,
          },
        },
      },
    };
  }

  it("weto HM NIE wyszarza w doku „CV wysłane” ani żadnego innego etapu", async () => {
    renderBoard(gateColumns(VETO));
    const menu = await openDockStageMenu();

    for (const name of ["Zweryfikowany", "CV wysłane", "Odrzucony"]) {
      const option = within(menu).getByRole("menuitem", { name });
      expect(option).not.toHaveAttribute("aria-disabled", "true");
      expect(option.getAttribute("title")).toBeNull();
    }
    // Menu trzeba zamknąć, żeby przycisk doku pod nim był osiągalny.
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: /Odrzuć z powodem/ })).not.toBeDisabled();
  });

  /** Fragment „Default B2B": po „Wysłać do Cpro" stoją „CV wysłane",
   *  „Preparation Meeting" i „Interview Klient". */
  function vetoRouteColumns(extra: Record<string, unknown>) {
    return [
      {
        stage: "new",
        name: "Wysłać do Cpro",
        category: "internal",
        stage_def_id: 401,
        count: 1,
        items: [
          {
            id: 811,
            candidate_id: 71,
            name: "Ewa",
            lastname: "Objazd",
            stage: "new",
            days_in_stage: 1,
            verification_status: "active",
            process_state_version: 3,
            ...extra,
          },
        ],
      },
      { stage: "cv_sent", name: "CV Wysłane", category: "internal", stage_def_id: 402, count: 0, items: [] },
      { stage: "new", name: "Preparation Meeting", category: "external", stage_def_id: 403, count: 0, items: [] },
      { stage: "client_interview", name: "Interview Klient", category: "external", stage_def_id: 404, count: 0, items: [] },
      {
        stage: "rejected",
        name: "Odrzucony",
        category: "terminal",
        stage_def_id: 405,
        count: 0,
        items: [],
        terminal_type: "rejected",
      },
    ] as never;
  }

  it("weto HM na drodze naprzód: główna akcja doku proponuje następny etap, aktywny", async () => {
    renderBoard(vetoRouteColumns(VETO));
    await openDock();

    const forward = screen.getByRole("button", { name: /Przenieś na etap: CV wysłane/ });
    expect(forward).not.toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /Przenieś na etap: Preparation Meeting/ }),
    ).toBeNull();
  });

  it("karta bez weta dostaje zwykłą akcję naprzód na „CV wysłane”", async () => {
    renderBoard(vetoRouteColumns({}));
    await openDock();

    expect(
      screen.getByRole("button", { name: /Przenieś na etap: CV wysłane/ }),
    ).not.toBeDisabled();
  });

  // Ruch na „Rozmowę u klienta” pyta najpierw o termin (20.10.2026) — te
  // testy sprawdzają ostrzeżenie serwera, więc przesuwają bez terminu.
  async function skipInterviewDate() {
    const dateDialog = await screen.findByRole("dialog", { name: "Kiedy rozmowa u klienta?" });
    fireEvent.click(within(dateDialog).getByLabelText("Nie znam jeszcze terminu"));
    fireEvent.click(within(dateDialog).getByRole("button", { name: "Przesuń" }));
  }

  it("409 ELIGIBILITY_WARNING otwiera okno z powodem, a „Przenieś mimo to” powtarza ruch z potwierdzeniem", async () => {
    post
      .mockRejectedValueOnce(eligibilityWarning409())
      .mockResolvedValueOnce({ data: { id: 812, process_state_version: 4 } });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={vetoRouteColumns(VETO)} jobId={10} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Rozmowa u klienta" }));
    await skipInterviewDate();

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Ostrzeżenie przed przeniesieniem"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Hiring manager odrzucił już tego kandydata — Brak bankowości.",
      ),
    ).toBeInTheDocument();
    expect(moveCalls()).toHaveLength(1);
    expect(moveCalls()[0][1]).toMatchObject({
      candidate_id: 71,
      stage_def_id: 404,
      acknowledge_eligibility: undefined,
    });

    fireEvent.click(within(dialog).getByRole("button", { name: "Przenieś mimo to" }));

    await waitFor(() => expect(moveCalls()).toHaveLength(2));
    expect(moveCalls()[1][1]).toMatchObject({
      candidate_id: 71,
      job_id: 10,
      stage: "client_interview",
      stage_def_id: 404,
      acknowledge_eligibility: true,
    });
    await waitFor(() =>
      expect(screen.queryByText("Ostrzeżenie przed przeniesieniem")).toBeNull(),
    );
    // Udany ruch odświeża zapytanie strony pod oboma kluczami.
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "10"] }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 10] });
  });

  it("„Anuluj” w oknie ostrzeżenia nie wysyła drugiego ruchu i dociąga prawdę serwera", async () => {
    post.mockRejectedValueOnce(eligibilityWarning409());
    renderBoard(vetoRouteColumns(VETO));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Rozmowa u klienta" }));
    await skipInterviewDate();

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));

    await waitFor(() =>
      expect(screen.queryByText("Ostrzeżenie przed przeniesieniem")).toBeNull(),
    );
    await waitFor(() => expect(kanban).toHaveBeenCalledWith(10));
    await new Promise((r) => setTimeout(r, 50));
    expect(moveCalls()).toHaveLength(1);
  });

  it("ruch zbiorczy pomija kartę z wetem HM i mówi dlaczego — bez liczenia jej jako nieudanej", async () => {
    renderBoard(gateColumns(VETO));
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Zaznacz Jan Bramka" }),
    );
    const bulkTrigger = screen
      .getAllByRole("combobox")
      .find((el) => el.textContent?.includes("Przenieś na etap"));
    await userEvent.click(bulkTrigger as Element);
    await userEvent.click(await screen.findByRole("option", { name: /CV wysłane/ }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(expect.stringContaining("Pominięto 1")),
    );
    const message = toastError.mock.calls[0][0] as string;
    expect(message).toContain("Jan Bramka");
    expect(message).toContain("Brak bankowości");
    expect(message).not.toMatch(/Nie udało się przenieść/);
    expect(moveCalls()).toHaveLength(0);
  });

  it("„CV wysłane” poza Nordeą: DL musi wpisać stawkę — bez „Przesuń bez stawki”", async () => {
    get.mockImplementation(() =>
      Promise.resolve({
        data: {
          effective_budget_hourly: null,
          pipeline_template_id: null,
          can_write_client_rate: false,
        },
      }),
    );
    renderBoard(gateColumns({}));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Przesuń bez stawki" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Przesuń i zapisz" })).toBeDisabled();
    expect(moveCalls()).toHaveLength(0);
  });

  it("„CV wysłane” bez kolejki Cpro: rekruter bez uprawnienia dostaje komunikat z jego nazwą", async () => {
    useAuthStore.setState({ user: { id: 5, role: "recruiter", roles: ["recruiter"] } } as never);
    renderBoard(gateColumns({}));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        expect.stringContaining(
          "uprawnieniem „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”",
        ),
      ),
    );
    // O tym, kto wysyła, decyduje uprawnienie — komunikat nie wskazuje roli.
    expect(toastError).not.toHaveBeenCalledWith(expect.stringContaining("Delivery Lead"));
    expect(moveCalls()).toHaveLength(0);
  });

  it("„CV wysłane” bez kolejki Cpro: rekruter z nadanym uprawnieniem wpisuje stawkę jak Delivery Lead", async () => {
    useAuthStore.setState({
      user: {
        id: 5,
        role: "recruiter",
        roles: ["recruiter"],
        effective_action_access: permissionSnapshot("recruitment_manage"),
      },
    } as never);
    renderBoard(gateColumns({}));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Przesuń i zapisz" })).toBeDisabled();
    expect(toastError).not.toHaveBeenCalled();
    expect(moveCalls()).toHaveLength(0);
  });

  it("„CV wysłane” bez kolejki Cpro: Delivery Lead z wyłączonym uprawnieniem nie wysyła mimo roli", async () => {
    useAuthStore.setState({
      user: {
        id: 6,
        role: "delivery_lead",
        roles: ["delivery_lead"],
        effective_action_access: permissionSnapshot("delivery_view", "clients_edit"),
      },
    } as never);
    renderBoard(gateColumns({}));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        expect.stringContaining("Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta"),
      ),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(moveCalls()).toHaveLength(0);
  });

  // Osoba z zaliczonym QC CV u klienta bez kolejki Cpro: kto ma uprawnienie do wysyłki,
  // dostaje pełny przegląd przed wysłaniem zamiast samego okna stawki.
  function qcPassedColumns() {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[3] = {
      ...columns[3],
      count: 1,
      items: [
        {
          id: 7301,
          candidate_id: 8301,
          stage: "new",
          name: "Iga",
          lastname: "Mazur",
          days_in_stage: 1,
          qc: { status: "passed", blocking_failed: 0 },
        },
      ],
    };
    return columns as never;
  }

  async function sendFromQcDock() {
    renderBoard(qcPassedColumns());
    const link = await screen.findByRole("link", { name: "Iga Mazur" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    await screen.findByRole("complementary", { name: "Panel osoby" });
    await userEvent.click(screen.getByRole("button", { name: "Inny etap…" }));
    const menu = await screen.findByRole("menu");
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));
  }

  it.each([
    ["Delivery Lead (uprawnienie domyślne)", { id: 7, role: "delivery_lead", roles: ["delivery_lead"] }],
    [
      "rekruter z nadanym uprawnieniem",
      {
        id: 8,
        role: "recruiter",
        roles: ["recruiter"],
        effective_action_access: permissionSnapshot("recruitment_manage"),
      },
    ],
  ])("z „QC CV” do klienta: %s dostaje przegląd przed wysłaniem", async (_label, user) => {
    useAuthStore.setState({ user } as never);
    await sendFromQcDock();

    expect(await screen.findByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7301");
    expect(toastError).not.toHaveBeenCalled();
    expect(moveCalls()).toHaveLength(0);
  });

  // Jeden panel osoby (04.10.2026): przegląd otwiera się W panelu osoby jako
  // szeroki tryb, dok jest pod nim ukryty, a po zamknięciu wraca.
  it("przegląd DL otwiera się w panelu osoby (szeroko), dok wraca po zamknięciu", async () => {
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    await sendFromQcDock();
    const review = await screen.findByTestId("dl-review-panel");
    const panel = screen.getByRole("complementary", { name: "Panel osoby" });
    expect(panel).toContainElement(review);
    expect(review).toHaveAttribute("data-layout", "panel");
    expect(panel).toHaveAttribute("data-wide");
    // Przegląd ma cały panel dla siebie (D4) — bez strefy podglądu screeningu.
    expect(panel).toHaveAttribute("data-size", "review");
    expect(screen.getByTestId("person-panel-side")).not.toBeVisible();
    expect(screen.getByTestId("person-panel-dock")).not.toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "zamknij przegląd" }));
    await waitFor(() => expect(screen.queryByTestId("dl-review-panel")).toBeNull());
    expect(screen.getByTestId("person-panel-dock")).toBeVisible();
    expect(screen.getByRole("complementary", { name: "Panel osoby" })).not.toHaveAttribute("data-wide");
    // Pozycja menu, która otworzyła przegląd, już nie istnieje — fokus wraca do panelu.
    await waitFor(() => expect(screen.getByTestId("person-panel-dock")).toHaveFocus());
  });

  it("Escape zamyka najpierw przegląd, a dopiero potem dok", async () => {
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    await sendFromQcDock();
    await screen.findByTestId("dl-review-panel");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("dl-review-panel")).toBeNull());
    expect(screen.getByTestId("person-panel-dock")).toBeVisible();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Panel osoby" })).toBeNull(),
    );
  });

  it("niewysłana notatka w panelu przeżywa przegląd DL (panel ukryty, nie odmontowany)", async () => {
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    renderBoard(qcPassedColumns());
    const link = await screen.findByRole("link", { name: "Iga Mazur" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    const dock = await screen.findByRole("complementary", { name: "Panel osoby" });
    const note = within(dock).getByPlaceholderText(/Dodaj notatkę/);
    await userEvent.type(note, "Zadzwonić po 15");
    await userEvent.click(within(dock).getByRole("button", { name: "Inny etap…" }));
    const menu = await screen.findByRole("menu");
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));
    await screen.findByTestId("dl-review-panel");
    await userEvent.click(screen.getByRole("button", { name: "zamknij przegląd" }));
    const back = await screen.findByRole("complementary", { name: "Panel osoby" });
    // Ten sam węzeł pola: sama wartość wróciłaby też ze szkicu po odmontowaniu.
    expect(within(back).getByPlaceholderText(/Dodaj notatkę/)).toBe(note);
    expect(note).toHaveValue("Zadzwonić po 15");
  });

  it("przegląd z Tablicy dostaje wiersz z serwera (CV po QC, kto zweryfikował)", async () => {
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    get.mockImplementation((url: string) =>
      url === "/api/board-tasks/dl-review-row"
        ? Promise.resolve({
            data: {
              row: { stage_id: 7301, candidate_id: 8301, verified_by_name: "Marta Testowa", cv_stage_id: 7299 },
              can_send_to_client: true,
            },
          })
        : Promise.resolve({ data: { effective_budget_hourly: null, pipeline_template_id: null } }),
    );
    await sendFromQcDock();

    const panel = await screen.findByTestId("dl-review-panel");
    await waitFor(() => expect(panel).toHaveAttribute("data-verified-by", "Marta Testowa"));
    expect(panel).toHaveAttribute("data-cv-stage-id", "7299");
    expect(panel).toHaveAttribute("data-can-send", "true");
    expect(get).toHaveBeenCalledWith("/api/board-tasks/dl-review-row", {
      params: { candidate_id: 8301, job_id: 10 },
    });
  });

  function renderReviewLink(candidateId: number) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={qcPassedColumns()}
            jobId={10}
            initialDockCandidateId={candidateId}
            initialDockOpensReview
            onInitialDockHandled={vi.fn()}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
  }

  it("link z dzwonka „CV do przeglądu” (`review=1`) otwiera przegląd DL", async () => {
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
    renderReviewLink(8301);
    expect(await screen.findByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7301");
    expect(toastInfo).not.toHaveBeenCalled();
    scrollIntoView.mockRestore();
  });

  it("`review=1` bez prawa wysyłki zostawia sam panel osoby i mówi dlaczego", async () => {
    useAuthStore.setState({ user: { id: 9, role: "recruiter", roles: ["recruiter"] } } as never);
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
    renderReviewLink(8301);
    await screen.findByRole("complementary", { name: "Panel osoby" });
    await waitFor(() =>
      expect(toastInfo).toHaveBeenCalledWith(
        "Ta osoba nie czeka teraz na przegląd przed wysłaniem do klienta.",
      ),
    );
    expect(screen.queryByTestId("dl-review-panel")).toBeNull();
    scrollIntoView.mockRestore();
  });

  it.each([
    ["rekruter bez uprawnienia", { id: 9, role: "recruiter", roles: ["recruiter"] }],
    [
      "Delivery Lead z wyłączonym uprawnieniem",
      {
        id: 10,
        role: "delivery_lead",
        roles: ["delivery_lead"],
        effective_action_access: permissionSnapshot("delivery_view", "clients_edit"),
      },
    ],
  ])("z „QC CV” do klienta: %s nie dostaje przeglądu, tylko komunikat", async (_label, user) => {
    useAuthStore.setState({ user } as never);
    await sendFromQcDock();

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        expect.stringContaining("Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta"),
      ),
    );
    expect(screen.queryByTestId("dl-review-panel")).toBeNull();
    expect(moveCalls()).toHaveLength(0);
  });

  it("„CV wysłane” u Nordei bez prawa zapisu stawki przenosi kartę bez pytania o stawkę", async () => {
    get.mockImplementation(() =>
      Promise.resolve({
        data: {
          effective_budget_hourly: null,
          pipeline_template_id: null,
          can_write_client_rate: false,
        },
      }),
    );
    renderBoard(gateColumns({}), undefined, false, true);
    const menu = await openDockStageMenu();
    // U Nordei kolumna „CV wysłane" nazywa się „Wysłane do Cpro".
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Wysłane do Cpro" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({ candidate_id: 61, stage: "cv_sent" }),
      ),
    );
    expect(screen.queryByText(/stawk[aęi] do klienta/i)).toBeNull();
  });

  it("„CV wysłane” z prawem zapisu stawki do klienta najpierw pyta o stawkę", async () => {
    get.mockImplementation(() =>
      Promise.resolve({
        data: {
          effective_budget_hourly: null,
          pipeline_template_id: null,
          can_write_client_rate: true,
        },
      }),
    );
    renderBoard(gateColumns({}));
    // Odpowiedź `GET /api/jobs/{id}` musi dojść, zanim klikniemy.
    await waitFor(() => expect(get).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));

    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(moveCalls()).toHaveLength(0);
  });

  it("okno „Zweryfikowany” podpowiada stawkę z profilu, a „Zostaw zapisaną stawkę” przesuwa bez nowej stawki", async () => {
    // Bramki pól dotyczą rekrutera — admin i DL przesuwają mimo braków (22.10.2026).
    useAuthStore.setState({ user: { id: 1, role: "recruiter", roles: ["recruiter"] } } as never);
    renderBoard(gateColumns({ candidate_expected_rate_hourly: "120.00" }));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Zweryfikowany" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Kwota")).toHaveValue(120);
    expect(within(dialog).getByRole("button", { name: "Przesuń" })).not.toBeDisabled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Zostaw zapisaną stawkę" }));

    await waitFor(() => expect(move).toHaveBeenCalledTimes(1));
    const body = move.mock.calls[0][0] as Record<string, unknown>;
    expect(body).toMatchObject({
      candidate_id: 61,
      job_id: 10,
      stage: "verified",
      stage_def_id: 302,
    });
    expect(body).not.toHaveProperty("expected_rate_value");
    expect(body).not.toHaveProperty("expected_rate_unit");
  });
});

describe("KanbanBoardV2 — focus na etapie", () => {
  beforeEach(() => {
    // Preferencja widoku jest globalna (per użytkownik, nie per rekrutacja),
    // więc test, który kliknie „Kolumny", zapisałby ją dla następnych.
    window.localStorage.clear();
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("pokazuje pełny pipeline w kolumnach o podłodze 200 px", async () => {
    const { container } = renderBoard(
      overviewColumns(),
      new Map([[90, 82]]),
    );

    // 15 kolumn otwiera się domyślnie w widoku przeglądowym (decyzja Artura
    // 20.09.2026) — ten test opisuje widok KOLUMNOWY, więc przełączamy jawnie.
    await userEvent.click(await screen.findByRole("button", { name: "Widok kolumnowy" }));
    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "full-pipeline");
    expect(board).toHaveClass("overflow-auto");
    const track = within(board).getByTestId("pipeline-board-track");
    expect(track).toHaveClass("flex", "min-h-full", "xl:pointer-fine:gap-1");
    // Pas bez własnej wysokości i scrolla: rośnie do najdłuższej kolumny,
    // a kolumny (i ich pola upuszczenia) rozciągają się do niego (17.10.2026).
    expect(board).not.toHaveClass("flex");
    expect(track.className).not.toMatch(/(^|\s)(h-|overflow-)/);
    for (const column of container.querySelectorAll("[data-colid]")) {
      expect(column.parentElement).toBe(track);
    }
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    for (const column of container.querySelectorAll<HTMLElement>("[data-colid]")) {
      // Dawny tryb kafelkowy ściskał kolumnę do zera.
      expect(column).not.toHaveClass("xl:pointer-fine:min-w-0");
      if (column.dataset.narrow === "true") {
        // Pusta kolumna jest wąska (24.09.2026) — 96 px, bez rozpychania.
        expect(column).toHaveClass(
          "xl:pointer-fine:w-24",
          "xl:pointer-fine:min-w-24",
          "xl:pointer-fine:basis-24",
          "xl:pointer-fine:grow-0",
        );
        continue;
      }
      expect(column).toHaveClass(
        "xl:pointer-fine:w-auto",
        "xl:pointer-fine:min-w-[11.5rem]",
        "xl:pointer-fine:basis-[11.5rem]",
        "xl:pointer-fine:grow",
      );
    }
    // Kolumna z kartą ma pełną szerokość, puste są wąskie.
    const narrow = container.querySelectorAll('[data-colid][data-narrow="true"]');
    expect(narrow.length).toBeGreaterThan(0);
    expect(narrow.length).toBeLessThan(container.querySelectorAll("[data-colid]").length);

    expect(container.querySelector("[data-mobile-stage-navigation]")).toHaveClass(
      "xl:pointer-fine:hidden",
    );
    expect(screen.getByTitle("Rozmowa techniczna")).toBeTruthy();
    expect(
      screen.getByRole("group", { name: "Nowi, liczba kandydatów: 1" }),
    ).toBeTruthy();

    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    const card = candidate.closest("[data-kanban-card]");
    expect(card).not.toHaveClass("xl:pointer-fine:pt-6");
    expect(card).toHaveAttribute("data-candidate-id", "90");
    expect(card?.getAttribute("title")).toContain("Aleksandra Nowakowska");
    expect(card?.getAttribute("title")).toContain(
      "Dodano do rekrutacji przez: Ewa Nowak",
    );
    expect(screen.queryByTestId("overview-match-score-90")).toBeNull();
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(container.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Dopasowanie AI: 82 na 100. Ocena: 4.5. W etapie od 5 dni. Dodano do rekrutacji przez: Ewa Nowak",
    );
    const checkbox = screen.getByRole("checkbox", {
      name: "Zaznacz Aleksandra Nowakowska",
    });
    expect(checkbox).toHaveClass("h-6", "w-6", "before:inset-1");
    expect(
      screen.getByRole("button", {
        name: "Usuń Aleksandra Nowakowska z rekrutacji",
      }),
    ).toBeTruthy();
  });

  it("przy czterech etapach zostawia pełną kartę, nie kafelek", async () => {
    const columns = (
      overviewColumns() as unknown as Array<Record<string, unknown>>
    ).slice(0, 4) as never;
    renderBoard(columns);

    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "full-pipeline");
    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    expect(candidate.closest("[data-kanban-card]")).not.toHaveClass(
      "xl:pointer-fine:pt-6",
    );
    expect(screen.queryByTestId("overview-match-score-90")).toBeNull();
    // Pełna karta niesie wiersz „co dalej" (5 dni na etapie wejściowym).
    expect(screen.getByText("Umów screening")).toBeTruthy();
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(document.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Następny krok: Umów screening.",
    );
  });

  it("powyżej dziesięciu kolumn karta startuje jako kafelek, a „Kolumny” ją rozwijają", async () => {
    renderBoard(overviewColumns(), new Map([[90, 82]]));

    await screen.findByTestId("pipeline-board");
    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    // Domyślnie kafelek: karta ściśnięta, wynik jako odznaka zamiast pierścienia.
    expect(candidate.closest("[data-kanban-card]")).toHaveClass(
      "xl:pointer-fine:pt-6",
    );
    expect(screen.getByTestId("overview-match-score-90")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Widok kolumnowy" }));

    expect(candidate.closest("[data-kanban-card]")).not.toHaveClass(
      "xl:pointer-fine:pt-6",
    );
    expect(screen.queryByTestId("overview-match-score-90")).toBeNull();
    expect(screen.getByText("Umów screening")).toBeTruthy();
  });

  it("zachowuje scroll i navigator dla pipeline dłuższego niż 16 etapów", async () => {
    const { container } = renderBoard(overflowColumns());

    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "scroll");
    expect(within(board).getByTestId("pipeline-board-track")).not.toHaveClass("xl:pointer-fine:gap-1");
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(13);
    expect(container.querySelector("[data-colid]")).not.toHaveClass(
      "xl:pointer-fine:min-w-0",
    );
    expect(container.querySelector("[data-mobile-stage-navigation]")).not.toHaveClass(
      "xl:pointer-fine:hidden",
    );
  });

  it("pokazuje wszystkie 15 etapów i nie odmontowuje Droppable po zmianie fokusu", async () => {
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
    const { container } = renderBoard(focusColumns());

    const picker = await screen.findByRole("combobox", {
      name: "Screening, etap 2 z 12",
    });
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    expect(container.querySelector('[data-colid="def:201"]')).toBeTruthy();
    expect(container.querySelector('[data-colid="def:202"]')).toBeTruthy();

    await userEvent.click(picker);
    expect(await screen.findAllByRole("option")).toHaveLength(12);
    await userEvent.click(
      await screen.findByRole("option", {
        name: /12\. Zatrudniony.*liczba kandydatów: 0/,
      }),
    );

    expect(
      await screen.findByRole("combobox", {
        name: "Zatrudniony, etap 12 z 12",
      }),
    ).toBeTruthy();
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    const target = container.querySelector<HTMLElement>('[data-colid="def:215"]');
    expect(target).toBeTruthy();
    expect(scrollIntoView.mock.instances.at(-1)).toBe(target);
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      behavior: "smooth",
      inline: "center",
      block: "nearest",
    });
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Następny etap" })).toBeDisabled();
    scrollIntoView.mockRestore();
  });

  it("nie ma przełącznika gęstości (cozy/kompaktowa)", async () => {
    const { container } = renderBoard(focusColumns());

    await screen.findByRole("combobox", { name: "Screening, etap 2 z 12" });
    expect(screen.queryByRole("button", { name: /Gęstość/ })).toBeNull();
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
  });

  it("nawiguje strzałkami i blokuje poprzedni etap na początku", async () => {
    renderBoard(focusColumns());

    await userEvent.click(
      await screen.findByRole("combobox", {
        name: "Screening, etap 2 z 12",
      }),
    );
    await userEvent.click(
      await screen.findByRole("option", {
        name: /1\. Nowy.*liczba kandydatów: 0/,
      }),
    );

    expect(screen.getByRole("button", { name: "Poprzedni etap" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Następny etap" }));
    expect(
      await screen.findByRole("combobox", {
        name: "Screening, etap 2 z 12",
      }),
    ).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });
});

// ── Kubełek „poza szablonem" ────────────────────────────────────────────────
//
// Karta, której etap nie ma kolumny w szablonie, znikała z tablicy bez śladu
// (1 633 karty na produkcji, pomiar 2026-09-02). Backend zwraca je teraz
// osobnym polem `off_template`. Te testy pilnują dwóch rzeczy naraz: że kubełek
// jest widoczny ORAZ że nie da się do niego nic przenieść.

function offTemplateFixture(count = 2) {
  return {
    name: "Poza szablonem",
    count,
    missing_stage_labels: ["Interview Wewnętrzny"],
    items: Array.from({ length: count }, (_, i) => ({
      id: 9000 + i,
      candidate_id: 500 + i,
      name: "Zofia",
      lastname: `Sierota${i}`,
      stage: "interview",
      days_in_stage: 7,
    })),
  } as never;
}

function renderWithBucket(
  columns = focusColumns(),
  offTemplate: unknown = offTemplateFixture(),
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <KanbanBoardV2
          columns={columns}
          jobId={10}
          offTemplate={offTemplate as never}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("KanbanBoardV2 — karty poza szablonem", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: { id: 1, role: "admin" } } as never);
  });

  it("renderuje kubełek z kartami zamiast je gubić", async () => {
    const { container } = renderWithBucket();

    await screen.findByTestId("pipeline-board");
    const bucket = container.querySelector(
      '[data-colid="stage:__off_template__"]',
    );
    expect(bucket).toBeTruthy();
    expect(screen.getByText("Zofia Sierota0")).toBeTruthy();
  });

  it("nie zmienia układu desktopowego", async () => {
    renderWithBucket();

    const board = await screen.findByTestId("pipeline-board");
    // 15 kolumn szablonu + kubełek — próg NIE może przeskoczyć na "scroll",
    // inaczej 1 009 rekrutacji dostałoby inny layout w nagrodę za bugfix.
    expect(board).toHaveAttribute("data-desktop-layout", "full-pipeline");
  });

  it("nie oferuje kubełka jako celu przeniesienia zbiorczego", async () => {
    const { container } = renderWithBucket();
    await screen.findByTestId("pipeline-board");

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Zaznacz Zofia Sierota0" }),
    );
    const bulkTrigger = screen
      .getAllByRole("combobox")
      .find((el) => el.textContent?.includes("Przenieś na etap"));
    await userEvent.click(bulkTrigger as Element);

    const options = await screen.findAllByRole("option");
    // 12 kolumn Tablicy + 2 zamknięci, bez „Zatrudniony" — hired oznacza się
    // pojedynczo.
    expect(options).toHaveLength(13);
    expect(options.some((o) => o.textContent?.includes("Zatrudniony"))).toBe(false);
    expect(
      options.some((o) => o.textContent?.includes("Poza szablonem")),
    ).toBe(false);
  });

  it("nie oferuje kubełka w nawigatorze etapów", async () => {
    renderWithBucket();

    expect(
      await screen.findByRole("combobox", { name: /etap 2 z 12/ }),
    ).toBeTruthy();
  });

  it("blokuje upuszczenie w kubełku, ale nie w kolumnie szablonu", async () => {
    const { container } = renderWithBucket();
    await screen.findByTestId("pipeline-board");

    // Wiążemy się z TĄ SAMĄ wartością, którą dostaje `isDropDisabled` —
    // DnD nie jest odpalalne w jsdom, więc kopia flagi nic by nie dowiodła.
    expect(
      container.querySelector('[data-colid="stage:__off_template__"]'),
    ).toHaveAttribute("data-drop-disabled", "true");
    expect(
      container.querySelector('[data-colid="def:201"]'),
    ).toHaveAttribute("data-drop-disabled", "false");
  });

  it("baner nazywa brakujący etap i prowadzi do szablonów", async () => {
    renderWithBucket();
    await screen.findByTestId("pipeline-board");

    expect(screen.getByText(/Interview Wewnętrzny/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Otwórz szablony" }),
    ).toHaveAttribute("href", "/settings/pipeline-templates");
  });

  it("zdrowa tablica nie dostaje ani kubełka, ani banera", async () => {
    const { container } = renderWithBucket(focusColumns(), null);
    await screen.findByTestId("pipeline-board");

    expect(
      container.querySelector('[data-colid="stage:__off_template__"]'),
    ).toBeNull();
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    expect(screen.queryByRole("link", { name: "Otwórz szablony" })).toBeNull();
  });
});

// ── Fala 3: grupy etapów, zwinięte grupy, SLA na kolumnie, „co dalej" ───────
//
// Szablon „Default B2B" z produkcji — ZMAPOWANY na legacy enumy (w odróżnieniu
// od `focusColumns()`), bo dopiero wtedy w ogóle powstają grupy etapów.

function defaultB2BColumns() {
  const spec: Array<[string, string, string, number]> = [
    ["new", "Nowi / Analiza CV", "internal", 2],
    ["screening", "Screening", "internal", 1],
    ["verified", "Zweryfikowany", "internal", 0],
    ["new", "Przepuszczony przez DZ", "internal", 0],
    ["new", "Wysłać do Cpro", "internal", 0],
    ["cv_sent", "CV Wysłane", "internal", 0],
    ["new", "Preparation Meeting", "external", 0],
    ["client_interview", "Interview Klient", "external", 0],
    ["acceptance", "Akceptacja", "external", 0],
    ["new", "Umowa wysłana", "external", 0],
    ["new", "Umowa podpisana", "external", 0],
    ["new", "Zatrudniony", "terminal", 0],
    ["onboarding", "Onboarding", "external", 0],
    ["new", "Odrzucony", "terminal", 1],
    ["new", "Wycofany", "terminal", 0],
  ];
  return spec.map(([stage, name, category, count], index) => ({
    stage,
    name,
    category,
    stage_def_id: 300 + index,
    count,
    terminal_type:
      name === "Zatrudniony"
        ? "hired"
        : name === "Odrzucony"
          ? "rejected"
          : name === "Wycofany"
            ? "withdrawn"
            : null,
    items: Array.from({ length: count }, (_, i) => ({
      id: 1000 + index * 100 + i,
      candidate_id: 2000 + index * 100 + i,
      stage,
      name: "Kandydat",
      lastname: `${name.slice(0, 6)}${i}`,
      // Dwa dni na etapie → „Umów screening"; dziewięć → zaległość.
      days_in_stage: i === 0 ? 2 : 9,
      added_to_job_by_name: "Katarzyna Nowak",
    })),
  })) as never;
}

describe("KanbanBoardV2 — fala 3: grupy etapów i karta z następną akcją", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: { id: 1, role: "admin" } } as never);
  });

  it("nad tablicą nie ma paska filtrów ani liczników (02.10.2026)", async () => {
    renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    expect(screen.queryByRole("toolbar", { name: "Filtry tablicy" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Mój ruch/ })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Filtruj po nazwisku" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Filtry/ })).toBeNull();
    expect(screen.queryByText(/w procesie/)).toBeNull();
    expect(screen.queryByText(/utknęło > 7 d/)).toBeNull();
    expect(screen.queryByTestId("board-closed-bar")).toBeNull();
    // Żadna karta nie jest przygaszona — filtrów nie ma.
    expect(document.querySelector("[data-kanban-card].opacity-40")).toBeNull();
  });

  it("strona wkłada nad kolumny własny pasek i dostaje od tablicy przełącznik widoku", async () => {
    const renderAbove = vi.fn((controls: React.ReactNode) => (
      <div data-testid="above-board">{controls}</div>
    ));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={defaultB2BColumns()} jobId={10} renderAbove={renderAbove} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    const board = await screen.findByTestId("pipeline-board");
    const above = screen.getByTestId("above-board");
    // Pasek stoi PRZED tablicą w dokumencie.
    expect(above.compareDocumentPosition(board) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(renderAbove).toHaveBeenCalled();
  });

  it("plakietka „Twój ruch” stoi tylko na kartach, na których ruch ma patrzący (nie cudze i nie DL)", async () => {
    useAuthStore.setState({ user: { id: 5, role: "recruiter", roles: ["recruiter"] } } as never);
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    // Nowi: jedna karta wolna („Twój ruch”), druga wzięta na 12 h przez Annę.
    const nowi = columns[0].items as Array<Record<string, unknown>>;
    nowi[1] = { ...nowi[1], claim_user_id: 9, claim_user_name: "Anna Kowal", claim_until: "2099-01-01T00:00:00Z" };
    columns[2] = {
      ...columns[2],
      count: 2,
      items: [
        { id: 7201, candidate_id: 8201, stage: "verified", name: "Ola", lastname: "Moja", days_in_stage: 1, recruiter_id: 5, recruiter_name: "Ja Rekruter" },
        { id: 7202, candidate_id: 8202, stage: "verified", name: "Ewa", lastname: "Cudza", days_in_stage: 1, recruiter_id: 9, recruiter_name: "Anna Kowal" },
      ],
    };
    // QC CV zaliczone poza Nordeą — ruch ma Delivery Lead („DL”), nie rekruter.
    columns[3] = {
      ...columns[3],
      count: 1,
      items: [
        { id: 7301, candidate_id: 8301, stage: "new", name: "Iga", lastname: "Mazur", days_in_stage: 1, recruiter_id: 5, qc: { status: "passed", blocking_failed: 0 } },
      ],
    };
    renderBoard(columns as never);
    await screen.findByTestId("pipeline-board");
    // Wolna karta w Nowi + Screening (bez rekrutera = „Twój ruch”) + własna
    // w „Zweryfikowanym”. Poza: karta wzięta przez Annę, cudza, QC oddane DL.
    const mine = screen
      .getAllByTestId("card-next-who")
      .filter((el) => el.textContent?.includes("Twój ruch"));
    expect(mine).toHaveLength(3);
  });

  it("od „Zweryfikowanego” karta pokazuje osobę, która zweryfikowała, a nie dodającą (20.10.2026)", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    const verifiedBy = { verified_by_name: "Olga Weryfikująca", verified_by_id: 81, verified_at: "2026-10-20T09:00:00Z" };
    // Screening: weryfikacja zapisana wcześniej (karta wróciła) — dalej dodający.
    columns[1] = {
      ...columns[1],
      items: [{ id: 7101, candidate_id: 8101, stage: "screening", name: "Jan", lastname: "Wrócił", days_in_stage: 1, added_to_job_by_name: "Piotr Szkicowy", ...verifiedBy }],
    };
    columns[2] = {
      ...columns[2],
      count: 1,
      items: [{ id: 7201, candidate_id: 8201, stage: "verified", name: "Kamil", lastname: "Przykładowy", days_in_stage: 1, added_to_job_by_name: "Piotr Szkicowy", added_to_job_at: "2026-08-17T09:00:00Z", ...verifiedBy }],
    };
    renderBoard(columns as never);
    await screen.findByTestId("pipeline-board");

    const verifiedRow = screen.getByTitle(/^Zweryfikował\(a\): Olga Weryfikująca/);
    expect(verifiedRow.title).toContain("Dodano do rekrutacji przez: Piotr Szkicowy");
    expect(within(verifiedRow).getByText("OW")).toBeInTheDocument();
    expect(within(verifiedRow).getByText("Olga")).toBeInTheDocument();

    const screeningCard = screen.getByText("Jan Wrócił").closest("[data-kanban-card]") as HTMLElement;
    expect(within(screeningCard).getByText("Piotr")).toBeInTheDocument();
    expect(within(screeningCard).queryByText("Olga")).toBeNull();
  });

  it("nawigator doku idzie po kolumnie otwartej osoby, karty od góry — także z etapów złożonych w kolumnę", async () => {
    // Audyt 24.09.2026: pierwsza karta w „Nowi” miała „12 z 35”, a „←” prowadziło
    // do ostatniej karty kolumny — dok liczył kolejność z surowych etapów
    // szablonu, łącznie z ukrytymi zamkniętymi. Od 14.10.2026 (D1) kolejka to
    // sama kolumna osoby: Screening nie wchodzi do „Nowych”.
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    // Duplikat nazwy z importu stoi na końcu szablonu, a karta renderuje się w „Nowi”.
    columns.push({
      stage: "new",
      name: "Nowi / Analiza CV (#41)",
      category: "internal",
      stage_def_id: 399,
      count: 1,
      terminal_type: null,
      items: [{ id: 7399, candidate_id: 8399, stage: "new", name: "Duplikat", lastname: "Importu", days_in_stage: 1 }],
    });
    renderBoard(columns as never);
    await screen.findByTestId("pipeline-board");
    const cards = Array.from(document.querySelectorAll("[data-kanban-card]")) as HTMLElement[];
    fireEvent.click(cards[0]);
    const dock = await screen.findByRole("complementary", { name: "Panel osoby" });
    // Nowi (2 + duplikat złożony w tę kolumnę); Screening i zamknięci poza kolejką.
    expect(within(dock).getByText("1 z 3")).toBeInTheDocument();
    expect(within(dock).getByTestId("dock-queue-label")).toHaveTextContent("Nowi");
    expect(within(dock).getByRole("button", { name: "Poprzednia karta" })).toBeDisabled();
    fireEvent.click(within(dock).getByRole("button", { name: "Następna karta" }));
    fireEvent.click(within(dock).getByRole("button", { name: "Następna karta" }));
    expect(await within(dock).findByText("3 z 3")).toBeInTheDocument();
    expect(within(dock).getAllByText(/Duplikat Importu/).length).toBeGreaterThan(0);
    expect(within(dock).getByRole("button", { name: "Następna karta" })).toBeDisabled();
  });

  it("akceptacja klienta (D1–D6): przycisk po rozmowie, zielony wiersz i liczniki w „Akceptacja i umowa”", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    const withItem = (index: number, item: Record<string, unknown>) => {
      columns[index] = { ...columns[index], count: 1, items: [{ stage: columns[index].stage, days_in_stage: 1, ...item }] };
    };
    withItem(7, { id: 7701, candidate_id: 8701, name: "Karol", lastname: "Wzorcowy" });
    withItem(8, {
      id: 7801,
      candidate_id: 8801,
      name: "Iza",
      lastname: "Umowna",
      client_acceptance: {
        stage_id: 7801,
        accepted_on: "2026-10-16",
        planned_start_on: null,
        marked_at: "2026-10-16T09:00:00Z",
        marked_by_name: "Olga Wzorcowa",
      },
    });
    withItem(9, { id: 7901, candidate_id: 8901, name: "Jan", lastname: "Próbny" });
    get.mockImplementation((url: string) => {
      if (url === "/api/pipeline/client-acceptance/recipients") {
        return Promise.resolve({
          data: { recipients: [{ user_id: 5, name: "Marta Nowak", role: "recruiter", role_label: "rekruter kandydata" }] },
        });
      }
      if (url === "/api/pipeline/move-requirements") {
        return Promise.resolve({
          data: { from_column: "client_interview", to_column: "contract", skipped_columns: [], items: [], primary: { kind: "move", label: "Przesuń" } },
        });
      }
      return Promise.resolve({ data: {} });
    });
    hmRecord.mockResolvedValue({});
    const { container } = renderBoard(columns as never);
    await screen.findByTestId("pipeline-board");

    // Kolumna „Akceptacja i umowa”: podpis i liczniki kroków.
    const contract = container.querySelector('[data-colid="def:308"]') as HTMLElement;
    expect(within(contract).getByText("Akceptacja i umowa")).toBeInTheDocument();
    expect(within(contract).getByText("Klient zaakceptował → umowa → podpis")).toBeInTheDocument();
    expect(within(contract).getByTestId("contract-step-accepted")).toHaveTextContent("Zaakceptowani 1");
    expect(within(contract).getByTestId("contract-step-sent")).toHaveTextContent("Umowa wysłana 1");
    expect(within(contract).getByTestId("contract-step-signed")).toHaveTextContent("Podpisana 0");
    // Karta po akceptacji: zielony wiersz zamiast małej plakietki „Akceptacja”.
    const iza = contract.querySelector('[data-candidate-id="8801"]') as HTMLElement;
    expect(within(iza).getByTestId("card-client-acceptance")).toHaveTextContent(
      "✓ Klient zaakceptował · 16.10 · Olga W.",
    );
    expect(within(iza).queryByText("Akceptacja")).toBeNull();
    // Karta bez zapisanej akceptacji w tej kolumnie (stary ruch) — bez zielonego wiersza.
    const jan = contract.querySelector('[data-candidate-id="8901"]') as HTMLElement;
    expect(within(jan).queryByTestId("card-client-acceptance")).toBeNull();

    // Karta po rozmowie: „Klient zaakceptował” otwiera okno, zapis = ruch z datą
    // akceptacji, potem werdykt „Akceptuje” i dymek z odbiorcami dzwonka.
    // Strzałka „→” z rozmowy na „Akceptację i umowę” to też akceptacja — to samo okno,
    // bez ruchu „na ślepo”.
    fireEvent.click(screen.getByRole("button", { name: "Przesuń Karol Wzorcowy na następny etap" }));
    const viaArrow = await screen.findByRole("dialog", { name: /Klient zaakceptował: Karol Wzorcowy/ });
    expect(post).not.toHaveBeenCalledWith("/api/pipeline/move", expect.anything());
    fireEvent.click(within(viaArrow).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /Klient zaakceptował/ })).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Klient zaakceptował: Karol Wzorcowy" }));
    const dialog = await screen.findByRole("dialog", { name: /Klient zaakceptował: Karol Wzorcowy/ });
    expect(await within(dialog).findByText("Marta Nowak")).toBeInTheDocument();
    const save = within(dialog).getByRole("button", { name: "Zapisz akceptację" });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({
          candidate_id: 8701,
          stage_def_id: 308,
          client_accepted_on: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        }),
      ),
    );
    await waitFor(() =>
      expect(hmRecord).toHaveBeenCalledWith(10, {
        candidate_id: 8701,
        decision: "advance",
        rejection_reason_id: null,
        note: null,
      }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Karol Wzorcowy — klient zaakceptował. Powiadomienie: Marta N.");
  });

  it("Tablica: 8 kolumn z numerem kroku, „QC CV” gospodarzem etapu DZ, zamknięci w wąskiej kolumnie obok", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    // Osoba na etapie „Przepuszczony przez DZ" (index 3) — gospodarz kolumny „QC CV".
    columns[3] = {
      ...columns[3],
      count: 1,
      items: [{ id: 7301, candidate_id: 8301, stage: "new", name: "Iga", lastname: "Mazur", days_in_stage: 1 }],
    };
    const { container } = renderBoard(columns as never);
    await screen.findByTestId("pipeline-board");

    const headers = Array.from(container.querySelectorAll("[data-colid] h3")).map((h) => h.textContent);
    // „Nowi” to zwykła kolumna — bez bloku propozycji i bez „Dodaj kandydatów”.
    expect(screen.queryByTestId("board-review")).toBeNull();
    expect(headers).toEqual([
      "Nowi",
      "Screening",
      "Zweryfikowany",
      "QC CV",
      "CV wysłane",
      "Rozmowa u klienta",
      "Akceptacja i umowa",
      "Zatrudniony",
    ]);
    const steps = Array.from(container.querySelectorAll('[data-testid="column-step"]')).map(
      (el) => el.textContent,
    );
    expect(steps).toEqual(["1", "2", "3", "4", "5", "6", "7", "8"]);
    // Karta z etapu DZ stoi w „QC CV” — bez dawnej odznaki „DZ ✓”, z chipem QC.
    const qcCol = container.querySelector('[data-colid="def:303"]') as HTMLElement;
    expect(within(qcCol).getByText("Iga Mazur")).toBeTruthy();
    expect(within(qcCol).queryByText("DZ ✓")).toBeNull();
    expect(within(qcCol).getByTestId("card-qc-chip")).toHaveTextContent("QC nie sprawdzone");
    // Niesprawdzone QC: ruch ma rekruter („Sprawdź QC CV”), nie DL.
    expect(within(qcCol).getByTestId("card-next-who")).toHaveTextContent("Twój ruch");
    // Odrzuceni i wycofani nie zajmują pełnych kolumn — stoją w wąskiej kolumnie
    // „Zamknięci” obok tablicy, a każda strefa jest celem upuszczenia.
    const closed = screen.getByRole("region", { name: "Zamknięci" });
    expect(closed).toHaveAttribute("data-testid", "board-closed-column");
    expect(screen.getByTestId("pipeline-board")).not.toContainElement(closed);
    expect(closed).toHaveTextContent("przez nas1");
    expect(closed).toHaveTextContent("przez DL0");
    expect(closed).toHaveTextContent("przez klienta0");
    expect(closed).toHaveTextContent("zrezygnował0");
    expect(closed.querySelectorAll("[data-rfd-droppable-id]")).toHaveLength(4);
    expect(container.querySelector('[data-colid="def:313"]')).toBeNull();
    await userEvent.click(within(closed).getByRole("button", { name: /Odrzucony przez nas/ }));
    expect(container.querySelector('[data-colid="def:313"]')).toBeTruthy();
    // Rozwinięte kolumny zamkniętych da się zwinąć z tego samego miejsca.
    await userEvent.click(within(closed).getByRole("button", { name: "Zwiń zamkniętych" }));
    expect(container.querySelector('[data-colid="def:313"]')).toBeNull();
  });

  it("tablica bez zamkniętych etapów w szablonie nie ma kolumny „Zamknięci”", async () => {
    const open = (defaultB2BColumns() as unknown as Array<Record<string, unknown>>).filter(
      (col) => col.terminal_type !== "rejected" && col.terminal_type !== "withdrawn",
    );
    renderBoard(open as never);
    await screen.findByTestId("pipeline-board");
    expect(screen.queryByTestId("board-closed-column")).toBeNull();
  });

  it("chip QC mówi wynik ostatniej kontroli i otwiera okno QC CV tej karty", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[3] = {
      ...columns[3],
      count: 1,
      items: [
        {
          id: 7302,
          candidate_id: 8302,
          stage: "new",
          name: "Kuba",
          lastname: "Braki",
          days_in_stage: 1,
          qc: { status: "failed", blocking_failed: 3 },
        },
      ],
    };
    renderBoard(columns as never);
    const chip = await screen.findByRole("button", { name: /QC: 3 do poprawy — otwórz QC CV dla Kuba Braki/ });
    // Znany brak — strzałka jest szara, ale klikalna.
    const card = document.querySelector('[data-candidate-id="8302"]') as HTMLElement;
    expect(within(card).getByTestId("card-advance")).toHaveAttribute("data-gap", "true");
    expect(within(card).getByTestId("card-next-who")).toHaveTextContent("Twój ruch");
    await userEvent.click(chip);
    expect(await screen.findByTestId("cv-qc-dialog")).toHaveAttribute("data-stage-id", "7302");
  });

  const qcColumns = (qc: { status: string; blocking_failed: number }) => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[3] = {
      ...columns[3],
      count: 1,
      items: [{ id: 7302, candidate_id: 8302, stage: "new", name: "Kuba", lastname: "Braki", days_in_stage: 1, qc }],
    };
    return columns;
  };
  const moveRequirements = (items: unknown[]) =>
    get.mockImplementation((url: string) =>
      url === "/api/pipeline/move-requirements"
        ? Promise.resolve({
            data: {
              from_column: "cv_qc",
              to_column: "cv_sent",
              skipped_columns: [],
              items,
              primary: { kind: "move", label: "Przesuń na „CV wysłane”" },
              owner_note: null,
            },
          })
        : Promise.resolve({ data: {} }),
    );

  it("„Przesuń dalej” z okna QC otwiera okno ruchu na następną kolumnę — nie przesuwa samo", async () => {
    qcResultCandidate.id = 8302;
    moveRequirements([]);
    renderBoard(qcColumns({ status: "passed", blocking_failed: 0 }) as never);
    await userEvent.click(await screen.findByRole("button", { name: /otwórz QC CV dla Kuba Braki/ }));
    await userEvent.click(await screen.findByRole("button", { name: "QC: przesuń dalej" }));
    await waitFor(() => expect(screen.queryByTestId("cv-qc-dialog")).toBeNull());
    const dialog = await screen.findByTestId("move-next-dialog");
    expect(dialog).toHaveTextContent("Kuba Braki");
    // Ruch etapu ma jedną drogę: okno „Przesuń dalej” i `usePipelineMove`.
    expect(post.mock.calls.filter((c) => c[0] === "/api/pipeline/move")).toHaveLength(0);
  });

  // Nordea (13.10.2026): „Przejrzyj i zaakceptuj do Cpro” z okna „Przesuń
  // dalej” otwiera przegląd z celem „Wysłać do Cpro” — goły ruch na etap Cpro
  // bez stawki serwer odrzuca (422).
  it("Nordea: „Przejrzyj i zaakceptuj do Cpro” w oknie „Przesuń dalej” otwiera przegląd, nie ruch", async () => {
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    qcResultCandidate.id = 8302;
    get.mockImplementation((url: string) =>
      url === "/api/pipeline/move-requirements"
        ? Promise.resolve({
            data: {
              from_column: "cv_qc",
              to_column: "cv_sent",
              skipped_columns: [],
              items: [],
              primary: { kind: "hand_to_cpro", label: "Przejrzyj i zaakceptuj do Cpro", target_stage_def_id: 304 },
              owner_note: null,
            },
          })
        : Promise.resolve({ data: {} }),
    );
    renderBoard(qcColumns({ status: "passed", blocking_failed: 0 }) as never, undefined, false, true, true);
    await screen.findByTestId("pipeline-board");
    const card = document.querySelector('[data-candidate-id="8302"]') as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: /otwórz QC CV dla Kuba Braki/ }));
    await userEvent.click(await screen.findByRole("button", { name: "QC: przesuń dalej" }));
    const dialog = await screen.findByTestId("move-next-dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /Przejrzyj i zaakceptuj do Cpro/ }));

    const panel = await screen.findByTestId("dl-review-panel");
    expect(panel).toHaveAttribute("data-stage-id", "7302");
    expect(panel).toHaveAttribute("data-target-stage-def-id", "304");
    expect(panel).toHaveAttribute("data-cpro", "true");
    expect(post.mock.calls.filter((c) => c[0] === "/api/pipeline/move")).toHaveLength(0);
  });

  // Test na produkcji 03.10.2026: strzałka na karcie otwierała samo okno stawki
  // do klienta — bez karty rekomendacji, uwag i „Wróć do poprawy”. Od 13.10.2026
  // gotowa karta ma u osoby z prawem wysyłki „Przejrzyj i wyślij” zamiast
  // strzałki, więc okno „Przesuń dalej” otwiera tu „Przesuń dalej” z okna QC.
  it("okno „Przesuń dalej” z „QC CV” do klienta otwiera ten sam przegląd co dok", async () => {
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    qcResultCandidate.id = 8302;
    moveRequirements([]);
    renderBoard(qcColumns({ status: "passed", blocking_failed: 0 }) as never);
    await screen.findByTestId("pipeline-board");
    const card = document.querySelector('[data-candidate-id="8302"]') as HTMLElement;
    expect(within(card).queryByTestId("card-advance")).toBeNull();
    await userEvent.click(within(card).getByRole("button", { name: /otwórz QC CV dla Kuba Braki/ }));
    await userEvent.click(await screen.findByRole("button", { name: "QC: przesuń dalej" }));
    const dialog = await screen.findByTestId("move-next-dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /Przesuń na „CV wysłane”/ }));

    expect(await screen.findByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7302");
    await waitFor(() => expect(screen.queryByTestId("move-next-dialog")).toBeNull());
    expect(post.mock.calls.filter((c) => c[0] === "/api/pipeline/move")).toHaveLength(0);
  });

  // `defaultB2BColumns`: „CV wysłane” to szósta kolumna szablonu (300 + 5).
  const SENT_COLUMN_ID = "def:305";

  it("przeciągnięcie z „QC CV” na „CV wysłane” też otwiera przegląd", async () => {
    useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    renderBoard(qcColumns({ status: "passed", blocking_failed: 0 }) as never);
    await screen.findByTestId("pipeline-board");
    const card = document.querySelector('[data-candidate-id="8302"]') as HTMLElement;
    const source = card.closest("[data-rfd-droppable-id]")?.getAttribute("data-rfd-droppable-id");
    expect(source).toBeTruthy();

    act(() =>
      dnd.onDragEnd?.({
        draggableId: "7302",
        type: "DEFAULT",
        reason: "DROP",
        mode: "FLUID",
        combine: null,
        source: { droppableId: source, index: 0 },
        destination: { droppableId: SENT_COLUMN_ID, index: 0 },
      }),
    );

    expect(await screen.findByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7302");
    expect(screen.queryByTestId("move-next-dialog")).toBeNull();
    expect(post.mock.calls.filter((c) => c[0] === "/api/pipeline/move")).toHaveLength(0);
  });

  it("QC otwarte z listy braków wraca po „Przesuń dalej” do tego samego okna ruchu", async () => {
    qcResultCandidate.id = 8302;
    moveRequirements([
      {
        key: "cv_qc",
        label: "QC CV",
        detail: "do poprawy: 1",
        status: "missing",
        blocking: true,
        action: { kind: "open_qc", label: "Otwórz QC CV", stage_id: 7302 },
      },
    ]);
    renderBoard(qcColumns({ status: "failed", blocking_failed: 1 }) as never);
    await screen.findByTestId("pipeline-board");
    const card = document.querySelector('[data-candidate-id="8302"]') as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: /Przesuń Kuba Braki na następny etap/ }));
    const dialog = await screen.findByTestId("move-next-dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Otwórz QC CV" }));
    await waitFor(() => expect(screen.queryByTestId("move-next-dialog")).toBeNull());
    expect(screen.getByTestId("cv-qc-dialog")).toHaveAttribute("data-stage-id", "7302");
    const before = get.mock.calls.filter((c) => c[0] === "/api/pipeline/move-requirements").length;
    await userEvent.click(screen.getByRole("button", { name: "QC: przesuń dalej" }));
    expect(await screen.findByTestId("move-next-dialog")).toBeTruthy();
    expect(screen.queryByTestId("cv-qc-dialog")).toBeNull();
    // Wymagania liczone od nowa — QC mogło się w międzyczasie zaliczyć.
    await waitFor(() =>
      expect(get.mock.calls.filter((c) => c[0] === "/api/pipeline/move-requirements").length).toBeGreaterThan(before),
    );
  });

  it("tablica tylko do odczytu: okno QC nie ma „Przesuń dalej”", async () => {
    renderBoard(qcColumns({ status: "passed", blocking_failed: 0 }) as never, undefined, true);
    await userEvent.click(await screen.findByRole("button", { name: /otwórz QC CV dla Kuba Braki/ }));
    expect(await screen.findByTestId("cv-qc-dialog")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "QC: przesuń dalej" })).toBeNull();
  });

  it("dok nie ma już przełączników DZ ani Cpro (także u Nordei)", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[2] = {
      ...columns[2],
      count: 1,
      items: [{ id: 7201, candidate_id: 8201, stage: "verified", name: "Olek", lastname: "Nowy", days_in_stage: 1 }],
    };
    renderBoard(columns as never, undefined, false, true);
    await screen.findByText("Olek Nowy");
    fireEvent.click(document.querySelector('[data-candidate-id="8201"]') as HTMLElement);
    const dock = await screen.findByRole("complementary", { name: "Panel osoby" });
    expect(within(dock).queryByRole("group", { name: "Odznaki etapu" })).toBeNull();
    expect(within(dock).queryByRole("button", { name: /DZ/ })).toBeNull();
    expect(within(dock).queryByRole("button", { name: /Cpro/ })).toBeNull();
  });

  it("nagłówek „Nowi” liczy tylko karty — propozycje stoją na kaflach nad tablicą", async () => {
    // „Default B2B": 2 karty w „Nowi / Analiza CV" (Screening to osobna kolumna).
    const { container: base } = renderBoard(defaultB2BColumns());
    await waitFor(() =>
      expect(base.querySelector('[aria-label="Nowi, liczba kandydatów: 2"]')).toBeTruthy(),
    );

    // Z etapem „Ogłoszenia" (1 karta) nagłówek liczy 1 + 2.
    rtlCleanup();
    const withPosting = [
      {
        stage: "posting",
        name: "Ogłoszenia",
        category: "internal",
        stage_def_id: 299,
        count: 1,
        items: [{ id: 7001, candidate_id: 8001, stage: "posting", name: "Ada", lastname: "Z Ogłoszenia", days_in_stage: 0 }],
      },
      ...(defaultB2BColumns() as unknown as Array<Record<string, unknown>>),
    ];
    const { container } = renderBoard(withPosting as never);
    await waitFor(() =>
      expect(container.querySelector('[aria-label="Nowi, liczba kandydatów: 3"]')).toBeTruthy(),
    );
  });

  it("u Nordei kolumna to „Wysłane do Cpro”, a karta w kolejce Cpro ma znacznik", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[4] = {
      ...columns[4],
      count: 1,
      items: [{ id: 7401, candidate_id: 8401, stage: "new", name: "Ewa", lastname: "Cpro", days_in_stage: 1 }],
    };
    const { container } = renderBoard(columns as never, undefined, false, true);
    await screen.findByText("Ewa Cpro");
    const headers = Array.from(container.querySelectorAll("[data-colid] h3")).map((h) => h.textContent);
    expect(headers).toContain("Wysłane do Cpro");
    expect(headers).not.toContain("CV wysłane");
    // 26.10.2026: kolejka Cpro to własna kolumna „Do Cpro” zaraz po „QC CV”.
    expect(headers.indexOf("Do Cpro")).toBe(headers.indexOf("QC CV") + 1);
    const qcCol = container.querySelector('[data-colid="def:303"]') as HTMLElement;
    expect(within(qcCol).queryByText("Ewa Cpro")).toBeNull();
    const cproCol = container.querySelector('[data-colid="def:304"]') as HTMLElement;
    expect(within(cproCol).getByText("Wrzuca osoba od Cpro")).toBeTruthy();
    const card = within(cproCol).getByText("Ewa Cpro").closest("[data-kanban-card]") as HTMLElement;
    expect(within(card).getByText("W kolejce Cpro")).toBeTruthy();
    expect(within(card).queryByText("DZ ✓")).toBeNull();
    expect(within(card).getByTestId("card-next-who")).toHaveTextContent("Osoba od Cpro");
  });

  // Zgłoszenie z 26.10.2026: DL Nordei odłożył kartę na „QC CV” we własnej
  // rekrutacji. Przegląd czekał na niego samego, dzwonek do siebie resolver
  // odsiał, a osoba od Cpro nie dostała nic.
  describe("Nordea: DL kieruje kartę do Cpro (26.10.2026)", () => {
    function verifiedColumns() {
      const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
      columns[2] = {
        ...columns[2],
        count: 1,
        items: [{ id: 7501, candidate_id: 8501, stage: "verified", name: "Ola", lastname: "Gotowa", days_in_stage: 1, verification_status: "active" }],
      };
      return columns as never;
    }

    const moveCalls = () => post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");

    async function moveFromDock(columns: never, target: string, ownsReview: boolean) {
      renderBoard(columns, undefined, false, true, ownsReview);
      const name = await screen.findByText("Ola Gotowa");
      fireEvent.click(name.closest("[data-kanban-card]") as HTMLElement);
      await screen.findByRole("complementary", { name: "Panel osoby" });
      await userEvent.click(screen.getByRole("button", { name: "Inny etap…" }));
      const menu = await screen.findByRole("menu");
      await userEvent.click(within(menu).getByRole("menuitem", { name: target }));
    }

    beforeEach(() => {
      useAuthStore.setState({ user: { id: 7, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
    });

    it("„QC CV” we własnej rekrutacji otwiera akceptację do Cpro zamiast ruchu", async () => {
      await moveFromDock(verifiedColumns(), "QC CV", true);
      const panel = await screen.findByTestId("dl-review-panel");
      expect(panel).toHaveAttribute("data-stage-id", "7501");
      expect(panel).toHaveAttribute("data-target-stage-def-id", "304");
      expect(panel).toHaveAttribute("data-cpro", "true");
      expect(moveCalls()).toHaveLength(0);
    });

    it("„QC CV” w cudzej rekrutacji to zwykłe przekazanie do przeglądu DL-a", async () => {
      await moveFromDock(verifiedColumns(), "QC CV", false);
      await waitFor(() => expect(moveCalls()).toHaveLength(1));
      expect(screen.queryByTestId("dl-review-panel")).toBeNull();
    });

    it("„Do Cpro” sprzed „QC CV” otwiera akceptację ze stawką", async () => {
      await moveFromDock(verifiedColumns(), "Do Cpro", false);
      const panel = await screen.findByTestId("dl-review-panel");
      expect(panel).toHaveAttribute("data-target-stage-def-id", "304");
      expect(moveCalls()).toHaveLength(0);
    });
  });

  it("strzałka „→” otwiera „Przesuń dalej”: braki blokują przycisk, akcja otwiera arkusz", async () => {
    // Bramki pól dotyczą rekrutera — admin i DL przesuwają mimo braków (22.10.2026).
    useAuthStore.setState({ user: { id: 1, role: "recruiter", roles: ["recruiter"] } } as never);
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    get.mockImplementation((url: string) =>
      url === "/api/pipeline/move-requirements"
        ? Promise.resolve({
            data: {
              from_column: "screening",
              to_column: "verified",
              skipped_columns: [],
              items: [
                {
                  key: "screening_sheet",
                  label: "Arkusz screeningu",
                  detail: "jeszcze niewypełniony",
                  status: "missing",
                  blocking: true,
                  action: { kind: "open_screening", label: "Otwórz arkusz", stage_id: 1100 },
                },
              ],
              primary: { kind: "move", label: "Przesuń na „Zweryfikowany”" },
              owner_note: null,
            },
          })
        : Promise.resolve({ data: {} }),
    );
    renderBoard(columns as never);
    await screen.findByTestId("pipeline-board");
    // Karta ze Screeningu (index 1).
    const card = document.querySelector('[data-candidate-id="2100"]') as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: /Przesuń Kandydat Screen0 na następny etap/ }));

    const dialog = await screen.findByTestId("move-next-dialog");
    await within(dialog).findByText("Arkusz screeningu");
    expect(get).toHaveBeenCalledWith(
      "/api/pipeline/move-requirements",
      expect.objectContaining({
        params: expect.objectContaining({ candidate_id: 2100, job_id: 10, to_stage_def_id: 302 }),
      }),
    );
    expect(within(dialog).getByTestId("move-next-primary")).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Otwórz arkusz" }));
    // Arkusz screeningu (ScreeningSheet) — okno „Przesuń dalej” chowa się na czas akcji.
    await waitFor(() => expect(screen.queryByTestId("move-next-dialog")).toBeNull());
    expect(post.mock.calls.filter((c) => c[0] === "/api/pipeline/move")).toHaveLength(0);
  });

  it("pusta kolumna jest wąska i ma pole „upuść tutaj”, kolumna z kartami — pełna", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");
    const verified = container.querySelector('[data-colid="def:302"]') as HTMLElement;
    const screening = container.querySelector('[data-colid="def:301"]') as HTMLElement;
    expect(verified).toHaveAttribute("data-narrow", "true");
    expect(within(verified).getByTestId("column-drop-hint")).toHaveTextContent("upuść tutaj");
    // `droppableId` bez zmian — upuszczanie trafia w ten sam etap.
    expect(verified.dataset.colid).toBe("def:302");
    expect(screening).not.toHaveAttribute("data-narrow");
    expect(within(screening).queryByTestId("column-drop-hint")).toBeNull();
  });

  it("wąska pusta kolumna zawija nazwę etapu (także w środku słowa), a pełna nazwa zostaje w title", async () => {
    // Audyt 24.09.2026: w 96 px „Zweryfikowany” ucinało się do „Zweryfikowan”.
    // Szerokości jsdom nie liczy — test pilnuje, że nagłówek umie łamać słowo
    // po polsku i nie obcina go do jednej linii.
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");
    const heading = container.querySelector('[data-colid="def:302"] h3') as HTMLElement;
    expect(heading).toHaveTextContent("Zweryfikowany");
    expect(heading).toHaveAttribute("title", "Zweryfikowany");
    expect(heading).toHaveAttribute("lang", "pl");
    expect(heading.className).toMatch(/xl:pointer-fine:hyphens-auto/);
    expect(heading.className).toMatch(/xl:pointer-fine:\[overflow-wrap:anywhere\]/);
    expect(heading.className).toMatch(/xl:pointer-fine:line-clamp-3/);
    // Kolumna z kartami: jedna linia tym samym rozmiarem (04.10.2026 — przy
    // 1280 px duża nazwa łamała się na „Zweryfi-kowany”), pełna nazwa w `title`.
    const full = container.querySelector('[data-colid="def:300"] h3') as HTMLElement;
    expect(full.className).toMatch(/(^| )truncate( |$)/);
    expect(full.className).toMatch(/text-\[13px\]/);
    expect(full.className).not.toMatch(/(^| )text-base( |$)/);
    expect(full).toHaveAttribute("title");
  });

  it("ramka „upuść tutaj” w pustej kolumnie jest widoczna tylko w trakcie przeciągania", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");
    const hint = within(container.querySelector('[data-colid="def:302"]') as HTMLElement).getByTestId(
      "column-drop-hint",
    );
    // W spoczynku ukryta; pokazuje ją znacznik `data-dragging` na korzeniu tablicy.
    expect(hint.className).toMatch(/(^| )hidden( |$)/);
    expect(hint.className).toMatch(/group-data-\[dragging=true\]\/board:block/);
    expect(hint.closest(".group\\/board")).not.toBeNull();
  });

  it("tylko do odczytu: pusta kolumna nie zaprasza do upuszczania", async () => {
    const { container } = renderBoard(defaultB2BColumns(), undefined, true);
    await screen.findByTestId("pipeline-board");
    const verified = container.querySelector('[data-colid="def:302"]') as HTMLElement;
    expect(within(verified).queryByTestId("column-drop-hint")).toBeNull();
  });

  it("nagłówek kolumny niesie drugą linię o SLA i najstarszej karcie", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    // Pod nazwą kolumny „co tu robisz" (v5), po prawej najstarsza karta;
    // pełna informacja o SLA (bez karty klienta — „SLA: —") w dymku.
    const intake = container.querySelector('[data-column-sla="def:300"]');
    expect(intake).toHaveTextContent("Przejrzyj, zadzwoń, kliknij „Biorę”");
    expect(intake).toHaveTextContent("najstarszy 9 d");
    expect(intake).toHaveAttribute("title", "SLA: — · najstarszy 9 d");
    // Po weryfikacji następna jest QC CV — nie „→ CV do klienta" (błąd sprzed v5).
    const verified = container.querySelector('[data-column-sla="def:302"]');
    expect(verified).toHaveTextContent("Stawka ✓ → przygotuj CV do QC");
    expect(verified).not.toHaveTextContent("→ CV do klienta");
    expect(container.querySelector('[data-column-sla="def:303"]')).toHaveTextContent(
      "Popraw CV, potem wyślij",
    );
    expect(container.querySelector('[data-column-sla="def:311"]')).toHaveTextContent("Obsada 0 / —");
  });

  it("karta mówi, co dalej — także gdy następnej akcji brak", async () => {
    renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    // Dwa dni na etapie wejściowym → screening; dziewięć → brak akcji.
    expect(screen.getAllByText("Umów screening").length).toBeGreaterThan(0);
    expect(screen.getByText("Brak następnej akcji")).toBeTruthy();
  });

  it("puste kolumny są zawsze widoczne — stary zapis „ukryj puste” nic nie chowa (25.10.2026)", async () => {
    const first = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");
    const all = first.container.querySelectorAll("[data-colid]").length;
    first.unmount();
    // Zapis `nexus-ui` sprzed v11 mógł mieć tę flagę; migracja ją kasuje,
    // a Tablica i tak jej nie czyta.
    useUiStore.setState({ hideEmptyKanbanColumns: true } as never);
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    // Więcej niż „Nowi” i „Screening” (jedyne z kartami) — puste też stoją.
    expect(all).toBeGreaterThan(2);
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(all);
    expect(screen.queryByTestId("toggle-empty-columns")).toBeNull();
    expect(screen.getByTestId("board-closed-column")).toBeTruthy();
  });
});

// 13.10.2026: Delivery Lead widzi na Tablicy, kto czeka NA NIEGO. `canReviewAsDl`
// (uprawnienie) daje przycisk „Przejrzyj i wyślij”; `viewerOwnsDlReview` (serwer:
// DL tej rekrutacji) — wypełniony przycisk, „Twój ruch”, „Czeka na Ciebie”
// i „Przejrzyj po kolei (N)” w nagłówku kolumny.
describe("KanbanBoardV2 — „Do wysłania do klienta” (13.10.2026)", () => {
  const DELIVERY_LEAD = { id: 7, role: "delivery_lead", roles: ["delivery_lead"] };
  const QUEUE_DONE = "Kolejka przejrzana — nikt więcej nie czeka w tej rekrutacji.";

  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: DELIVERY_LEAD } as never);
  });

  // „QC CV” (etap „Przepuszczony przez DZ”): Iga gotowa od wczoraj, Kuba od
  // trzech dni (QC przepuszczone), Ola jeszcze z poprawkami po QC.
  function readyColumns(count: 1 | 2) {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    const items = [
      { id: 7301, candidate_id: 8301, stage: "new", name: "Iga", lastname: "Mazur", days_in_stage: 1, qc: { status: "passed", blocking_failed: 0 } },
      { id: 7302, candidate_id: 8302, stage: "new", name: "Kuba", lastname: "Braki", days_in_stage: 3, qc: { status: "overridden", blocking_failed: 1 } },
    ].slice(0, count);
    columns[3] = {
      ...columns[3],
      count: items.length + 1,
      items: [
        ...items,
        { id: 7303, candidate_id: 8303, stage: "new", name: "Ola", lastname: "Poprawki", days_in_stage: 2, qc: { status: "failed", blocking_failed: 2 } },
      ],
    };
    return columns as never;
  }

  const cardOf = (candidateId: number) =>
    document.querySelector(`[data-candidate-id="${candidateId}"]`) as HTMLElement;
  const moveCalls = () => post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");

  it("Delivery Lead tej rekrutacji: „Przejrzyj i wyślij” na gotowej karcie otwiera przegląd, nie okno „Przesuń dalej”", async () => {
    renderBoard(readyColumns(1), undefined, false, false, true);
    await screen.findByTestId("pipeline-board");
    const card = cardOf(8301);
    const button = within(card).getByRole("button", { name: "Przejrzyj i wyślij: Iga Mazur" });
    expect(button).toHaveAttribute("data-testid", "card-review-send");
    expect(button).toHaveAttribute("data-owner", "true");
    // Przycisk zastępuje strzałkę; karta mówi, że ruch jest po stronie patrzącego.
    expect(within(card).queryByTestId("card-advance")).toBeNull();
    expect(within(card).getByTestId("card-next-who")).toHaveTextContent("Twój ruch");
    expect(within(card).getByTestId("card-badge-dl_review")).toHaveTextContent("Czeka na Ciebie · 1 dzień");
    // Karta z poprawkami po QC to dalej ruch rekrutera — strzałka, bez przycisku.
    expect(within(cardOf(8303)).queryByTestId("card-review-send")).toBeNull();
    expect(within(cardOf(8303)).getByTestId("card-advance")).toBeInTheDocument();
    // Jedna gotowa osoba — kolejki „po kolei” nie ma.
    expect(screen.queryByTestId("dl-review-sequence-start")).toBeNull();

    await userEvent.click(button);

    expect(await screen.findByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7301");
    expect(screen.queryByTestId("move-next-dialog")).toBeNull();
    // Poza kolejką przegląd jest taki jak dotąd: bez licznika, zamyka się po decyzji.
    expect(screen.queryByTestId("dl-review-sequence")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "decyzja: wyślij" }));
    await waitFor(() => expect(screen.queryByTestId("dl-review-panel")).toBeNull());
    expect(toastInfo).not.toHaveBeenCalled();
    expect(moveCalls()).toHaveLength(0);
  });

  it("dwie gotowe osoby: „Przejrzyj po kolei (2)” prowadzi przez kolejkę — najdłużej czekająca pierwsza, po decyzji następna", async () => {
    const { container } = renderBoard(readyColumns(2), undefined, false, false, true);
    await screen.findByTestId("pipeline-board");
    const start = screen.getByTestId("dl-review-sequence-start");
    // Liczy gotowe osoby (2), nie wszystkie karty kolumny (3).
    expect(start).toHaveTextContent("Przejrzyj po kolei (2)");
    // Stoi w drugiej linii nagłówka „QC CV”, w miejscu tekstu „co tu robisz”.
    const purposeLine = container.querySelector('[data-column-sla="def:303"]') as HTMLElement;
    expect(purposeLine).toContainElement(start);
    expect(purposeLine.querySelector("[data-column-purpose]")).toBeNull();
    // „Porównaj” w pierwszej linii zostaje.
    expect(screen.getByTestId("dl-review-compare")).toHaveTextContent("Porównaj (3)");

    await userEvent.click(start);

    // Kuba czeka trzy dni, Iga jeden — Kuba pierwszy.
    const first = await screen.findByTestId("dl-review-panel");
    expect(first).toHaveAttribute("data-stage-id", "7302");
    expect(within(first).getByTestId("dl-review-sequence")).toHaveTextContent("1 z 2");

    await userEvent.click(within(first).getByRole("button", { name: "decyzja: wyślij" }));

    await waitFor(() =>
      expect(screen.getByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7301"),
    );
    expect(screen.getByTestId("dl-review-sequence")).toHaveTextContent("2 z 2");
    expect(toastInfo).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "decyzja: wyślij" }));

    await waitFor(() => expect(screen.queryByTestId("dl-review-panel")).toBeNull());
    expect(toastInfo).toHaveBeenCalledTimes(1);
    expect(toastInfo).toHaveBeenCalledWith(QUEUE_DONE);
    expect(moveCalls()).toHaveLength(0);
  });

  it("„Pomiń” pokazuje następną osobę, a ręczne zamknięcie przeglądu kończy kolejkę", async () => {
    renderBoard(readyColumns(2), undefined, false, false, true);
    await screen.findByTestId("pipeline-board");
    await userEvent.click(screen.getByTestId("dl-review-sequence-start"));
    expect(await screen.findByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7302");

    await userEvent.click(screen.getByRole("button", { name: "pomiń" }));
    await waitFor(() =>
      expect(screen.getByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7301"),
    );
    expect(screen.getByTestId("dl-review-sequence")).toHaveTextContent("2 z 2");

    await userEvent.click(screen.getByRole("button", { name: "zamknij przegląd" }));
    await waitFor(() => expect(screen.queryByTestId("dl-review-panel")).toBeNull());
    expect(toastInfo).not.toHaveBeenCalled();

    // Kolejka skończona: przegląd z karty otwiera się już bez licznika i nie
    // przeskakuje sam na następną osobę.
    await userEvent.click(within(cardOf(8302)).getByTestId("card-review-send"));
    const review = await screen.findByTestId("dl-review-panel");
    expect(review).toHaveAttribute("data-stage-id", "7302");
    expect(screen.queryByTestId("dl-review-sequence")).toBeNull();
  });

  it("po pominięciu kogoś koniec kolejki nie mówi, że nikt nie czeka", async () => {
    renderBoard(readyColumns(2), undefined, false, false, true);
    await screen.findByTestId("pipeline-board");
    await userEvent.click(screen.getByTestId("dl-review-sequence-start"));
    await screen.findByTestId("dl-review-panel");
    await userEvent.click(screen.getByRole("button", { name: "pomiń" }));
    await waitFor(() =>
      expect(screen.getByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7301"),
    );
    await userEvent.click(screen.getByRole("button", { name: "decyzja: wyślij" }));
    await waitFor(() => expect(screen.queryByTestId("dl-review-panel")).toBeNull());
    expect(toastInfo).toHaveBeenCalledTimes(1);
    expect(toastInfo).toHaveBeenCalledWith("Koniec kolejki — pominięte osoby dalej czekają: 1.");
  });

  it("„Zakończ kolejkę” i Escape zamykają przegląd razem z kolejką", async () => {
    renderBoard(readyColumns(2), undefined, false, false, true);
    await screen.findByTestId("pipeline-board");
    await userEvent.click(screen.getByTestId("dl-review-sequence-start"));
    await screen.findByTestId("dl-review-panel");
    await userEvent.click(screen.getByRole("button", { name: "zakończ kolejkę" }));
    await waitFor(() => expect(screen.queryByTestId("dl-review-panel")).toBeNull());

    await userEvent.click(screen.getByTestId("dl-review-sequence-start"));
    await screen.findByTestId("dl-review-panel");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("dl-review-panel")).toBeNull());
    // Po chwili przegląd dalej jest zamknięty — nikt nie otworzył się sam.
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId("dl-review-panel")).toBeNull();
    expect(toastInfo).not.toHaveBeenCalled();
  });

  it("rekruter nie widzi ani „Przejrzyj i wyślij”, ani „Przejrzyj po kolei”", async () => {
    useAuthStore.setState({ user: { id: 5, role: "recruiter", roles: ["recruiter"] } } as never);
    renderBoard(readyColumns(2));
    await screen.findByTestId("pipeline-board");
    expect(screen.queryByTestId("card-review-send")).toBeNull();
    expect(screen.queryByTestId("dl-review-sequence-start")).toBeNull();
    const card = cardOf(8301);
    expect(within(card).getByTestId("card-advance")).toBeInTheDocument();
    expect(within(card).getByTestId("card-next-who")).toHaveTextContent("DL");
    expect(within(card).getByTestId("card-badge-dl_review")).toHaveTextContent("Czeka na DL · 1 dzień");
  });

  it("Delivery Lead, który może wysłać, ale przegląd nie jest jego: przycisk obrysowany, bez „Przejrzyj po kolei”", async () => {
    renderBoard(readyColumns(2));
    await screen.findByTestId("pipeline-board");
    const buttons = screen.getAllByTestId("card-review-send");
    expect(buttons).toHaveLength(2);
    for (const button of buttons) expect(button).toHaveAttribute("data-owner", "false");
    expect(screen.queryByTestId("dl-review-sequence-start")).toBeNull();
    const card = cardOf(8301);
    expect(within(card).getByTestId("card-next-who")).toHaveTextContent("DL");
    expect(within(card).getByTestId("card-badge-dl_review")).toHaveTextContent("Czeka na DL · 1 dzień");
    expect(within(card).queryByTestId("card-advance")).toBeNull();

    await userEvent.click(within(card).getByTestId("card-review-send"));
    expect(await screen.findByTestId("dl-review-panel")).toHaveAttribute("data-stage-id", "7301");
    expect(screen.queryByTestId("move-next-dialog")).toBeNull();
  });

  it("tablica tylko do odczytu: bez przycisków przeglądu, także u Delivery Leada rekrutacji", async () => {
    renderBoard(readyColumns(2), undefined, true, false, true);
    await screen.findByTestId("pipeline-board");
    expect(screen.queryByTestId("card-review-send")).toBeNull();
    expect(screen.queryByTestId("dl-review-sequence-start")).toBeNull();
  });

  it("Nordea (13.10.2026): Delivery Lead akceptuje w przeglądzie, a jego celem jest etap „Wysłać do Cpro”", async () => {
    renderBoard(readyColumns(2), undefined, false, true, true);
    await screen.findByTestId("pipeline-board");
    const card = cardOf(8301);
    expect(within(card).getByTestId("card-next-who")).toHaveTextContent("Twój ruch");
    expect(within(card).getByTestId("card-badge-dl_review")).toHaveTextContent("Czeka na Ciebie · 1 dzień");
    expect(screen.getByTestId("dl-review-sequence-start")).toHaveTextContent("Przejrzyj po kolei (2)");
    expect(screen.getByTestId("dl-review-compare")).toBeInTheDocument();
    // 14.10.2026: u Nordei nic nie idzie do klienta — przycisk mówi o akceptacji.
    const review = within(card).getByRole("button", { name: "Przejrzyj i zaakceptuj do Cpro: Iga Mazur" });
    expect(review).toHaveTextContent("Przejrzyj → Cpro");
    expect(review).not.toHaveTextContent("wyślij");

    await userEvent.click(review);

    const panel = await screen.findByTestId("dl-review-panel");
    expect(panel).toHaveAttribute("data-stage-id", "7301");
    // „Wysłać do Cpro” w szablonie Default B2B (`defaultB2BColumns`, indeks 4).
    expect(panel).toHaveAttribute("data-target-stage-def-id", "304");
    expect(panel).toHaveAttribute("data-cpro", "true");
    expect(moveCalls()).toHaveLength(0);
  });
});

// Przegląd UX 17.09.2026: dok nie zajmuje kolumny siatki — wysuwa się z prawej
// dopiero po kliknięciu karty, Escape go zamyka, a `?candidate=` otwiera go
// od razu z powiadomienia.
describe("KanbanBoardV2 — wysuwany dok i deep link ?candidate=", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: { id: 1, role: "admin", roles: ["admin"] } } as never);
  });

  function dockColumns() {
    return overviewColumns();
  }

  it("bez kliknięcia karty nie ma doku ani pustego panelu obok tablicy", async () => {
    renderBoard(dockColumns());
    await screen.findByTestId("pipeline-board");
    expect(
      screen.queryByRole("complementary", { name: "Panel osoby" }),
    ).toBeNull();
    expect(screen.queryByText(/Kliknij kartę na tablicy/)).toBeNull();
  });

  it("klik karty otwiera dok, Escape go zamyka", async () => {
    renderBoard(dockColumns());
    const link = await screen.findByRole("link", { name: "Aleksandra Nowakowska" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    expect(
      await screen.findByRole("complementary", { name: "Panel osoby" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(
        screen.queryByRole("complementary", { name: "Panel osoby" }),
      ).toBeNull(),
    );
  });

  it("zwykły klik w nazwisko otwiera dok, nie profil; Ctrl/⌘-klik zostawia link przeglądarce", async () => {
    renderBoard(dockColumns());
    const link = await screen.findByRole("link", { name: "Aleksandra Nowakowska" });
    // Prawdziwy adres zostaje — nowa karta, czytniki ekranu, „Kopiuj link".
    expect(link.getAttribute("href")).toMatch(/^\/candidates\/90\?/);

    // Ctrl-klik: przeglądarka otwiera profil w nowej karcie, dok się nie otwiera.
    const ctrl = new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true });
    link.dispatchEvent(ctrl);
    expect(ctrl.defaultPrevented).toBe(false);
    expect(screen.queryByRole("complementary", { name: "Panel osoby" })).toBeNull();

    // Zwykły klik: bez nawigacji (preventDefault), otwiera dok osoby.
    const plain = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(plain);
    expect(plain.defaultPrevented).toBe(true);
    expect(
      await screen.findByRole("complementary", { name: "Panel osoby" }),
    ).toBeInTheDocument();
  });

  it("Escape przy otwartym dialogu nie zamyka doku", async () => {
    renderBoard(dockColumns());
    const link = await screen.findByRole("link", { name: "Aleksandra Nowakowska" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    await screen.findByRole("complementary", { name: "Panel osoby" });

    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.appendChild(dialog);
    try {
      fireEvent.keyDown(window, { key: "Escape" });
      expect(
        screen.getByRole("complementary", { name: "Panel osoby" }),
      ).toBeInTheDocument();
    } finally {
      dialog.remove();
    }
  });

  it("initialDockCandidateId otwiera dok tej osoby i prosi stronę o zdjęcie parametru", async () => {
    const onHandled = vi.fn();
    const scrollIntoView = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={dockColumns()}
            jobId={10}
            initialDockCandidateId={90}
            onInitialDockHandled={onHandled}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );

    const dock = await screen.findByRole("complementary", { name: "Panel osoby" });
    expect(within(dock).getByText("Aleksandra Nowakowska")).toBeInTheDocument();
    expect(onHandled).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalled();
    scrollIntoView.mockRestore();
  });

  it("zgłasza stronie, kto jest w doku — „Tabela” otwiera potem tę osobę w panelu", async () => {
    const onDockCandidateChange = vi.fn();
    const scrollIntoView = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={dockColumns()}
            jobId={10}
            initialDockCandidateId={90}
            onDockCandidateChange={onDockCandidateChange}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await screen.findByRole("complementary", { name: "Panel osoby" });
    expect(onDockCandidateChange).toHaveBeenNthCalledWith(1, null);
    expect(onDockCandidateChange).toHaveBeenLastCalledWith(90);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(onDockCandidateChange).toHaveBeenLastCalledWith(null));
    scrollIntoView.mockRestore();
  });

  it("initialDockCandidateId spoza tablicy nie otwiera doku, ale i tak zdejmuje parametr", async () => {
    const onHandled = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={dockColumns()}
            jobId={10}
            initialDockCandidateId={12345}
            onInitialDockHandled={onHandled}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );

    await screen.findByTestId("pipeline-board");
    await waitFor(() => expect(onHandled).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByRole("complementary", { name: "Panel osoby" }),
    ).toBeNull();
  });
});


// ── Przełącznik widoku: kafelki ↔ kolumny (decyzja Artura 20.09.2026) ────────
//
// Tryb kafelkowy (karty degradowane do ~25 px, żeby cały szablon zmieścił się
// bez przewijania) ZOSTAJE, ale jako wybór użytkownika. Reguła automatyczna —
// szablon szerszy niż `OVERVIEW_COLUMN_THRESHOLD` otwiera się kafelkowo — jest
// tylko WARTOŚCIĄ DOMYŚLNĄ.
//
// To jedyna warstwa, która to łapie: usterka #1604 (odznaka screeningu na
// `absolute bottom-1 right-1` przykrywająca „następną akcję") przeszła przez
// komplet zielonych testów, bo układu karty nikt nie asercjonował.
describe("KanbanBoardV2 — przełącznik widoku tablicy", () => {
  /** `n` kolumn, każda z jedną kartą (pustych nie ukrywamy w tych testach). */
  function wideColumns(n: number) {
    return Array.from({ length: n }, (_, i) => ({
      stage: "new",
      name: `Etap ${i + 1}`,
      category: "internal",
      stage_def_id: 900 + i,
      count: 1,
      items: [
        {
          id: 7000 + i,
          candidate_id: 7000 + i,
          name: "Kandydat",
          lastname: `Nr${i + 1}`,
          stage: "new",
          days_in_stage: 1,
          verification_status: "active",
        },
      ],
    })) as never;
  }

  function renderWide(n: number) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={wideColumns(n)} jobId={10} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
  }

  const toggle = () => screen.queryByRole("group", { name: "Widok tablicy" });
  const tiles = () => screen.getByRole("button", { name: "Widok przeglądowy" });
  const columns = () => screen.getByRole("button", { name: "Widok kolumnowy" });

  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    get.mockImplementation(() =>
      Promise.resolve({
        data: { effective_budget_hourly: null, pipeline_template_id: null },
      }),
    );
  });

  it("szeroki szablon startuje w widoku przeglądowym, bez zapisanej preferencji", async () => {
    renderWide(12);
    await screen.findByTestId("pipeline-board");

    expect(toggle()).toBeInTheDocument();
    expect(tiles()).toHaveAttribute("aria-pressed", "true");
    expect(columns()).toHaveAttribute("aria-pressed", "false");
  });

  it("kliknięcie „Kolumny” przełącza widok i zapisuje wybór", async () => {
    renderWide(12);
    await screen.findByTestId("pipeline-board");

    await userEvent.click(columns());

    expect(columns()).toHaveAttribute("aria-pressed", "true");
    expect(tiles()).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(KANBAN_VIEW_MODE_STORAGE_KEY)).toBe("columns");
  });

  it("wybór przeżywa przemontowanie — reguła automatyczna go nie nadpisuje", async () => {
    const first = renderWide(12);
    await screen.findByTestId("pipeline-board");
    await userEvent.click(columns());
    first.unmount();

    renderWide(12);
    await screen.findByTestId("pipeline-board");

    expect(columns()).toHaveAttribute("aria-pressed", "true");
  });

  it("wąski szablon nie ma przełącznika — kafelki dałyby tam tylko mniejsze karty", async () => {
    renderWide(4);
    await screen.findByTestId("pipeline-board");

    expect(toggle()).toBeNull();
  });

  it("zapamiętane kafelki NIE wracają na wąskim szablonie — byłby to stan bez wyjścia", async () => {
    window.localStorage.setItem(KANBAN_VIEW_MODE_STORAGE_KEY, "tiles");
    renderWide(4);
    await screen.findByTestId("pipeline-board");

    // Przełącznika nie ma, więc nie ma czym wyjść z kafelków — widok musi być
    // kolumnowy. Preferencja zostaje zapisana i wróci na szerokim szablonie.
    expect(toggle()).toBeNull();
    expect(window.localStorage.getItem(KANBAN_VIEW_MODE_STORAGE_KEY)).toBe("tiles");
  });
});

describe("KanbanBoardV2 — „Rozwiń”: pełne narzędzia w tym samym panelu (04.10.2026)", () => {
  const ctx = { clientId: 3, clientName: "Bank Alfa", onMoved: vi.fn(), canCloseJob: false };
  const query = { isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  function renderWithWorkbench(
    initialWorkbench: { candidateId: number; section: "cv" | "interviews" } | null = null,
    columns: unknown = pendingColumns(),
  ) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={columns as never}
            jobId={10}
            workbenchContext={ctx}
            kanbanQueryState={query}
            initialWorkbench={initialWorkbench}
            onInitialWorkbenchHandled={vi.fn()}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
  }

  it("„Rozwiń” poszerza panel, pokazuje narzędzia zamiast sekcji; Esc zwija bez utraty tekstu", async () => {
    renderWithWorkbench();
    const link = await screen.findByRole("link", { name: "Anna Kowalska" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    const panel = await screen.findByRole("complementary", { name: "Panel osoby" });
    const note = within(panel).getByPlaceholderText(/Dodaj notatkę/);
    await userEvent.type(note, "Oddzwonić");

    await userEvent.click(within(panel).getByRole("button", { name: "Rozwiń" }));
    expect(panel).toHaveAttribute("data-wide");
    const tools = screen.getByTestId("person-workbench-stub");
    // „Zweryfikowany” otwiera zakładkę CV — z dużym podglądem po lewej (D6).
    expect(tools).toHaveAttribute("data-section", "cv");
    expect(panel).toHaveAttribute("data-size", "split");
    expect(screen.getByTestId("dock-sections")).not.toBeVisible();
    await userEvent.type(screen.getByLabelText("pole warsztatu"), "215 zł/h");

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(panel).not.toHaveAttribute("data-wide"));
    expect(screen.getByTestId("dock-sections")).toBeVisible();
    // Ten sam węzeł pola: sama wartość wróciłaby też ze szkicu po odmontowaniu.
    expect(within(panel).getByPlaceholderText(/Dodaj notatkę/)).toBe(note);
    expect(note).toHaveValue("Oddzwonić");

    await userEvent.click(within(panel).getByRole("button", { name: "Rozwiń" }));
    expect(screen.getByLabelText("pole warsztatu")).toHaveValue("215 zł/h");
  });

  it("Esc zamyka najpierw duże okno notatki — rozwinięcie i panel zostają", async () => {
    renderWithWorkbench();
    const link = await screen.findByRole("link", { name: "Anna Kowalska" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    const panel = await screen.findByRole("complementary", { name: "Panel osoby" });
    fireEvent.click(within(panel).getByRole("button", { name: "Rozwiń" }));
    const note = within(panel).getByPlaceholderText(/Dodaj notatkę/);
    // `fireEvent`, nie pisanie znak po znaku: test sprawdza warstwy Esc, a ciężka
    // tablica na wolnym runnerze nie mieści dziewięciu klawiszy w limicie testu.
    fireEvent.change(note, { target: { value: "Oddzwonić" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Powiększ pole notatki" }));
    expect(screen.getByTestId("dock-body")).not.toBeVisible();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.getByTestId("dock-body")).toBeVisible());
    expect(panel).toHaveAttribute("data-wide");
    expect(note).toHaveValue("Oddzwonić");

    // Drugi Esc działa jak dotąd: zwija rozwinięte narzędzia.
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(panel).not.toHaveAttribute("data-wide"));
  });

  it("stary link `?candidate=&panel=` otwiera panel od razu rozwinięty na zakładce", async () => {
    renderWithWorkbench({ candidateId: 5, section: "interviews" });
    const panel = await screen.findByRole("complementary", { name: "Panel osoby" });
    await waitFor(() => expect(panel).toHaveAttribute("data-wide"));
    expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-section", "interviews");
    // Każda zakładka ma podgląd po lewej (09.10.2026): panel nie zmienia
    // szerokości, więc pasek zakładek nie przesuwa się w bok.
    expect(panel).toHaveAttribute("data-size", "split");
    await userEvent.click(screen.getByRole("button", { name: "zakładka umowa" }));
    await waitFor(() =>
      expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-section", "contract"),
    );
    expect(panel).toHaveAttribute("data-size", "split");
    expect(screen.getByTestId("person-panel-side")).toBeVisible();
  });

  it.each([
    ["krzyżyk doku", (panel: HTMLElement) => userEvent.click(within(panel).getByRole("button", { name: "Zamknij dok" }))],
    ["„Zwiń”", (panel: HTMLElement) => userEvent.click(within(panel).getByRole("button", { name: "Zwiń" }))],
  ])("okno „Przesuń dalej”, z którego rozwinięto panel, wraca po wyjściu: %s", async (_label, leave) => {
    // Bramki pól dotyczą rekrutera — admin i DL przesuwają mimo braków (22.10.2026).
    useAuthStore.setState({ user: { id: 1, role: "recruiter", roles: ["recruiter"] } } as never);
    get.mockImplementation((url: string) =>
      url === "/api/pipeline/move-requirements"
        ? Promise.resolve({
            data: {
              from_column: "verified",
              to_column: "cv_qc",
              skipped_columns: [],
              items: [
                {
                  key: "company_cv",
                  label: "CV firmowe",
                  status: "missing",
                  blocking: true,
                  action: { kind: "generate_cv", label: "Wygeneruj CV" },
                },
              ],
              primary: { kind: "move", label: "Przesuń dalej" },
              owner_note: null,
            },
          })
        : Promise.resolve({ data: {} }),
    );
    renderWithWorkbench(null, [
      {
        stage: "verified",
        name: "Zweryfikowany",
        category: "internal",
        stage_def_id: 13,
        count: 1,
        // Bez CV firmowego strzałka otwiera okno (znany brak, 14.10.2026).
        items: [
          { id: 777, candidate_id: 5, name: "Anna", lastname: "Kowalska", stage: "verified", days_in_stage: 1, company_cv: false },
        ],
      },
      { stage: "interview", name: "QC CV", category: "internal", stage_def_id: 14, count: 0, items: [] },
    ]);
    const card = (await screen.findByRole("link", { name: "Anna Kowalska" })).closest(
      "[data-kanban-card]",
    ) as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: /Przesuń Anna Kowalska na następny etap/ }));
    const dialog = await screen.findByTestId("move-next-dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Wygeneruj CV" }));
    await waitFor(() => expect(screen.queryByTestId("move-next-dialog")).toBeNull());
    const panel = await screen.findByRole("complementary", { name: "Panel osoby" });
    await waitFor(() => expect(panel).toHaveAttribute("data-wide"));
    expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-section", "cv");

    await leave(panel);
    expect(await screen.findByTestId("move-next-dialog")).toBeTruthy();
  });

  it("klik w osobę z „Nowych” otwiera panel szeroki (split) od razu na formularzu screeningu (0424)", async () => {
    renderWithWorkbench(null, [
      {
        stage: "new",
        name: "Nowi",
        category: "internal",
        stage_def_id: 11,
        count: 1,
        items: [{ id: 701, candidate_id: 7, name: "Tomasz", lastname: "Wzorcowy", stage: "new", days_in_stage: 1 }],
      },
      {
        stage: "verified",
        name: "Zweryfikowany",
        category: "internal",
        stage_def_id: 13,
        count: 1,
        items: [{ id: 777, candidate_id: 5, name: "Anna", lastname: "Kowalska", stage: "verified", days_in_stage: 1 }],
      },
    ]);
    const card = (await screen.findByRole("link", { name: "Tomasz Wzorcowy" })).closest(
      "[data-kanban-card]",
    ) as HTMLElement;
    fireEvent.click(card);
    const panel = await screen.findByRole("complementary", { name: "Panel osoby" });
    await waitFor(() => expect(panel).toHaveAttribute("data-size", "split"));
    expect(panel).toHaveAttribute("data-wide");
    expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-section", "screening");

    // „Zwiń” wraca do zwykłego doku osoby.
    await userEvent.click(within(panel).getByRole("button", { name: "Zwiń" }));
    await waitFor(() => expect(panel).toHaveAttribute("data-size", "dock"));
    expect(panel).not.toHaveAttribute("data-wide");

    // Osoba spoza „Nowych”/„Screeningu” otwiera zwykły dok.
    fireEvent.click(
      (await screen.findByRole("link", { name: "Anna Kowalska" })).closest("[data-kanban-card]") as HTMLElement,
    );
    await waitFor(() => expect(panel).toHaveAttribute("data-size", "dock"));
  });

  it("bez kontekstu warsztatów (harness) panel nie ma „Rozwiń”", async () => {
    renderBoard();
    const link = await screen.findByRole("link", { name: "Anna Kowalska" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    const panel = await screen.findByRole("complementary", { name: "Panel osoby" });
    expect(within(panel).queryByRole("button", { name: "Rozwiń" })).toBeNull();
  });
});

// Prośba rekrutera (13.10.2026, D1–D4): po „Odrzuć z powodem” i „Zrezygnował”
// z panelu osoby panel pokazuje osobę, która stała za zamkniętą w kolejności
// strzałki „›”. Do tej daty zostawał na odrzuconej osobie bez „‹ N z M ›”.
describe("KanbanBoardV2 — po zamknięciu osoby z panelu następna osoba (13.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: { id: 1, role: "admin" } } as never);
  });

  const moveCalls = () => post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");

  const person = (id: number, stage: string, name: string, lastname: string) => ({
    id: 900 + id,
    candidate_id: id,
    stage,
    name,
    lastname,
    days_in_stage: 2,
  });

  function closingColumns() {
    return [
      {
        stage: "new",
        name: "Nowi / Analiza CV",
        category: "internal",
        stage_def_id: 501,
        count: 2,
        terminal_type: null,
        items: [person(61, "new", "Michał", "Zieliński"), person(62, "new", "Anna", "Wiśniewska")],
      },
      {
        stage: "screening",
        name: "Screening",
        category: "internal",
        stage_def_id: 502,
        count: 1,
        terminal_type: null,
        items: [person(63, "screening", "Tomasz", "Wójcik")],
      },
      {
        stage: "verified",
        name: "Zweryfikowany",
        category: "internal",
        stage_def_id: 503,
        count: 0,
        terminal_type: null,
        items: [],
      },
      {
        stage: "rejected",
        name: "Odrzucony",
        category: "terminal",
        stage_def_id: 508,
        count: 0,
        terminal_type: "rejected",
        items: [],
      },
      {
        stage: "withdrawn",
        name: "Wycofany",
        category: "terminal",
        stage_def_id: 509,
        count: 0,
        terminal_type: "withdrawn",
        items: [],
      },
    ] as never;
  }

  async function openPerson(name: string) {
    const link = await screen.findByRole("link", { name });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    return screen.findByRole("complementary", { name: "Panel osoby" });
  }

  async function confirmClosing(dialog: HTMLElement, reason = "Brak Azure") {
    fireEvent.change(within(dialog).getByPlaceholderText(/brak wymaganych kompetencji/), {
      target: { value: reason },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Potwierdź" }));
  }

  it("po „Potwierdź” panel pokazuje następną osobę z kolejności „›” i pasek „Odrzucono”", async () => {
    renderBoard(closingColumns());
    const panel = await openPerson("Michał Zieliński");
    // Od 14.10.2026 kolejka to kolumna osoby — „Nowi” (2), bez Screeningu.
    expect(within(panel).getByText("1 z 2")).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: /Odrzuć z powodem/ }));
    const dialog = await screen.findByRole("dialog");
    // Okno mówi, kogo odrzucasz i kto będzie następny.
    expect(within(dialog).getByText("Michał Zieliński · Nowi")).toBeInTheDocument();
    expect(within(dialog).getByText("Dalej: Anna Wiśniewska · Nowi")).toBeInTheDocument();
    await confirmClosing(dialog);

    await waitFor(() => expect(within(panel).getByText("1 z 1")).toBeInTheDocument());
    expect(within(panel).getAllByText("Anna Wiśniewska").length).toBeGreaterThan(0);
    const notice = within(panel).getByRole("status", { name: "Poprzednia osoba" });
    expect(notice).toHaveTextContent("Odrzucono: Michał Zieliński · Brak Azure");
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: 61, stage_def_id: 508 });

    // „Pokaż” wraca do odrzuconej osoby, „Wróć do kolejki” — do następnej.
    fireEvent.click(within(notice).getByRole("button", { name: "Pokaż" }));
    await waitFor(() => expect(within(panel).getAllByText("Michał Zieliński").length).toBeGreaterThan(0));
    fireEvent.click(within(panel).getByRole("button", { name: "Wróć do kolejki" }));
    await waitFor(() => expect(within(panel).getByText("1 z 1")).toBeInTheDocument());
    expect(within(panel).getAllByText("Anna Wiśniewska").length).toBeGreaterThan(0);
  });

  it("pasek znika po przejściu do innej osoby", async () => {
    renderBoard(closingColumns());
    const panel = await openPerson("Michał Zieliński");
    fireEvent.click(within(panel).getByRole("button", { name: /Odrzuć z powodem/ }));
    await confirmClosing(await screen.findByRole("dialog"));
    await within(panel).findByRole("status", { name: "Poprzednia osoba" });

    // Anna jest jedyna w „Nowych” — rekruter przechodzi kartą do Screeningu.
    const other = await openPerson("Tomasz Wójcik");
    await waitFor(() => expect(within(other).getAllByText("Tomasz Wójcik").length).toBeGreaterThan(0));
    expect(within(other).getByText("1 z 1")).toBeInTheDocument();
    expect(within(other).getByTestId("dock-queue-label")).toHaveTextContent("Screening");
    expect(within(other).queryByRole("status", { name: "Poprzednia osoba" })).toBeNull();
  });

  it("„Zrezygnował” też przechodzi dalej, pasek mówi „Rezygnacja”", async () => {
    renderBoard(closingColumns());
    const panel = await openPerson("Michał Zieliński");
    fireEvent.click(within(panel).getByRole("button", { name: "Zrezygnował" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Dalej: Anna Wiśniewska · Nowi")).toBeInTheDocument();
    await confirmClosing(dialog, "Przyjął inną ofertę");

    const notice = await within(panel).findByRole("status", { name: "Poprzednia osoba" });
    expect(notice).toHaveTextContent("Rezygnacja: Michał Zieliński · Przyjął inną ofertę");
    expect(within(panel).getByText("1 z 1")).toBeInTheDocument();
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: 61, stage_def_id: 509 });
  });

  it("ostatnia osoba w kolejności: okno to zapowiada, panel się zamyka, komunikat ma „Pokaż”", async () => {
    renderBoard(closingColumns());
    const panel = await openPerson("Tomasz Wójcik");
    expect(within(panel).getByText("1 z 1")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: /Odrzuć z powodem/ }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("To ostatnia osoba w kolejce — panel się zamknie."),
    ).toBeInTheDocument();
    await confirmClosing(dialog);

    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Panel osoby" })).toBeNull(),
    );
    expect(toastAction).toHaveBeenCalledTimes(1);
    const [message, options] = toastAction.mock.calls[0];
    expect(message).toBe("Odrzucono: Tomasz Wójcik. To była ostatnia osoba w kolejce „Screening”.");
    expect(options.actionLabel).toBe("Pokaż");
    act(() => {
      options.onAction();
    });
    const back = await screen.findByRole("complementary", { name: "Panel osoby" });
    expect(within(back).getAllByText("Tomasz Wójcik").length).toBeGreaterThan(0);
  });

  it("ostatnia osoba w „Nowych” zamyka panel — przejście nie wchodzi do Screeningu (D1, 14.10.2026)", async () => {
    renderBoard(closingColumns());
    const panel = await openPerson("Anna Wiśniewska");
    expect(within(panel).getByText("2 z 2")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: /Odrzuć z powodem/ }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("To ostatnia osoba w kolejce — panel się zamknie."),
    ).toBeInTheDocument();
    await confirmClosing(dialog);

    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Panel osoby" })).toBeNull(),
    );
    expect(toastAction.mock.calls[0][0]).toBe(
      "Odrzucono: Anna Wiśniewska. To była ostatnia osoba w kolejce „Nowi”.",
    );
  });

  it("odmowa serwera (ktoś inny zmienił kartę) zostawia panel na tej samej osobie, bez paska", async () => {
    post.mockRejectedValueOnce({
      response: { status: 409, data: { detail: { code: PIPELINE_VERSION_CONFLICT_CODE } } },
    });
    renderBoard(closingColumns());
    const panel = await openPerson("Michał Zieliński");
    fireEvent.click(within(panel).getByRole("button", { name: /Odrzuć z powodem/ }));
    await confirmClosing(await screen.findByRole("dialog"));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(within(panel).getAllByText("Michał Zieliński").length).toBeGreaterThan(0);
    expect(within(panel).queryByRole("status", { name: "Poprzednia osoba" })).toBeNull();
    expect(within(panel).queryAllByText("Anna Wiśniewska")).toHaveLength(0);
  });

  it("ostrzeżenie serwera: przejście dopiero po „Przenieś mimo to” i udanym ruchu", async () => {
    post
      .mockRejectedValueOnce({
        response: {
          status: 409,
          data: {
            detail: {
              code: "ELIGIBILITY_WARNING",
              reason_code: "blacklist",
              reason: "Kandydat jest na czarnej liście klienta.",
              message: "Kandydat jest na czarnej liście klienta.",
              can_acknowledge: true,
            },
          },
        },
      })
      .mockResolvedValueOnce({ data: { id: 1961 } });
    // Po ostrzeżeniu tablica dociąga prawdę serwera — Michał dalej w „Nowych”.
    kanban.mockResolvedValue({ data: { columns: closingColumns(), off_template: null } });
    renderBoard(closingColumns());
    const panel = await openPerson("Michał Zieliński");
    fireEvent.click(within(panel).getByRole("button", { name: /Odrzuć z powodem/ }));
    await confirmClosing(await screen.findByRole("dialog"));

    const warning = await screen.findByRole("dialog");
    expect(within(warning).getByText("Kandydat jest na czarnej liście klienta.")).toBeInTheDocument();
    // Okno ostrzeżenia dotyczy jeszcze Michała.
    expect(within(panel).getAllByText("Michał Zieliński").length).toBeGreaterThan(0);
    expect(within(panel).queryByRole("status", { name: "Poprzednia osoba" })).toBeNull();

    fireEvent.click(within(warning).getByRole("button", { name: "Przenieś mimo to" }));
    const notice = await within(panel).findByRole("status", { name: "Poprzednia osoba" });
    expect(notice).toHaveTextContent("Odrzucono: Michał Zieliński");
    // Atrapa serwera po ruchu dalej zwraca Michała w „Nowych”, więc liczymy osobę, nie licznik.
    expect(within(panel).getAllByText("Anna Wiśniewska").length).toBeGreaterThan(0);
  });

  it("panel przeniesiony na inną osobę w trakcie ruchu nie skacze", async () => {
    let resolveMove: (value: unknown) => void = () => {};
    post.mockImplementationOnce(() => new Promise((resolve) => (resolveMove = resolve)));
    renderBoard(closingColumns());
    const panel = await openPerson("Michał Zieliński");
    fireEvent.click(within(panel).getByRole("button", { name: /Odrzuć z powodem/ }));
    await confirmClosing(await screen.findByRole("dialog"));
    await waitFor(() => expect(moveCalls()).toHaveLength(1));

    // Zanim serwer odpowie, rekruter otwiera kogoś innego.
    const other = await openPerson("Tomasz Wójcik");
    await act(async () => {
      resolveMove({ data: { id: 1962 } });
    });
    expect(within(other).getAllByText("Tomasz Wójcik").length).toBeGreaterThan(0);
    expect(within(other).queryByRole("status", { name: "Poprzednia osoba" })).toBeNull();
  });
});

describe("KanbanBoardV2 — „Rozwiń”: po odrzuceniu widok zostaje jak po „›” (13.10.2026)", () => {
  const ctx = { clientId: 3, clientName: "Bank Alfa", onMoved: vi.fn(), canCloseJob: false };
  const query = { isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("następna osoba z „Nowych” zostaje przy formularzu; „Dalej: Zweryfikowany” otwiera zwykły dok", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={[
              {
                stage: "new",
                name: "Nowi",
                category: "internal",
                stage_def_id: 11,
                count: 2,
                items: [
                  { id: 701, candidate_id: 7, name: "Michał", lastname: "Zieliński", stage: "new", days_in_stage: 1 },
                  { id: 702, candidate_id: 8, name: "Anna", lastname: "Wiśniewska", stage: "new", days_in_stage: 1 },
                ],
              },
              {
                stage: "verified",
                name: "Zweryfikowany",
                category: "internal",
                stage_def_id: 13,
                count: 1,
                items: [{ id: 777, candidate_id: 5, name: "Marta", lastname: "Lis", stage: "verified", days_in_stage: 1 }],
              },
              {
                stage: "rejected",
                name: "Odrzucony",
                category: "terminal",
                stage_def_id: 18,
                count: 0,
                terminal_type: "rejected",
                items: [],
              },
            ] as never}
            jobId={10}
            workbenchContext={ctx}
            kanbanQueryState={query}
            onInitialWorkbenchHandled={vi.fn()}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    const card = (await screen.findByRole("link", { name: "Michał Zieliński" })).closest(
      "[data-kanban-card]",
    ) as HTMLElement;
    fireEvent.click(card);
    const panel = await screen.findByRole("complementary", { name: "Panel osoby" });
    await waitFor(() => expect(panel).toHaveAttribute("data-size", "split"));

    const reject = async () => {
      fireEvent.click(within(panel).getByRole("button", { name: /Odrzuć z powodem/ }));
      const dialog = await screen.findByRole("dialog");
      fireEvent.change(within(dialog).getByPlaceholderText(/brak wymaganych kompetencji/), {
        target: { value: "Brak Azure" },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Potwierdź" }));
    };

    await reject();
    await waitFor(() =>
      expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-candidate", "8"),
    );
    expect(panel).toHaveAttribute("data-size", "split");
    expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-section", "screening");

    // Anna jest ostatnia w kolejce „Nowi” — odrzucenie nie przeskoczy do
    // innej kolumny (D1), ale pasek końca kolejki prowadzi dalej (D4).
    const end = within(panel).getByRole("status", { name: "Koniec kolejki" });
    expect(end).toHaveTextContent("To jedyna osoba w kolejce.");
    fireEvent.click(within(end).getByRole("button", { name: /Dalej: Zweryfikowany \(1\)/ }));
    await waitFor(() => expect(panel).toHaveAttribute("data-size", "dock"));
    expect(within(panel).getAllByText("Marta Lis").length).toBeGreaterThan(0);
    expect(within(panel).getByTestId("dock-queue-label")).toHaveTextContent("Zweryfikowany");
  });
});

describe("KanbanBoardV2 — „Odrzuć” w formularzu screeningu też przenosi panel (13.10.2026)", () => {
  const ctx = { clientId: 3, clientName: "Bank Alfa", onMoved: vi.fn(), canCloseJob: false };
  const query = { isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("po udanym odrzuceniu z formularza panel pokazuje następną osobę z „Nowych” z paskiem", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={[
              {
                stage: "new",
                name: "Nowi",
                category: "internal",
                stage_def_id: 11,
                count: 2,
                items: [
                  { id: 701, candidate_id: 7, name: "Michał", lastname: "Zieliński", stage: "new", days_in_stage: 1 },
                  { id: 702, candidate_id: 8, name: "Anna", lastname: "Wiśniewska", stage: "new", days_in_stage: 1 },
                ],
              },
              {
                stage: "rejected",
                name: "Odrzucony",
                category: "terminal",
                stage_def_id: 18,
                count: 0,
                terminal_type: "rejected",
                items: [],
              },
            ] as never}
            jobId={10}
            workbenchContext={ctx}
            kanbanQueryState={query}
            onInitialWorkbenchHandled={vi.fn()}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(
      (await screen.findByRole("link", { name: "Michał Zieliński" })).closest("[data-kanban-card]") as HTMLElement,
    );
    const panel = await screen.findByRole("complementary", { name: "Panel osoby" });
    await waitFor(() => expect(panel).toHaveAttribute("data-size", "split"));

    fireEvent.click(screen.getByRole("button", { name: "formularz: odrzucono" }));
    await waitFor(() =>
      expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-candidate", "8"),
    );
    expect(panel).toHaveAttribute("data-size", "split");
    expect(within(panel).getByRole("status", { name: "Poprzednia osoba" })).toHaveTextContent(
      "Odrzucono: Michał Zieliński · Brak Azure",
    );
  });
});

// ── Strzałka „→” bez okna z „Cofnij” i odznaki CV (D7, 14.10.2026) ─────────
describe("KanbanBoardV2 — strzałka „→”: ruch od razu z „Cofnij” (14.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: { id: 1, role: "admin" } } as never);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const moveCalls = () => post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");
  const columnOf = (container: HTMLElement, id: number) =>
    container.querySelector(`[data-candidate-id="${id}"]`)?.closest("[data-colid]")?.getAttribute("data-colid");

  async function clickArrow(name: string) {
    const card = (await screen.findByRole("link", { name })).closest("[data-kanban-card]") as HTMLElement;
    vi.useFakeTimers();
    fireEvent.click(within(card).getByRole("button", { name: new RegExp(`Przesuń ${name} na następny etap`) }));
  }

  it("z „Nowych” na „Screening”: bez okna, karta od razu w Screeningu, żądanie po 10 s", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    // „Nowi / Analiza CV” — pierwsza karta (2000).
    await clickArrow("Kandydat Nowi /0");
    expect(screen.queryByTestId("move-next-dialog")).toBeNull();
    expect(columnOf(container, 2000)).toBe("def:301");
    expect(toastAction).toHaveBeenCalledWith(
      "Kandydat Nowi /0 → Screening",
      expect.objectContaining({ actionLabel: "Cofnij", durationMs: 10_000 }),
    );
    expect(moveCalls()).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(moveCalls()).toHaveLength(1);
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: 2000, stage: "screening", stage_def_id: 301 });
  });

  it("przesunięta karta staje na górze kolumny docelowej, nie na dole (16.10.2026)", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await clickArrow("Kandydat Nowi /0");
    const inScreening = Array.from(
      new Set(
        Array.from(container.querySelectorAll('[data-colid="def:301"] [data-candidate-id]')).map((el) =>
          Number(el.getAttribute("data-candidate-id")),
        ),
      ),
    );
    expect(inScreening).toEqual([2000, 2100]);
  });

  it("„Cofnij” wraca kartę na miejsce bez żadnego żądania", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await clickArrow("Kandydat Nowi /0");
    const onAction = toastAction.mock.calls[0][1].onAction as () => void;
    act(() => onAction());
    expect(columnOf(container, 2000)).toBe("def:300");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(moveCalls()).toHaveLength(0);
  });

  it("zamknięcie Tablicy przed upływem 10 s wysyła ruch od razu", async () => {
    const { unmount } = renderBoard(defaultB2BColumns());
    await clickArrow("Kandydat Nowi /0");
    expect(moveCalls()).toHaveLength(0);
    unmount();
    expect(moveCalls()).toHaveLength(1);
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: 2000, stage: "screening" });
  });

  it("otwarcie tej osoby w panelu wysyła odłożony ruch od razu (panel czyta stan z serwera)", async () => {
    renderBoard(defaultB2BColumns());
    await clickArrow("Kandydat Nowi /0");
    expect(moveCalls()).toHaveLength(0);
    vi.useRealTimers();
    fireEvent.click(document.querySelector('[data-candidate-id="2000"]') as HTMLElement);
    await waitFor(() => expect(moveCalls()).toHaveLength(1));
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: 2000, stage: "screening" });
  });

  it("odświeżenie tablicy w ciągu 10 s nie cofa karty", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = (columns: unknown) => (
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={columns as never} jobId={10} />
        </TooltipProvider>
      </QueryClientProvider>
    );
    const { container, rerender } = render(view(defaultB2BColumns()));
    await clickArrow("Kandydat Nowi /0");
    // Nowa odpowiedź serwera (np. po innym ruchu) — serwer jeszcze nie wie o strzałce.
    rerender(view(defaultB2BColumns()));
    expect(columnOf(container, 2000)).toBe("def:301");
  });

  it("ze „Zweryfikowanego” bez CV firmowego strzałka otwiera „Przesuń dalej” (znany brak)", async () => {
    // Bramki pól dotyczą rekrutera — admin i DL przesuwają mimo braków (22.10.2026).
    useAuthStore.setState({ user: { id: 1, role: "recruiter", roles: ["recruiter"] } } as never);
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[2] = {
      ...columns[2],
      count: 1,
      items: [
        { id: 7201, candidate_id: 8201, stage: "verified", name: "Olek", lastname: "Bezcv", days_in_stage: 1, company_cv: false },
      ],
    };
    renderBoard(columns as never);
    const card = (await screen.findByRole("link", { name: "Olek Bezcv" })).closest("[data-kanban-card]") as HTMLElement;
    const arrow = within(card).getByRole("button", { name: /Przesuń Olek Bezcv na następny etap/ });
    expect(arrow).toHaveAttribute("data-gap", "true");
    expect(arrow).toHaveAttribute("title", expect.stringContaining("Brak CV firmowego"));
    fireEvent.click(arrow);
    expect(await screen.findByTestId("move-next-dialog")).toBeTruthy();
    expect(toastAction).not.toHaveBeenCalled();
    expect(moveCalls()).toHaveLength(0);
  });

  it("„Zweryfikowany” ze stawką etapu ze Screeningu: strzałka bez okna stawki (D2)", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[1] = {
      ...columns[1],
      items: [
        {
          id: 1100,
          candidate_id: 2100,
          stage: "screening",
          name: "Kandydat",
          lastname: "Screen0",
          days_in_stage: 2,
          screening_done: true,
          expected_rate_value: "140.00",
          expected_rate_unit: "hourly",
          expected_rate_currency: "PLN",
        },
      ],
    };
    const { container } = renderBoard(columns as never);
    await clickArrow("Kandydat Screen0");
    expect(screen.queryByTestId("move-next-dialog")).toBeNull();
    expect(screen.queryByLabelText("Kwota")).toBeNull();
    expect(columnOf(container, 2100)).toBe("def:302");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(moveCalls()).toHaveLength(1);
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: 2100, stage: "verified" });
    expect(moveCalls()[0][1]).not.toHaveProperty("expected_rate_value");
  });

  it("brak samego minimum dla DL: strzałka otwiera okno z brakującymi polami, bez ruchu (21.10.2026)", async () => {
    // Bramki pól dotyczą rekrutera — admin i DL przesuwają mimo braków (22.10.2026).
    useAuthStore.setState({ user: { id: 1, role: "recruiter", roles: ["recruiter"] } } as never);
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[1] = {
      ...columns[1],
      items: [
        {
          id: 1101,
          candidate_id: 2101,
          stage: "screening",
          name: "Kandydat",
          lastname: "Minimum",
          days_in_stage: 2,
          screening_done: true,
          minimum_missing: ["location", "work_mode"],
          expected_rate_value: "140.00",
          expected_rate_unit: "hourly",
          expected_rate_currency: "PLN",
        },
      ],
    };
    const { container } = renderBoard(columns as never);
    const card = (await screen.findByRole("link", { name: "Kandydat Minimum" })).closest(
      "[data-kanban-card]",
    ) as HTMLElement;
    const arrow = within(card).getByRole("button", { name: /Przesuń Kandydat Minimum na następny etap/ });
    expect(arrow).toHaveAttribute("data-gap", "true");
    expect(arrow).toHaveAttribute("title", expect.stringContaining("Brak: lokalizacja, tryb pracy"));
    fireEvent.click(arrow);
    expect(await screen.findByText("Kandydat Minimum → Zweryfikowany")).toBeTruthy();
    expect(screen.queryByTestId("move-next-dialog")).toBeNull();
    // Karta stoi w „Screeningu” i nic nie idzie do serwera, dopóki pola nie są zapisane.
    expect(moveCalls()).toHaveLength(0);
    expect(columnOf(container, 2101)).toBe("def:301");
  });

  // 22.10.2026: Delivery Lead (i admin — to samo uprawnienie) przesuwa bez
  // bramek pól: strzałka nie jest szara, karta idzie od razu, a komunikat
  // wymienia braki. Stawki też nie pyta.
  it("Delivery Lead: strzałka ze Screeningu bez arkusza, stawki i minimum przesuwa od razu z brakami w komunikacie", async () => {
    useAuthStore.setState({
      user: { id: 1, role: "delivery_lead", roles: ["delivery_lead"], skips_fill_gates: true },
    } as never);
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[1] = {
      ...columns[1],
      items: [
        {
          id: 1102,
          candidate_id: 2102,
          stage: "screening",
          name: "Kandydat",
          lastname: "Dlowy",
          days_in_stage: 2,
          screening_done: false,
          minimum_missing: ["location"],
        },
      ],
    };
    const { container } = renderBoard(columns as never);
    const card = (await screen.findByRole("link", { name: "Kandydat Dlowy" })).closest(
      "[data-kanban-card]",
    ) as HTMLElement;
    const arrow = within(card).getByRole("button", { name: /Przesuń Kandydat Dlowy na następny etap/ });
    expect(arrow).toHaveAttribute("data-gap", "false");
    await clickArrow("Kandydat Dlowy");
    expect(screen.queryByTestId("move-next-dialog")).toBeNull();
    expect(screen.queryByLabelText("Kwota")).toBeNull();
    expect(columnOf(container, 2102)).toBe("def:302");
    expect(toastAction.mock.calls[0][0]).toBe(
      "Kandydat Dlowy → Zweryfikowany · bez: arkusza screeningu, stawki kandydata, lokalizacja",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(moveCalls()).toHaveLength(1);
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: 2102, stage: "verified" });
  });

  // Audyt 22.10.2026 (F109): wyłącznik `DL_SKIPS_FILL_GATES=false` działa też
  // na Tablicę — DL z uprawnieniem wysyłki ma szarą strzałkę i okno minimum,
  // jak przed #2581 (front czyta `skips_fill_gates` z `/api/auth/me`).
  it("Delivery Lead przy wyłączonym DL_SKIPS_FILL_GATES ma szarą strzałkę i okno minimum", async () => {
    useAuthStore.setState({
      user: { id: 1, role: "delivery_lead", roles: ["delivery_lead"], skips_fill_gates: false },
    } as never);
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[1] = {
      ...columns[1],
      items: [
        {
          id: 1103,
          candidate_id: 2103,
          stage: "screening",
          name: "Kandydat",
          lastname: "Wyłączony",
          days_in_stage: 2,
          screening_done: true,
          minimum_missing: ["location"],
          expected_rate_value: "140.00",
          expected_rate_unit: "hourly",
          expected_rate_currency: "PLN",
        },
      ],
    };
    const { container } = renderBoard(columns as never);
    const card = (await screen.findByRole("link", { name: "Kandydat Wyłączony" })).closest(
      "[data-kanban-card]",
    ) as HTMLElement;
    const arrow = within(card).getByRole("button", { name: /Przesuń Kandydat Wyłączony na następny etap/ });
    expect(arrow).toHaveAttribute("data-gap", "true");
    fireEvent.click(arrow);
    expect(await screen.findByText("Kandydat Wyłączony → Zweryfikowany")).toBeTruthy();
    expect(moveCalls()).toHaveLength(0);
    expect(columnOf(container, 2103)).toBe("def:301");
  });

  it("karta przesunięta przez DL mimo braków ma odznakę „Przesunął DL”", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[2] = {
      ...columns[2],
      count: 1,
      items: [
        {
          id: 7202,
          candidate_id: 8202,
          stage: "verified",
          name: "Ola",
          lastname: "Przeniesiona",
          days_in_stage: 0,
          requirements_skipped: ["screening_sheet", "candidate_rate"],
          requirements_skipped_by_name: "Anna Nowak",
        },
      ],
    };
    renderBoard(columns as never);
    const card = (await screen.findByRole("link", { name: "Ola Przeniesiona" })).closest(
      "[data-kanban-card]",
    ) as HTMLElement;
    expect(within(card).getByTestId("card-requirements-skipped")).toHaveTextContent(
      "Przesunął DL · bez arkusza i stawki",
    );
  });
});

describe("KanbanBoardV2 — stan CV na karcie „Zweryfikowanego” (14.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
  });

  it("w przygotowaniu, gotowe z liczbą do poprawy, gotowe bez uwag", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[2] = {
      ...columns[2],
      count: 3,
      items: [
        { id: 7301, candidate_id: 8301, stage: "verified", name: "Ala", lastname: "Pisze", days_in_stage: 1, auto_cv_state: "processing" },
        {
          id: 7302,
          candidate_id: 8302,
          stage: "verified",
          name: "Bartek",
          lastname: "Poprawki",
          days_in_stage: 1,
          company_cv: true,
          qc: { status: "failed", blocking_failed: 1, warnings_count: 1 },
        },
        {
          id: 7303,
          candidate_id: 8303,
          stage: "verified",
          name: "Celina",
          lastname: "Czysta",
          days_in_stage: 1,
          company_cv: true,
          qc: { status: "passed", blocking_failed: 0, warnings_count: 0 },
        },
      ],
    };
    renderBoard(columns as never);
    const badge = async (name: string) =>
      within((await screen.findByRole("link", { name })).closest("[data-kanban-card]") as HTMLElement).getByTestId(
        "card-cv-state",
      );
    expect(await badge("Ala Pisze")).toHaveTextContent("CV w przygotowaniu…");
    expect(await badge("Bartek Poprawki")).toHaveTextContent("CV gotowe · QC: 1 do poprawy · 1 uwaga");
    expect(await badge("Celina Czysta")).toHaveTextContent("CV gotowe · QC bez uwag");
  });
});

describe("KanbanBoardV2 — panel osoby: przekazanie dalej, następna w kolumnie, kanał notatki (14.10.2026)", () => {
  const ctx = { clientId: 3, clientName: "Bank Alfa", onMoved: vi.fn(), canCloseJob: false };
  const query = { isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  function renderPeople() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={[
              {
                stage: "new",
                name: "Nowi",
                category: "internal",
                stage_def_id: 11,
                count: 3,
                items: [
                  { id: 701, candidate_id: 7, name: "Michał", lastname: "Zieliński", stage: "new", days_in_stage: 1 },
                  { id: 702, candidate_id: 8, name: "Anna", lastname: "Wiśniewska", stage: "new", days_in_stage: 3 },
                  { id: 703, candidate_id: 9, name: "Ola", lastname: "Ostatnia", stage: "new", days_in_stage: 0 },
                ],
              },
            ] as never}
            jobId={10}
            workbenchContext={ctx}
            kanbanQueryState={query}
            onInitialWorkbenchHandled={vi.fn()}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
  }

  it("„następna w kolumnie” idzie za osobą w kolejności „›”, a „otwórz” pokazuje ją w panelu", async () => {
    renderPeople();
    fireEvent.click(
      (await screen.findByRole("link", { name: "Michał Zieliński" })).closest("[data-kanban-card]") as HTMLElement,
    );
    const stub = await screen.findByTestId("person-workbench-stub");
    expect(stub).toHaveAttribute("data-note-fill", "yes");
    const next = within(stub).getByRole("button", { name: "następna w Nowych: Anna Wiśniewska · czeka 3 dni" });
    fireEvent.click(next);
    await waitFor(() => expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-candidate", "8"));
    // Za ostatnią osobą — pierwsza od góry, nie ona sama.
    fireEvent.click(
      within(screen.getByTestId("person-workbench-stub")).getByRole("button", {
        name: "następna w Nowych: Ola Ostatnia · czeka od dziś",
      }),
    );
    await waitFor(() => expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-candidate", "9"));
    expect(
      within(screen.getByTestId("person-workbench-stub")).getByRole("button", {
        name: "następna w Nowych: Michał Zieliński · czeka 1 dzień",
      }),
    ).toBeTruthy();
  });

  it("„Zapisz i przekaż dalej” przenosi panel na „CV” i zapamiętuje osobę; inna osoba czyści znacznik", async () => {
    renderPeople();
    fireEvent.click(
      (await screen.findByRole("link", { name: "Michał Zieliński" })).closest("[data-kanban-card]") as HTMLElement,
    );
    const stub = await screen.findByTestId("person-workbench-stub");
    expect(stub).toHaveAttribute("data-section", "screening");
    fireEvent.click(within(stub).getByRole("button", { name: "formularz: przekazano" }));
    await waitFor(() => expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-section", "cv"));
    expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-forwarded", "7");

    fireEvent.click(
      within(screen.getByTestId("person-workbench-stub")).getByRole("button", { name: /następna w Nowych: Anna/ }),
    );
    await waitFor(() => expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-candidate", "8"));
    expect(screen.getByTestId("person-workbench-stub")).toHaveAttribute("data-forwarded", "");
  });
});

describe("KanbanBoardV2 — filtr „Kto dodał” i kolejka w kolumnie (D1–D5, 14.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({
      user: { id: 7, role: "recruiter", roles: ["recruiter"], name: "Tomasz Rybak" },
    } as never);
  });

  const ADDERS: Record<number, string> = { 7: "Tomasz Rybak", 8: "Paulina Wrona" };
  const person = (id: number, stage: string, name: string, lastname: string, by: number | null) => ({
    id: 900 + id,
    candidate_id: id,
    stage,
    name,
    lastname,
    days_in_stage: 2,
    added_to_job_by_id: by,
    added_to_job_by_name: by == null ? null : ADDERS[by],
  });
  const ADAM = person(41, "new", "Adam", "Nowak", 8);
  const BEATA = person(42, "new", "Beata", "Lis", 7);
  const CEZARY = person(43, "new", "Cezary", "Mróz", 8);
  const DOROTA = person(44, "new", "Dorota", "Wójcik", 7);
  const EMIL = person(45, "new", "Emil", "Bąk", null);
  const FILIP = person(46, "screening", "Filip", "Kos", 8);

  function boardColumns(nowi = [ADAM, BEATA, CEZARY, DOROTA, EMIL], screening = [FILIP]) {
    const col = (id: number, stage: string, name: string, items: unknown[], extra = {}) => ({
      stage,
      name,
      category: "internal",
      stage_def_id: id,
      count: items.length,
      terminal_type: null,
      items,
      ...extra,
    });
    return [
      col(601, "new", "Nowi / Analiza CV", nowi),
      col(602, "screening", "Screening", screening),
      col(603, "verified", "Zweryfikowany", []),
      col(608, "rejected", "Odrzucony", [], { category: "terminal", terminal_type: "rejected" }),
    ] as never;
  }

  function renderFiltered(addedBy: AddedByFilter, columns = boardColumns()) {
    const onAddedByChange = vi.fn<(filter: AddedByFilter) => void>();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const ui = (cols: never, filter: AddedByFilter) => (
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={cols} jobId={10} addedBy={filter} onAddedByChange={onAddedByChange} />
        </TooltipProvider>
      </QueryClientProvider>
    );
    const view = render(ui(columns, addedBy));
    return {
      onAddedByChange,
      rerender: (cols: never, filter: AddedByFilter = addedBy) => view.rerender(ui(cols, filter)),
    };
  }

  async function openPerson(name: string) {
    const link = await screen.findByRole("link", { name });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    return screen.findByRole("complementary", { name: "Panel osoby" });
  }

  const moveCalls = () => post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");

  it("„Ty”: karty innych znikają, kolumna mówi „2 z 5”, strzałki chodzą po Twoich w „Nowych”", async () => {
    const { onAddedByChange } = renderFiltered({ kind: "user", userId: 7 });
    expect(await screen.findByRole("group", { name: "Nowi, liczba kandydatów: 2 z 5" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Adam Nowak" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Emil Bąk" })).toBeNull();

    const panel = await openPerson("Beata Lis");
    expect(within(panel).getByText("1 z 2")).toBeInTheDocument();
    expect(within(panel).getByTestId("dock-queue-label")).toHaveTextContent("Nowi · dodani przez Ciebie");
    expect(within(panel).queryByRole("status", { name: "Koniec kolejki" })).toBeNull();

    fireEvent.click(within(panel).getByRole("button", { name: "Następna karta" }));
    await waitFor(() => expect(within(panel).getByText("2 z 2")).toBeInTheDocument());
    expect(within(panel).getAllByText("Dorota Wójcik").length).toBeGreaterThan(0);
    expect(within(panel).getByRole("button", { name: "Następna karta" })).toBeDisabled();

    // Koniec kolejki (D4): Screening nie ma Twoich osób, więc bez „Dalej”.
    const end = within(panel).getByRole("status", { name: "Koniec kolejki" });
    expect(end).toHaveTextContent("To ostatnia z 2 osób w kolejce.");
    expect(within(end).queryByRole("button", { name: /Dalej/ })).toBeNull();
    fireEvent.click(within(end).getByRole("button", { name: "Wszyscy (5)" }));
    expect(onAddedByChange).toHaveBeenCalledWith(ADDED_BY_ALL);
    fireEvent.click(within(end).getByRole("button", { name: "Od pierwszej" }));
    await waitFor(() => expect(within(panel).getByText("1 z 2")).toBeInTheDocument());
    expect(within(panel).getAllByText("Beata Lis").length).toBeGreaterThan(0);
  });

  it("bez filtra kolejka to cała kolumna „Nowi” (5), a nie cała Tablica (6)", async () => {
    renderFiltered(ADDED_BY_ALL);
    expect(await screen.findByRole("group", { name: "Nowi, liczba kandydatów: 5" })).toBeInTheDocument();
    const panel = await openPerson("Adam Nowak");
    expect(within(panel).getByText("1 z 5")).toBeInTheDocument();
    expect(within(panel).getByTestId("dock-queue-label")).toHaveTextContent(/^Nowi$/);
  });

  it("kolumna, z której filtr schował wszystkich, mówi to i daje „Pokaż wszystkich”", async () => {
    const { onAddedByChange } = renderFiltered({ kind: "user", userId: 7 });
    const screening = await screen.findByRole("group", { name: "Screening, liczba kandydatów: 0 z 1" });
    const empty = within(screening).getByTestId("column-filter-empty");
    expect(empty).toHaveTextContent("Brak osób dodanych przez Ciebie.");
    fireEvent.click(within(empty).getByRole("button", { name: "Pokaż wszystkich (1)" }));
    expect(onAddedByChange).toHaveBeenCalledWith(ADDED_BY_ALL);
  });

  it("„Brak danych” pokazuje karty bez zapisanej osoby dodającej", async () => {
    renderFiltered({ kind: "none" });
    expect(await screen.findByRole("link", { name: "Emil Bąk" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Beata Lis" })).toBeNull();
    const panel = await openPerson("Emil Bąk");
    expect(within(panel).getByTestId("dock-queue-label")).toHaveTextContent("Nowi · bez danych o dodającym");
  });

  it("upuszczenie przy filtrze przesuwa kartę, którą trzymasz — po numerze karty, nie po pozycji", async () => {
    renderFiltered({ kind: "user", userId: 7 });
    await screen.findByRole("link", { name: "Dorota Wójcik" });
    act(() =>
      dnd.onDragEnd?.({
        draggableId: String(DOROTA.id),
        type: "DEFAULT",
        reason: "DROP",
        mode: "FLUID",
        combine: null,
        source: { droppableId: "def:601", index: 0 },
        destination: { droppableId: "def:602", index: 0 },
      }),
    );
    await waitFor(() => expect(moveCalls()).toHaveLength(1));
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: DOROTA.candidate_id });
  });

  it("osoba wyszła z kolumny: panel zostaje, „Wróć do kolejki” prowadzi do tej, która stała za nią", async () => {
    const { rerender } = renderFiltered(ADDED_BY_ALL);
    const panel = await openPerson("Beata Lis");
    expect(within(panel).getByText("2 z 5")).toBeInTheDocument();

    // Beata przeszła na Screening (np. „Zapisz i przekaż dalej”).
    rerender(boardColumns([ADAM, CEZARY, DOROTA, EMIL], [FILIP, { ...BEATA, id: 1942, stage: "screening" }]));
    await waitFor(() => expect(within(panel).getByRole("button", { name: "Wróć do kolejki" })).toBeInTheDocument());
    expect(within(panel).getAllByText("Beata Lis").length).toBeGreaterThan(0);
    expect(within(panel).getByTestId("dock-queue-label")).toHaveTextContent("Nowi");

    fireEvent.click(within(panel).getByRole("button", { name: "Wróć do kolejki" }));
    await waitFor(() => expect(within(panel).getByText("2 z 4")).toBeInTheDocument());
    expect(within(panel).getAllByText("Cezary Mróz").length).toBeGreaterThan(0);
  });

  it("ta sama osoba otwarta z nowej kolumny (po zamknięciu panelu albo z karty) przenosi tam kolejkę", async () => {
    const { rerender } = renderFiltered(ADDED_BY_ALL, boardColumns([ADAM, BEATA, CEZARY], [FILIP]));
    let panel = await openPerson("Beata Lis");
    expect(within(panel).getByText("2 z 3")).toBeInTheDocument();
    const moved = boardColumns([ADAM, CEZARY], [FILIP, { ...BEATA, id: 1942, stage: "screening" }]);
    rerender(moved);
    await waitFor(() => expect(within(panel).getByRole("button", { name: "Wróć do kolejki" })).toBeInTheDocument());

    // Klik w kartę Beaty w Screeningu przy otwartym panelu.
    panel = await openPerson("Beata Lis");
    await waitFor(() => expect(within(panel).getByText("2 z 2")).toBeInTheDocument());
    expect(within(panel).getByTestId("dock-queue-label")).toHaveTextContent("Screening");

    // Wraca do „Nowych”, panel zamknięty, potem znów karta w Screeningu.
    fireEvent.click(within(panel).getByRole("button", { name: "Następna karta" }));
    rerender(boardColumns([ADAM, BEATA, CEZARY], [FILIP]));
    panel = await openPerson("Beata Lis");
    await waitFor(() => expect(within(panel).getByTestId("dock-queue-label")).toHaveTextContent("Nowi"));
    rerender(moved);
    fireEvent.click(within(panel).getByRole("button", { name: "Zamknij dok" }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Panel osoby" })).toBeNull());
    panel = await openPerson("Beata Lis");
    await waitFor(() => expect(within(panel).getByText("2 z 2")).toBeInTheDocument());
    expect(within(panel).getByTestId("dock-queue-label")).toHaveTextContent("Screening");
  });

  it("filtr odznacza osoby, które schował — pasek zaznaczonych nie działa na niewidocznych", async () => {
    const { rerender } = renderFiltered(ADDED_BY_ALL);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Zaznacz Adam Nowak" }));
    expect(await screen.findByText(/Zaznaczono/)).toBeInTheDocument();
    rerender(boardColumns(), { kind: "user", userId: 7 });
    await waitFor(() => expect(screen.queryByText(/Zaznaczono/)).toBeNull());
  });
});
