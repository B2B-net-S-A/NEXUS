/**
 * `JobSettingsPanel` — „Ustawienia zlecenia" w zakładce „Zespół" doku kroku 02
 * (`JobReadinessDock`, `variant="champion"`). Siedem pól, dotąd wyłącznie
 * w pełnym oknie edycji (`AppShell.tsx` `JobFormFields`): Owner (TAC),
 * Delivery Lead, Szablon procesu, Kategoria kompetencji, Program / Train,
 * Priorytet, Deadline.
 *
 * Każdy wiersz zapisuje NATYCHMIAST po zmianie (wzorzec `HiringManagerPicker`)
 * przez `PATCH /api/jobs/{id}` z JEDNYM polem.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobSettingsPanel } from "@/components/v2/jobs/JobSettingsPanel";

const getMock = vi.fn();
const patchMock = vi.fn();
const clientTeamGetMock = vi.fn();
const templatesListMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    patch: (...args: unknown[]) => patchMock(...args),
  },
  clientTeamApi: {
    get: (...args: unknown[]) => clientTeamGetMock(...args),
  },
  pipelineTemplatesApi: {
    list: (...args: unknown[]) => templatesListMock(...args),
  },
}));

const clientTeamFixture = {
  tacs: [
    { id: 1, user_id: 11, name: "Kasia TAC", email: "k@example.com", created_at: "2026-01-01" },
    { id: 2, user_id: 12, name: "Marek TAC", email: "m@example.com", created_at: "2026-01-01" },
  ],
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

const categoriesFixture = [
  {
    id: 1,
    slug: "software_development",
    name_pl: "Software Development",
    name_en: "Software Development",
    description: "",
    keywords: [],
    display_order: 1,
  },
];

const templatesFixture = [
  {
    id: 5,
    name: "Default B2B",
    description: null,
    is_default: true,
    archived: false,
    stage_count: 6,
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
  },
];

function mockGetByUrl() {
  getMock.mockImplementation((url: string) => {
    if (url === "/api/users") {
      return Promise.resolve({ data: dlDirectoryFixture });
    }
    if (url === "/api/competence-categories") {
      return Promise.resolve({ data: categoriesFixture });
    }
    if (url === "/api/jobs/train-names") {
      return Promise.resolve({ data: { items: ["ART Payments"] } });
    }
    return Promise.resolve({ data: {} });
  });
}

const baseProps = {
  jobId: 501,
  clientId: 42,
  jobTitle: "Programista Python",
  jobDescription: "Opis oferty",
  jobRequirements: null,
  tacId: null as number | null,
  deliveryLeadId: null as number | null,
  pipelineTemplateId: null as number | null,
  competenceCategoryId: null as number | null,
  trainName: null as string | null,
  priority: "medium" as const,
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
  templatesListMock.mockReset();
  mockGetByUrl();
  clientTeamGetMock.mockResolvedValue({ data: clientTeamFixture });
  templatesListMock.mockResolvedValue({ data: templatesFixture });
  patchMock.mockResolvedValue({ data: {} });
});

describe("JobSettingsPanel — read view", () => {
  it('renderuje nagłówek "Ustawienia zlecenia" i puste wartości "nie przypisano" / "nie ustawiono"', async () => {
    renderPanel();

    expect(screen.getByText("Ustawienia zlecenia")).toBeInTheDocument();
    // Owner (TAC) + Delivery Lead: osoby — "nie przypisano".
    const notAssigned = await screen.findAllByText("nie przypisano");
    expect(notAssigned.length).toBe(2);
    // Szablon / Kategoria / Program / Deadline: "nie ustawiono".
    const notSet = screen.getAllByText("nie ustawiono");
    expect(notSet.length).toBe(4);
  });

  it("rozwiązuje nazwy z odpowiednich katalogów, nie pokazuje gołych ID", async () => {
    renderPanel({
      tacId: 11,
      deliveryLeadId: 21,
      pipelineTemplateId: 5,
      competenceCategoryId: 1,
      trainName: "ART Payments",
    });

    expect(await screen.findByText("Kasia TAC")).toBeInTheDocument();
    expect(await screen.findByText("Head DL")).toBeInTheDocument();
    expect(await screen.findByText("Default B2B")).toBeInTheDocument();
    expect(await screen.findByText("Software Development")).toBeInTheDocument();
    expect(screen.getByText("ART Payments")).toBeInTheDocument();
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

describe("JobSettingsPanel — Owner (TAC)", () => {
  it("edycja pokazuje optgroup TAC-ów klienta i hint przy >1 TAC-u", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click((await screen.findAllByText("Zmień"))[0]);

    const select = await screen.findByLabelText("Owner requestu (TAC)");
    const group = within(select).getByRole("group", {
      name: "TAC-y przypisani do klienta",
    });
    expect(within(group).getByRole("option", { name: "Kasia TAC" })).toBeInTheDocument();
    expect(within(group).getByRole("option", { name: "Marek TAC" })).toBeInTheDocument();
    expect(screen.getByText("Klient ma 2 równorzędnych TAC-ów.")).toBeInTheDocument();
  });

  it("wybór TAC-a wysyła PATCH {tac_id: 12}", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click((await screen.findAllByText("Zmień"))[0]);
    const select = await screen.findByLabelText("Owner requestu (TAC)");
    await user.selectOptions(select, "12");

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { tac_id: 12 }),
    );
  });

  it('czyszczenie ("— brak ownera requestu —") wysyła PATCH {tac_id: null}', async () => {
    const user = userEvent.setup();
    renderPanel({ tacId: 11 });

    await user.click((await screen.findAllByText("Zmień"))[0]);
    const select = await screen.findByLabelText("Owner requestu (TAC)");
    await user.selectOptions(select, "");

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { tac_id: null }),
    );
  });

  it("po udanym zapisie unieważnia champion-profile / job / job-readiness / jobs-v2 / dashboard,my-jobs", async () => {
    const user = userEvent.setup();
    const { invalidateSpy } = renderPanel();

    await user.click((await screen.findAllByText("Zmień"))[0]);
    const select = await screen.findByLabelText("Owner requestu (TAC)");
    await user.selectOptions(select, "12");

    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    const invalidatedKeys = invalidateSpy.mock.calls.map((call) => (call[0] as { queryKey: unknown[] })?.queryKey);
    expect(invalidatedKeys).toContainEqual(["champion-profile", 501]);
    expect(invalidatedKeys).toContainEqual(["job", "501"]);
    expect(invalidatedKeys).toContainEqual(["job-readiness", 501]);
    expect(invalidatedKeys).toContainEqual(["jobs-v2"]);
    expect(invalidatedKeys).toContainEqual(["dashboard", "my-jobs"]);
  });

  it("edycja po zapisie zamyka wiersz (wraca do read-view) — wartość odświeża rodzic przez unieważnienie", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click((await screen.findAllByText("Zmień"))[0]);
    const select = await screen.findByLabelText("Owner requestu (TAC)");
    await user.selectOptions(select, "12");

    // Panel nie robi optymistycznej aktualizacji — `tacId` wraca stąd, skąd
    // przyszedł (propsy rodzica), a ten sam odczyta go dopiero po
    // unieważnieniu `["job", "<id>"]` (osobny test wyżej). Tu pilnujemy
    // wyłącznie tego, że po udanym zapisie wiersz przestaje być w edycji.
    await waitFor(() =>
      expect(screen.queryByLabelText("Owner requestu (TAC)")).not.toBeInTheDocument(),
    );
  });
});

describe("JobSettingsPanel — Delivery Lead", () => {
  it("katalog DL-i idzie przez /api/users z powtarzanymi roles= (paramsSerializer indexes:null)", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getAllByText("Zmień")[1]);
    await screen.findByLabelText("Delivery Lead");

    const call = getMock.mock.calls.find(([url]) => url === "/api/users");
    expect(call).toBeTruthy();
    expect(call?.[1]).toMatchObject({
      params: { roles: ["delivery_lead", "admin", "head_of_recruitment"] },
      paramsSerializer: { indexes: null },
    });
  });

  it("wybór DL-a wysyła PATCH {delivery_lead_id: 22}", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getAllByText("Zmień")[1]);
    const select = await screen.findByLabelText("Delivery Lead");
    await user.selectOptions(select, "22");

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { delivery_lead_id: 22 }),
    );
  });
});

describe("JobSettingsPanel — Priorytet i Deadline", () => {
  it("zmiana priorytetu wysyła PATCH {priority: \"high\"}", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getAllByText("Zmień")[5]);
    const select = await screen.findByLabelText("Priorytet");
    await user.selectOptions(select, "high");

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { priority: "high" }),
    );
  });

  it('etykiety priorytetu to Niski/Średni/Wysoki/Krytyczny', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getAllByText("Zmień")[5]);
    const select = await screen.findByLabelText("Priorytet");
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Niski", "Średni", "Wysoki", "Krytyczny"]);
  });

  it("zmiana deadline'u wysyła PATCH {deadline: \"2026-12-01\"}", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getAllByText("Zmień")[6]);
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

    await user.click((await screen.findAllByText("Zmień"))[0]);
    const select = await screen.findByLabelText("Owner requestu (TAC)");
    await user.selectOptions(select, "12");

    expect(await screen.findByText("Błąd serwera")).toBeInTheDocument();
    expect(screen.getByLabelText("Owner requestu (TAC)")).toBeInTheDocument();
  });
});
