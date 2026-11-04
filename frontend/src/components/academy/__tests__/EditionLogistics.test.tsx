import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  EditionBoard,
  EditionLogistics,
  canReceiveKit,
  editionLabel,
  sectionProgress,
} from "@/components/academy/EditionLogistics";
import {
  defaultEdition,
  type EditionParticipant,
  type EditionView,
} from "@/lib/api/academy-edition";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
  showError: vi.fn(),
  config: undefined as unknown,
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, patch: mocks.patch, post: mocks.post },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError }),
}));
vi.mock("@/lib/api/hr", () => ({
  useHrConfig: () => mocks.config,
}));

function person(
  id: number,
  name: string,
  overrides: Partial<EditionParticipant> = {},
): EditionParticipant {
  return {
    application_id: id,
    candidate_id: 1000 + id,
    full_name: name,
    email: `osoba${id}@example.com`,
    city: "Lublin",
    status: "signed",
    status_label: "W akademii",
    left: false,
    cohort_month: "2026-11-01",
    contract: { state: "podpisana", at: "2026-10-10T10:00:00Z" },
    hotel: "do_zrobienia",
    ticket: "do_zrobienia",
    logistics_note: null,
    kit: { state: "brak", items: [] },
    protocol: null,
    ...overrides,
  };
}

const EDITION: EditionView = {
  edition: {
    program_id: 1,
    program_name: "Akademia Rekrutera",
    cohort_month: "2026-11-01",
    key: "2026-11",
    starts_on: "2026-11-02",
    ends_on: "2026-11-16",
  },
  checklist: [
    {
      key: "informacje",
      label: "Informacje od prowadzącej",
      done: 1,
      total: 2,
      items: [
        {
          id: 11,
          item_key: "info_start",
          label: "Otrzymać od prowadzącej informację, czy rusza kolejna edycja",
          done: true,
          done_at: "2026-10-01T10:00:00Z",
          done_by: "Recepcja Przykładowa",
          note: null,
        },
        {
          id: 12,
          item_key: "info_date",
          label: "Otrzymać termin rozpoczęcia edycji",
          done: false,
          done_at: null,
          done_by: null,
          note: null,
        },
      ],
    },
  ],
  checklist_done: 1,
  checklist_total: 2,
  participants: [
    person(1, "Marta Przykładowa"),
    person(2, "Kamil Testowy", {
      hotel: "zrobione",
      kit: { state: "wydany", items: [{ assignment_id: 5, item_id: 9, category: "laptop", name: "Laptop X" }] },
      protocol: { id: 3, number: "PZO/2026/10/001", status: "oczekuje" },
    }),
    person(3, "Ewa Fikcyjna", {
      left: true,
      status: "withdrew",
      status_label: "Zrezygnował",
      contract: { state: "rezygnacja", at: null },
      hotel: "do_anulowania",
      kit: { state: "do_zwrotu", items: [] },
    }),
    person(4, "Igor Wymyślony", { contract: { state: "wyslana", at: null } }),
  ],
  summary: {
    participants: 3,
    left: 1,
    contracts_signed: 2,
    kits_issued: 1,
    kits_to_return: 1,
    protocols_confirmed: 0,
    logistics_open: 6,
  },
  can_issue: true,
};

function wrap(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.config = { isSuccess: true, data: { open_modules: { equipment: true } } };
});

describe("pure helpers", () => {
  it("only people still in the edition without a kit can receive one", () => {
    expect(EDITION.participants.map(canReceiveKit)).toEqual([true, false, false, true]);
  });

  it("section progress is a percentage, zero for an empty section", () => {
    expect(sectionProgress({ done: 1, total: 3 })).toBe(33);
    expect(sectionProgress({ done: 0, total: 0 })).toBe(0);
  });

  it("an edition is a program month with its working days", () => {
    expect(editionLabel(EDITION.edition, false)).toBe("listopad 2026 · 02.11–16.11");
    expect(editionLabel(EDITION.edition, true)).toBe(
      "Akademia Rekrutera · listopad 2026 · 02.11–16.11",
    );
  });

  it("opens the nearest edition that has not ended its month", () => {
    const items = [{ key: "2026-12" }, { key: "2026-11" }, { key: "2026-09" }];
    expect(defaultEdition(items, "2026-10-16")).toEqual({ key: "2026-11" });
    expect(defaultEdition(items, "2026-11-20")).toEqual({ key: "2026-11" });
    expect(defaultEdition(items, "2027-01-05")).toEqual({ key: "2026-12" });
    expect(defaultEdition([], "2026-10-16")).toBeNull();
  });
});

