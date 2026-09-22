/**
 * `JobSettingsPanel` — „Ustawienia zlecenia" w zakładce „Zespół" doku.
 *
 * Od 22.09.2026 dwa pola: Delivery Lead i Deadline. Owner (TAC), Szablon
 * procesu, Kategoria kompetencji, Program / Train i Priorytet zniknęły
 * z tworzenia i z ustawień (decyzja Artura przy stronie `/jobs/new`).
 *
 * Każdy wiersz zapisuje NATYCHMIAST po zmianie przez `PATCH /api/jobs/{id}`
 * z JEDNYM polem.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobSettingsPanel } from "@/components/v2/jobs/JobSettingsPanel";

const getMock = vi.fn();
const patchMock = vi.fn();
const clientTeamGetMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    patch: (...args: unknown[]) => patchMock(...args),
  },
  clientTeamApi: {
    get: (...args: unknown[]) => clientTeamGetMock(...args),
  },
}));

const clientTeamFixture = {
  tacs: [],
  delivery_leads: [
    {
      id: 3,
      user_id: 21,
      name: "Head DL",
      email: "head@example.com",
      created_at: "2026-01-01",
      is_head: true,
    },
  ],
};

const dlDirectoryFixture = [
  { id: 21, name: "Head DL", email: "head@example.com" },
  { id: 22, name: "Zwykły DL", email: "zwykly@example.com" },
];

const baseProps = {
  jobId: 501,
  clientId: 42,
  deliveryLeadId: null as number | null,
  deadline: null as string | null,
  canEdit: true,
};

function renderPanel(props: Partial<typeof baseProps> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={client}>
      <JobSettingsPanel {...baseProps} {...props} />
    </QueryClientProvider>,
  );
  return { client, invalidateSpy, ...view };
}

beforeEach(() => {
  getMock.mockReset();
  patchMock.mockReset();
  clientTeamGetMock.mockReset();
  getMock.mockImplementation((url: string) =>
    Promise.resolve({ data: url === "/api/users" ? dlDirectoryFixture : {} }),
  );
  clientTeamGetMock.mockResolvedValue({ data: clientTeamFixture });
  patchMock.mockResolvedValue({ data: {} });
});

describe("JobSettingsPanel — read view", () => {
  it("ma wyłącznie Delivery Leada i Deadline", async () => {
    renderPanel();

    expect(screen.getByText("Ustawienia zlecenia")).toBeInTheDocument();
    expect(await screen.findByText("nie przypisano")).toBeInTheDocument();
    expect(screen.getByText("nie ustawiono")).toBeInTheDocument();
    expect(screen.getAllByText("Zmień")).toHaveLength(2);
    for (const gone of [
      "Owner (TAC)",
      "Szablon procesu",
      "Kat. kompetencji",
      "Program / Train",
      "Priorytet",
    ]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
  });

  it('pokazuje "✓ Head DL klienta" dla przypisanego head DL i "Nadpisane" dla innego', async () => {
    renderPanel({ deliveryLeadId: 21 });
    expect(await screen.findByText("✓ Head DL klienta")).toBeInTheDocument();

    renderPanel({ deliveryLeadId: 22 });
    expect(await screen.findByText("Nadpisane (head DL klienta: Head DL)")).toBeInTheDocument();
  });
});

describe("JobSettingsPanel — canEdit=false", () => {
  it('chowa wszystkie linki "Zmień"', () => {
    renderPanel({ canEdit: false });
    expect(screen.queryByText("Zmień")).not.toBeInTheDocument();
  });
});

describe("JobSettingsPanel — Delivery Lead", () => {
  it("katalog DL-i idzie przez /api/users z powtarzanymi roles= (paramsSerializer indexes:null)", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getAllByText("Zmień")[0]);
    await screen.findByLabelText("Delivery Lead");

    const call = getMock.mock.calls.find(([url]) => url === "/api/users");
    expect(call?.[1]).toMatchObject({
      params: { roles: ["delivery_lead", "admin", "head_of_recruitment"] },
      paramsSerializer: { indexes: null },
    });
  });

  it("wybór DL-a wysyła PATCH {delivery_lead_id: 22} i unieważnia zależne widoki", async () => {
    const user = userEvent.setup();
    const { invalidateSpy } = renderPanel();

    await user.click(screen.getAllByText("Zmień")[0]);
    const select = await screen.findByLabelText("Delivery Lead");
    await user.selectOptions(select, "22");

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { delivery_lead_id: 22 }),
    );
    const keys = invalidateSpy.mock.calls.map(
      (call) => (call[0] as { queryKey: unknown[] })?.queryKey,
    );
    expect(keys).toContainEqual(["job-readiness", 501]);
    expect(keys).toContainEqual(["jobs-v2"]);
    await waitFor(() =>
      expect(screen.queryByLabelText("Delivery Lead")).not.toBeInTheDocument(),
    );
  });
});

describe("JobSettingsPanel — Deadline", () => {
  it("zmiana deadline'u wysyła PATCH {deadline: \"2026-12-01\"}", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getAllByText("Zmień")[1]);
    const input = await screen.findByLabelText("Deadline");
    await user.clear(input);
    await user.type(input, "2026-12-01");

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { deadline: "2026-12-01" }),
    );
  });
});

describe("JobSettingsPanel — błąd zapisu", () => {
  it("nieudany PATCH zostawia wiersz w edycji z komunikatem, nie zamyka go po cichu", async () => {
    patchMock.mockRejectedValueOnce({
      response: { status: 500, data: { detail: "Błąd serwera" } },
    });
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getAllByText("Zmień")[0]);
    const select = await screen.findByLabelText("Delivery Lead");
    await user.selectOptions(select, "22");

    expect(await screen.findByText("Błąd serwera")).toBeInTheDocument();
    expect(screen.getByLabelText("Delivery Lead")).toBeInTheDocument();
  });
});
