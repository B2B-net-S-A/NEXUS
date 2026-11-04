/**
 * Pasek „Do dopięcia” nad Briefem (04.10.2026) — zastępuje zakładkę
 * „Gotowość” panelu bocznego. Pokazuje się wyłącznie, gdy jest co dopiąć,
 * a przycisk przekazania tylko przy rekrutacji nieprzekazanej (panel pokazywał
 * go obok zdania „Zlecenie przekazane do searchu”).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionTodoStrip } from "@/components/champion/ChampionTodoStrip";

const getMock = vi.fn();
const championGetMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const api = { get: (...args: unknown[]) => getMock(...args) };
  return {
    ...actual,
    default: api,
    api,
    championApi: { ...actual.championApi, get: (...args: unknown[]) => championGetMock(...args) },
  };
});
vi.mock("@/components/v2/recruitment/OrderMissingBlock", () => ({
  MissingBlock: ({ onGoChampion }: { onGoChampion: (a: string | null) => void }) => (
    <button type="button" data-testid="mock-missing" onClick={() => onGoChampion("champion-section-screening")}>
      braki
    </button>
  ),
}));
vi.mock("@/components/v2/jobs/JobHandoffButton", () => ({
  JobHandoffButton: () => <div data-testid="mock-handoff" />,
}));
vi.mock("@/components/ChampionVerificationChecklist", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/ChampionVerificationChecklist")>();
  return {
    ...actual,
    ChampionVerificationChecklist: ({ canEdit }: { canEdit: boolean }) => (
      <div data-testid="mock-verification" data-can-edit={String(canEdit)} />
    ),
  };
});

const VERIFIED = {
  job_id: 7,
  champion_profile: {
    verification: { client: { status: "verified" }, consultant: { status: "verified" } },
    briefing: { status: "attached" },
  },
};
const UNVERIFIED = {
  job_id: 7,
  champion_profile: {
    verification: { client: { status: "pending" }, consultant: { status: "pending" } },
    briefing: { status: "pending" },
  },
};

function readiness(patch: Record<string, unknown>) {
  getMock.mockResolvedValue({
    data: { ready: true, blockers: [], closed: false, already_handed_off: true, ...patch },
  });
}

function renderStrip(props: Partial<Parameters<typeof ChampionTodoStrip>[0]> = {}) {
  const onGoChampion = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <ChampionTodoStrip
        jobId={7}
        job={{ status: "published" }}
        canSeeGate
        canWritePipeline
        canEditChampion
        canEditJob
        onGoChampion={onGoChampion}
        onEditJob={() => undefined}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onGoChampion };
}

beforeEach(() => {
  getMock.mockReset();
  championGetMock.mockReset();
  championGetMock.mockResolvedValue({ data: VERIFIED });
});

describe("ChampionTodoStrip", () => {
  it("rekrutacja przekazana i zweryfikowana — pasek się nie pokazuje", async () => {
    readiness({});
    const { container } = renderStrip();
    await vi.waitFor(() => expect(getMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(container).toBeEmptyDOMElement();
  });

  it("przekazana, ale bez weryfikacji: zwinięty pasek z licznikiem, bez przycisku przekazania", async () => {
    readiness({});
    championGetMock.mockResolvedValue({ data: UNVERIFIED });
    renderStrip();
    const toggle = await screen.findByRole("button", { name: /Do dopięcia · 3/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent("rozmowa z klientem");
    expect(toggle).toHaveTextContent("nie blokuje pracy rekruterów");

    await userEvent.click(toggle);
    expect(screen.getByTestId("mock-verification")).toHaveAttribute("data-can-edit", "true");
    expect(screen.getByText(/Champion niezweryfikowany/)).toBeInTheDocument();
    expect(screen.queryByTestId("mock-handoff")).toBeNull();
  });

  it("nieprzekazana z brakami: pasek otwarty, braki i przycisk przekazania", async () => {
    readiness({ already_handed_off: false, ready: false, blockers: ["Ustaw termin."] });
    const { onGoChampion } = renderStrip();
    expect(await screen.findByTestId("mock-handoff")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Do dopięcia · 2/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await userEvent.click(screen.getByTestId("mock-missing"));
    expect(onGoChampion).toHaveBeenCalledWith("champion-section-screening");
  });

  it("bez zapisu w rekrutacjach nie ma przycisku przekazania", async () => {
    readiness({ already_handed_off: false });
    championGetMock.mockResolvedValue({ data: UNVERIFIED });
    renderStrip({ canWritePipeline: false });
    await screen.findByRole("button", { name: /Do dopięcia · 3/ });
    expect(screen.queryByTestId("mock-handoff")).toBeNull();
  });

  it("bez uprawnienia do prowadzenia rekrutacji nie pyta o gotowość i nic nie rysuje", async () => {
    const { container } = renderStrip({ canSeeGate: false });
    await new Promise((r) => setTimeout(r, 0));
    expect(getMock).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("zamknięta rekrutacja — nic do dopięcia", async () => {
    readiness({ closed: true, already_handed_off: false });
    championGetMock.mockResolvedValue({ data: UNVERIFIED });
    const { container } = renderStrip();
    await vi.waitFor(() => expect(getMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
