/**
 * Procesy rekrutacyjne (runda 2, 21.10.2026): etapy i powody odrzucenia
 * w zakładkach, przy etapie to, co ma ustawione, akcje w „⋯”. Dane fikcyjne.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StageDef } from "@/lib/api";

const address = vi.hoisted(() => ({ search: "" }));
const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn() }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(address.search),
  usePathname: () => "/settings",
}));
vi.mock("@/lib/url-selection", () => ({
  useUrlWriter: () => ({
    replaceUrl: (url: string) => {
      address.search = url.split("?")[1] ?? "";
    },
  }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  pipelineTemplatesApi: api,
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn() }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => false, confirmDialog: null }),
}));

import { PipelineTemplatesTab, processDescription, stageSetupBadges } from "./PipelineTemplatesTab";

function stage(id: number, name: string, over: Partial<StageDef> = {}): StageDef {
  return {
    id,
    template_id: 1,
    name,
    order: id,
    category: "internal",
    is_terminal: false,
    terminal_type: null,
    tracker_enabled: false,
    tracker_public_name: null,
    sla_max_days: null,
    legacy_enum_value: null,
    scorecard_schema: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...over,
  };
}

beforeEach(() => {
  address.search = "";
  api.list.mockResolvedValue({
    data: [{ id: 1, name: "Proces testowy", description: null, is_default: true, archived: false, stage_count: 3, created_at: "", updated_at: "" }],
  });
  api.get.mockResolvedValue({
    data: {
      id: 1,
      name: "Proces testowy",
      description: "Domyślny proces (seedowany z legacy enum PipelineStage).",
      is_default: true,
      stages: [
        stage(1, "Screening", { scorecard_schema: { questions: [{}, {}] } }),
        stage(2, "Rozmowa u klienta", { category: "external", sla_max_days: 5 }),
        stage(3, "Odrzucony", { category: "terminal", is_terminal: true, terminal_type: "rejected" }),
      ],
      rejection_reasons: [],
    },
  });
});

describe("processDescription / stageSetupBadges", () => {
  it("techniczny opis zasianego procesu nie trafia na ekran", () => {
    expect(processDescription("Domyślny proces (seedowany z legacy enum PipelineStage).")).toBeNull();
    expect(processDescription("  ")).toBeNull();
    expect(processDescription("Rekrutacje do banków")).toBe("Rekrutacje do banków");
  });

  it("pigułki: scorecard z liczbą pytań, SLA, widoczność dla kandydata", () => {
    expect(stageSetupBadges(stage(1, "A", { scorecard_schema: { questions: [{}] }, sla_max_days: 3, tracker_enabled: true }))).toEqual([
      "scorecard · 1",
      "SLA 3 dni",
      "widoczny dla kandydata",
    ]);
    expect(stageSetupBadges(stage(2, "B"))).toEqual([]);
  });
});

describe("PipelineTemplatesTab", () => {
  it("etapy z kategorią po polsku i ustawieniami, akcje w „⋯”, powody w osobnej zakładce", async () => {
    const user = userEvent.setup();
    render(<PipelineTemplatesTab />);

    const screening = await screen.findByTestId("stage-1");
    expect(within(screening).getByText("scorecard · 2")).toBeInTheDocument();
    expect(within(screen.getByTestId("stage-2")).getByText("U klienta")).toBeInTheDocument();
    expect(within(screen.getByTestId("stage-3")).getByText("Końcowy · odrzucenie")).toBeInTheDocument();
    expect(screen.queryByText(/legacy enum/)).toBeNull();
    expect(screen.getByText("domyślny")).toBeInTheDocument();

    await user.click(within(screen.getByTestId("stage-3")).getByRole("button", { name: "Więcej: Odrzucony" }));
    expect(await screen.findByRole("menuitem", { name: "Etapu końcowego nie usuniesz" })).toHaveAttribute(
      "data-disabled",
    );
    await user.keyboard("{Escape}");

    expect(screen.queryByText("Dodaj powód")).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Powody odrzucenia" }));
    expect(address.search).toBe("zakladka=powody");
  });
});
