import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => get(...a) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: toastSuccess, showError: toastError, showToast: vi.fn() }),
}));

import {
  HAND_TO_DL_MESSAGE,
  MoveNextDialog,
  NO_QC_STAGE_MESSAGE,
} from "@/components/v2/recruitment/MoveNextDialog";
import type { MoveRequirementsResponse } from "@/lib/api/moveRequirements";

const item = { id: 11, candidate_id: 7, stage: "verified", name: "Anna", lastname: "Kowalczyk" };
const target = { stage: "interview", name: "QC CV", stage_def_id: 44, count: 0, items: [] };

function respond(data: Partial<MoveRequirementsResponse>) {
  get.mockResolvedValue({
    data: {
      from_column: "verified",
      to_column: "cv_qc",
      skipped_columns: [],
      items: [],
      primary: { kind: "move", label: "Przesuń na „QC CV”" },
      owner_note: null,
      ...data,
    },
  });
}

function renderDialog(overrides: Partial<React.ComponentProps<typeof MoveNextDialog>> = {}) {
  const props = {
    open: true,
    onOpenChange: vi.fn(),
    jobId: 3,
    item: item as never,
    target: target as never,
    targetLabel: "QC CV",
    fromKey: "verified" as const,
    targetKey: "cv_qc" as const,
    onMove: vi.fn(),
    onHandToCpro: vi.fn(),
    onAction: vi.fn(),
    ...overrides,
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MoveNextDialog {...props} />
    </QueryClientProvider>,
  );
  return props;
}