describe("EditionBoard", () => {
  it("shows a row per participant and preselects people without a kit", () => {
    wrap(<EditionBoard data={EDITION} />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("Marta Przykładowa")).toBeInTheDocument();
    expect(within(table).getByText("Rezygnacja")).toBeInTheDocument();
    expect(within(table).getByText("Do zwrotu")).toBeInTheDocument();
    expect(within(table).getByText("PZO/2026/10/001")).toBeInTheDocument();
    // Marta i Igor: bez zestawu i w edycji; Kamil ma zestaw, Ewa odpadła.
    expect(screen.getByRole("button", { name: "Wydaj zestawy (2)" })).toBeEnabled();
    expect(screen.queryByRole("checkbox", { name: "Wydaj zestaw: Ewa Fikcyjna" })).toBeNull();
  });

  it("hides bulk issue for people without the equipment permission", () => {
    wrap(<EditionBoard data={{ ...EDITION, can_issue: false }} />);
    expect(screen.queryByRole("button", { name: /Wydaj zestawy/ })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /Wydaj zestaw:/ })).toBeNull();
  });

  it("unchecking a participant updates the bulk issue counter", async () => {
    const user = userEvent.setup();
    wrap(<EditionBoard data={EDITION} />);
    await user.click(screen.getByRole("checkbox", { name: "Wydaj zestaw: Igor Wymyślony" }));
    expect(screen.getByRole("button", { name: "Wydaj zestawy (1)" })).toBeEnabled();
  });

  it("ticks a checklist item through the API", async () => {
    const user = userEvent.setup();
    mocks.patch.mockResolvedValue({ data: { ...EDITION.checklist[0].items[1], done: true } });
    wrap(<EditionBoard data={EDITION} />);
    const section = screen.getByRole("button", { name: /Informacje od prowadzącej/ });
    expect(section).toHaveAttribute("aria-expanded", "false");
    await user.click(section);
    await user.click(screen.getByRole("checkbox", { name: "Otrzymać termin rozpoczęcia edycji" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith(
        "/api/academy/programs/1/editions/2026-11/checklist/12",
        { done: true },
      ),
    );
  });

  it("a failed checklist save is reported, not swallowed", async () => {
    const user = userEvent.setup();
    mocks.patch.mockRejectedValue({ response: { status: 500, data: { detail: "awaria" } } });
    wrap(<EditionBoard data={EDITION} />);
    await user.click(screen.getByRole("button", { name: /Informacje od prowadzącej/ }));
    await user.click(screen.getByRole("checkbox", { name: "Otrzymać termin rozpoczęcia edycji" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalled());
  });
});

describe("EditionLogistics", () => {
  it("renders nothing while the equipment module is off", () => {
    mocks.config = { isSuccess: true, data: { open_modules: { equipment: false } } };
    const { container } = wrap(<EditionLogistics programId={1} />);
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("a failed editions request is an error, not an empty list", async () => {
    mocks.get.mockRejectedValue({ response: { status: 500, data: {} } });
    wrap(<EditionLogistics programId={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByText(/Brak uczestników po zaliczonym zadaniu/)).toBeNull();
  });

  it("loads the edition with its participants", async () => {
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/academy/editions") {
        return { data: { items: [{ ...EDITION.edition, participants: 3, people: 4 }] } };
      }
      if (url === "/api/academy/programs/1/editions/2026-11") return { data: EDITION };
      throw new Error(`nieoczekiwany adres ${url}`);
    });
    wrap(<EditionLogistics programId={1} />);
    expect(await screen.findByText("Kamil Testowy")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/academy/editions", {
      params: { program_id: 1 },
    });
  });

  it("without a program lists editions of every program (reception tab)", async () => {
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/academy/editions") return { data: { items: [] } };
      throw new Error(`nieoczekiwany adres ${url}`);
    });
    wrap(<EditionLogistics />);
    expect(await screen.findByText(/Brak uczestników po zaliczonym zadaniu/)).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/academy/editions", { params: {} });
  });
});
