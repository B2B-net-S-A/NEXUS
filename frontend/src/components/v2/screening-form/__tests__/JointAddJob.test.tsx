import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AlsoFitsManualJob } from "@/lib/also-fits-api";

const search = vi.fn();
vi.mock("@/lib/also-fits-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/also-fits-api")>()),
  alsoFitsApi: {
    get: vi.fn(),
    search: (...a: unknown[]) => search(...a),
  },
}));

import { JointAddJob, manualJobContext } from "../JointAddJob";
import { JointScreeningPicker } from "../JointScreeningPicker";

function job(id: number, extra: Partial<AlsoFitsManualJob> = {}): AlsoFitsManualJob {
  return {
    job_id: id,
    title: `Senior Java Developer ${id}`,
    client_name: "Nordea Bank Abp",
    client_reference: `${42700 + id}`,
    delivery_lead_name: "Marcin K.",
    joinable: true,
    ...extra,
  };
}

function withQuery(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

async function openAndType(phrase: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /Dodaj inną rekrutację/ }));
  await user.type(screen.getByLabelText("Szukaj otwartej rekrutacji"), phrase);
  return user;
}

describe("„+ Dodaj inną rekrutację” w „Screening dla” (29.10.2026)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("szuka od 2 znaków, pomija rekrutacje już na liście i dołącza z zespołu", async () => {
    search.mockResolvedValue([job(42), job(7), job(9, { joinable: false })]);
    const onAdd = vi.fn();
    withQuery(<JointAddJob candidateId={4860} fromJobId={763073} listedIds={new Set([7])} onAdd={onAdd} />);
    await openAndType("42742");

    const mine = await screen.findByTestId("joint-add-42");
    expect(search).toHaveBeenCalledWith(4860, 763073, "42742");
    expect(screen.queryByTestId("joint-add-7")).toBeNull();
    expect(within(mine).getByText("Nordea Bank Abp · Twój zespół")).toBeInTheDocument();
    const foreign = screen.getByTestId("joint-add-9");
    expect(within(foreign).getByRole("button", { name: "+ Dodaj do Nowych" })).toBeInTheDocument();

    await userEvent.setup().click(within(mine).getByRole("button", { name: "+ Dodaj i dołącz" }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ job_id: 42, joinable: true }));
    // Po wyborze pole się zamyka — z powrotem sam link.
    expect(screen.getByRole("button", { name: /Dodaj inną rekrutację/ })).toBeInTheDocument();
  });

  it("jedna litera nie pyta serwera", async () => {
    withQuery(<JointAddJob candidateId={1} fromJobId={2} listedIds={new Set()} onAdd={vi.fn()} />);
    await openAndType("j");
    expect(screen.getByText(/Otwarte rekrutacje całej firmy/)).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });

  it("awaria wyszukiwania nie wygląda jak „brak rekrutacji”", async () => {
    search.mockRejectedValue(new Error("boom"));
    withQuery(<JointAddJob candidateId={1} fromJobId={2} listedIds={new Set()} onAdd={vi.fn()} />);
    await openAndType("java");
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wyszukać rekrutacji.");
    expect(screen.queryByText(/Brak otwartej rekrutacji/)).toBeNull();
  });

  it("przy komplecie rekrutacji w rozmowie własny zespół idzie tylko do „Nowych”", async () => {
    search.mockResolvedValue([job(42)]);
    withQuery(<JointAddJob candidateId={1} fromJobId={2} listedIds={new Set()} onAdd={vi.fn()} joinFull />);
    await openAndType("java");
    const row = await screen.findByTestId("joint-add-42");
    expect(within(row).getByRole("button", { name: "+ Dodaj do Nowych" })).toBeInTheDocument();
  });

  it("opis zespołu: inny zespół z imieniem DL-a albo bez niego", () => {
    expect(manualJobContext(job(1, { joinable: false }))).toBe("Nordea Bank Abp · inny zespół · DL: Marcin K.");
    expect(manualJobContext(job(1, { joinable: false, delivery_lead_name: null, client_name: null }))).toBe("inny zespół");
  });

  it("sekcja „Screening dla” stoi także bez podpowiedzi i innych rekrutacji osoby", () => {
    withQuery(
      <JointScreeningPicker
        anchorTitle="Full Stack Java Developer"
        pairs={[]}
        suggestions={[]}
        selected={new Set()}
        onToggle={vi.fn()}
        onAddAndJoin={vi.fn()}
        addingJobId={null}
        manualAdd={{ candidateId: 1, fromJobId: 2, onAdd: vi.fn(), addedNote: "Dodano do „Nowych”: Backend." }}
      />,
    );
    expect(screen.getByRole("region", { name: "Screening dla" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dodaj inną rekrutację/ })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Dodano do „Nowych”: Backend.");
  });
});