describe("MoveNextDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pyta serwer o wymagania dokładnie tego ruchu i pokazuje pasek 8 kroków", async () => {
    respond({});
    renderDialog();
    expect(await screen.findByText("Ten krok nie ma wymagań — możesz przesuwać.")).toBeTruthy();
    expect(get).toHaveBeenCalledWith(
      "/api/pipeline/move-requirements",
      expect.objectContaining({ params: { candidate_id: 7, job_id: 3, to_stage_def_id: 44 } }),
    );
    const steps = within(screen.getByTestId("move-next-steps")).getAllByRole("listitem");
    expect(steps).toHaveLength(8);
    expect(steps[2]).toHaveAttribute("data-state", "current");
    expect(steps[3]).toHaveAttribute("data-state", "target");
  });

  it("blokujący brak wyłącza główny przycisk, a akcja przy braku woła onAction", async () => {
    respond({
      items: [
        {
          key: "company_cv",
          label: "CV firmowe „Pod rekrutację”",
          detail: "jeszcze nie wygenerowane",
          status: "missing",
          blocking: true,
          action: { kind: "generate_cv", label: "Wygeneruj teraz", stage_id: 11 },
        },
        { key: "availability", label: "Dostępność", status: "missing", blocking: false, action: null },
      ],
    });
    const props = renderDialog();
    await screen.findByText("CV firmowe „Pod rekrutację”");
    expect(screen.getByText("(nie blokuje)")).toBeTruthy();
    const primary = screen.getByTestId("move-next-primary");
    expect(primary).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Wygeneruj teraz" }));
    expect(props.onAction).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "generate_cv", stage_id: 11 }),
      item,
    );
    expect(props.onMove).not.toHaveBeenCalled();
  });

  it("stawka kandydata nie blokuje — zapyta o nią okno ruchu", async () => {
    respond({
      from_column: "screening",
      to_column: "verified",
      items: [
        {
          key: "candidate_rate",
          label: "Stawka kandydata",
          status: "missing",
          blocking: true,
          action: { kind: "set_candidate_rate", label: "Wpisz stawkę" },
        },
      ],
      primary: { kind: "move", label: "Przesuń na „Zweryfikowany”" },
    });
    const props = renderDialog({ targetKey: "verified", fromKey: "screening" });
    await screen.findByText("Zapytamy o nią przy przesunięciu.");
    expect(screen.queryByRole("button", { name: "Wpisz stawkę" })).toBeNull();
    const primary = screen.getByTestId("move-next-primary");
    expect(primary).not.toBeDisabled();
    await userEvent.click(primary);
    expect(props.onMove).toHaveBeenCalledWith(target);
  });

  it("hand_to_dl: toast o kolejce DL i zamknięcie — bez ruchu", async () => {
    respond({
      from_column: "cv_qc",
      to_column: "cv_sent",
      items: [
        {
          key: "client_rate",
          label: "Stawka do klienta",
          status: "waiting",
          blocking: false,
          action: { kind: "set_client_rate", label: "Wpisz stawkę" },
        },
      ],
      primary: { kind: "hand_to_dl", label: "Przekaż do Delivery Leada" },
      owner_note: "CV wysyła Delivery Lead — trafi do jego „Czeka na Ciebie”.",
    });
    const props = renderDialog({ targetKey: "cv_sent", fromKey: "cv_qc" });
    expect(await screen.findByTestId("move-next-owner-note")).toHaveTextContent("CV wysyła Delivery Lead");
    await userEvent.click(screen.getByTestId("move-next-primary"));
    expect(toastSuccess).toHaveBeenCalledWith(HAND_TO_DL_MESSAGE);
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
    expect(props.onMove).not.toHaveBeenCalled();
  });

  it("hand_to_dl ze „Zweryfikowanego”: przesuwa na QC CV, żeby DL ją zobaczył", async () => {
    respond({
      from_column: "verified",
      to_column: "cv_sent",
      primary: { kind: "hand_to_dl", label: "Przekaż do Delivery Leada", target_stage_def_id: 41 },
    });
    const props = renderDialog({ targetKey: "cv_sent", fromKey: "verified" });
    await userEvent.click(await screen.findByTestId("move-next-primary"));
    expect(props.onHandToCpro).toHaveBeenCalledWith(41);
    expect(toastSuccess).toHaveBeenCalledWith(HAND_TO_DL_MESSAGE);
  });

  it("hand_to_dl bez etapu QC w szablonie: mówi to wprost, nie udaje przekazania", async () => {
    respond({
      from_column: "verified",
      to_column: "cv_sent",
      primary: { kind: "hand_to_dl", label: "Przekaż do Delivery Leada", target_stage_def_id: null },
    });
    const props = renderDialog({ targetKey: "cv_sent", fromKey: "verified" });
    await userEvent.click(await screen.findByTestId("move-next-primary"));
    expect(props.onHandToCpro).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(NO_QC_STAGE_MESSAGE);
    expect(toastSuccess).not.toHaveBeenCalledWith(HAND_TO_DL_MESSAGE);
  });

  it("hand_to_cpro: ruch na etap Cpro wskazany przez serwer", async () => {
    respond({
      from_column: "cv_qc",
      to_column: "cv_sent",
      primary: { kind: "hand_to_cpro", label: "Przekaż do Cpro", target_stage_def_id: 45 },
    });
    const props = renderDialog({ cproEnabled: true, targetKey: "cv_sent", fromKey: "cv_qc" });
    await userEvent.click(await screen.findByRole("button", { name: /Przekaż do Cpro/ }));
    expect(props.onHandToCpro).toHaveBeenCalledWith(45);
    expect(props.onMove).not.toHaveBeenCalled();
  });

  it("pomijane kolumny są oznaczone i nazwane", async () => {
    respond({ from_column: "screening", to_column: "cv_qc", skipped_columns: ["verified"] });
    renderDialog({ fromKey: "screening" });
    await screen.findByText(/Pomijasz: Zweryfikowany/);
    const steps = within(screen.getByTestId("move-next-steps")).getAllByRole("listitem");
    expect(steps[2]).toHaveAttribute("data-state", "skipped");
  });

  it("awaria serwera nie zamyka drogi — „Przesuń mimo to” robi zwykły ruch", async () => {
    get.mockRejectedValue(new Error("boom"));
    const props = renderDialog();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się sprawdzić wymagań.");
    await userEvent.click(within(alert).getByRole("button", { name: "Przesuń mimo to" }));
    await waitFor(() => expect(props.onMove).toHaveBeenCalledWith(target));
  });
});
