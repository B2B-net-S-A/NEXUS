/**
 * `JobSettingsPanel` — karta zakładki „Zespół” doku gotowości.
 *
 * Od 02.10.2026 pięć wierszy w stałej kolejności: Delivery Lead → Rekruter →
 * Kategoria → Termin → Priorytet (decyzja Artura, feedback Head of
 * Recruitment). Priorytet wrócił w trzech poziomach — do tej daty test
 * pilnował, że go tu NIE ma.
 * Owner (TAC), szablon procesu i Program / Train nadal ustawia backend.
 *
 * Delivery Lead i Termin zapisują przez `PATCH /api/jobs/{id}` z JEDNYM polem,
 * priorytet — kliknięciem poziomu.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JobSettingsPanel,
  type JobSettingsPanelProps,
} from "@/components/v2/jobs/JobSettingsPanel";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";

const getMock = vi.fn();
const patchMock = vi.fn();
const clientTeamGetMock = vi.fn();
const categoriesListMock = vi.fn();
const toast = vi.hoisted(() => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    patch: (...args: unknown[]) => patchMock(...args),
  },
  clientTeamApi: {
    get: (...args: unknown[]) => clientTeamGetMock(...args),
  },
  competenceCategoriesApi: {
    list: (...args: unknown[]) => categoriesListMock(...args),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

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

const baseProps: JobSettingsPanelProps = {
  jobId: 501,
  clientId: 42,
  deliveryLeadId: null,
  deadline: null,
  deadlineTime: null,
  canEdit: true,
  categoryId: null,
  priorityLevel: "p2",
  canSetPriority: true,
};

function panel(props: Partial<JobSettingsPanelProps> = {}) {
  return <JobSettingsPanel {...baseProps} {...props} />;
}

function renderPanel(props: Partial<JobSettingsPanelProps> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={client}>{panel(props)}</QueryClientProvider>,
  );
  const invalidatedKeys = () =>
    invalidateSpy.mock.calls.map(
      (call) => (call[0] as { queryKey: unknown[] })?.queryKey,
    );
  return {
    client,
    invalidatedKeys,
    rerenderPanel: (next: Partial<JobSettingsPanelProps>) =>
      view.rerender(
        <QueryClientProvider client={client}>{panel(next)}</QueryClientProvider>,
      ),
    ...view,
  };
}

const priorityGroup = () => screen.getByRole("radiogroup", { name: "Priorytet" });
const priorityOption = (name: string) =>
  within(priorityGroup()).getByRole("radio", { name });

beforeEach(() => {
  getMock.mockReset();
  patchMock.mockReset();
  clientTeamGetMock.mockReset();
  categoriesListMock.mockReset();
  toast.showSuccess.mockReset();
  toast.showError.mockReset();
  toast.showInfo.mockReset();
  getMock.mockImplementation((url: string) =>
    Promise.resolve({ data: url === "/api/users" ? dlDirectoryFixture : {} }),
  );
  clientTeamGetMock.mockResolvedValue({ data: clientTeamFixture });
  categoriesListMock.mockResolvedValue([]);
  patchMock.mockResolvedValue({ data: {} });
});

describe("JobSettingsPanel — karta zespołu", () => {
  it("ma pięć wierszy w kolejności: Delivery Lead, Rekruter, Kategoria, Termin, Priorytet", async () => {
    renderPanel({ recruiters: <span>osoby przy rekrutacji</span> });

    const card = screen.getByRole("region", { name: "Zespół, termin i priorytet" });
    expect(await within(card).findByText("nie przypisano")).toBeInTheDocument();
    const labels = within(card)
      .getAllByText(/^(Delivery Lead|Rekruter|Kategoria|Termin|Priorytet)$/)
      .map((node) => node.textContent);
    expect(labels).toEqual([
      "Delivery Lead",
      "Rekruter",
      "Kategoria",
      "Termin",
      "Priorytet",
    ]);
    expect(within(card).getByText("osoby przy rekrutacji")).toBeInTheDocument();
    expect(within(card).getByText("nie ustawiono")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zmień: Delivery Lead" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zmień: Termin" })).toBeInTheDocument();
  });

  it("nie ma starych nazw ani pól, które ustawia backend", async () => {
    renderPanel({ recruiters: <span>osoby przy rekrutacji</span> });
    await screen.findByText("nie przypisano");

    for (const gone of [
      "Ustawienia zlecenia",
      "Deadline",
      "Właściciel projektu",
      "Współpracownicy",
      "Owner (TAC)",
      "Szablon procesu",
      "Kat. kompetencji",
      "Program / Train",
    ]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
  });

  it("bez treści wiersza „Rekruter” wiersza nie ma (karta bywa użyta bez obsady)", async () => {
    renderPanel();
    await screen.findByText("nie przypisano");
    expect(screen.queryByText("Rekruter")).not.toBeInTheDocument();
  });

  it('pokazuje "✓ Head DL klienta" dla przypisanego head DL i "Nadpisane" dla innego', async () => {
    renderPanel({ deliveryLeadId: 21 });
    expect(await screen.findByText("✓ Head DL klienta")).toBeInTheDocument();

    renderPanel({ deliveryLeadId: 22 });
    expect(await screen.findByText("Nadpisane (head DL klienta: Head DL)")).toBeInTheDocument();
  });
});

describe("JobSettingsPanel — canEdit=false", () => {
  it('chowa linki "Zmień" przy Delivery Leadzie i terminie', () => {
    renderPanel({ canEdit: false });
    expect(screen.queryByText("Zmień")).not.toBeInTheDocument();
  });
});

describe("JobSettingsPanel — Delivery Lead", () => {
  it("katalog DL-i idzie przez /api/users z powtarzanymi roles= (paramsSerializer indexes:null)", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Zmień: Delivery Lead" }));
    await screen.findByLabelText("Delivery Lead");

    const call = getMock.mock.calls.find(([url]) => url === "/api/users");
    expect(call?.[1]).toMatchObject({
      params: { roles: ["delivery_lead", "admin", "head_of_recruitment"] },
      paramsSerializer: { indexes: null },
    });
  });

  it("wybór DL-a wysyła PATCH {delivery_lead_id: 22} i unieważnia zależne widoki", async () => {
    const user = userEvent.setup();
    const { invalidatedKeys } = renderPanel();

    await user.click(screen.getByRole("button", { name: "Zmień: Delivery Lead" }));
    const select = await screen.findByLabelText("Delivery Lead");
    await user.selectOptions(select, "22");

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { delivery_lead_id: 22 }),
    );
    const keys = invalidatedKeys();
    expect(keys).toContainEqual(["job-readiness", 501]);
    expect(keys).toContainEqual(["jobs-v2"]);
    // Delivery Lead jest kolumną i filtrem także na pulpicie „Requesty i obłożenie”.
    expect(keys).toContainEqual(REQUEST_BOARD_QUERY_KEY);
    await waitFor(() =>
      expect(screen.queryByLabelText("Delivery Lead")).not.toBeInTheDocument(),
    );
  });
});

describe("JobSettingsPanel — Termin", () => {
  it("zapis samej daty wysyła PATCH {deadline, deadline_time: null}", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Zmień: Termin" }));
    const input = await screen.findByLabelText("Termin");
    await user.clear(input);
    await user.type(input, "2026-12-01");
    await user.click(screen.getByText("Zapisz"));

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", {
        deadline: "2026-12-01",
        deadline_time: null,
      }),
    );
  });

  it("data z godziną idzie jednym zapisem, a widok pokazuje „01.10.2026, 12:00”", async () => {
    const user = userEvent.setup();
    renderPanel({ deadline: "2026-10-01", deadlineTime: null });

    await user.click(screen.getByRole("button", { name: "Zmień: Termin" }));
    const time = await screen.findByLabelText("Godzina terminu");
    await user.type(time, "12:00");
    await user.click(screen.getByText("Zapisz"));

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", {
        deadline: "2026-10-01",
        deadline_time: "12:00",
      }),
    );

    renderPanel({ deadline: "2026-10-01", deadlineTime: "12:00:00" });
    expect(screen.getByText("01.10.2026, 12:00")).toBeInTheDocument();
  });

  it("godzina jest zablokowana bez daty", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Zmień: Termin" }));
    expect(await screen.findByLabelText("Godzina terminu")).toBeDisabled();
  });
});

describe("JobSettingsPanel — błąd zapisu", () => {
  it("nieudany PATCH zostawia wiersz w edycji z komunikatem, nie zamyka go po cichu", async () => {
    patchMock.mockRejectedValueOnce({
      response: { status: 500, data: { detail: "Błąd serwera" } },
    });
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Zmień: Delivery Lead" }));
    const select = await screen.findByLabelText("Delivery Lead");
    await user.selectOptions(select, "22");

    expect(await screen.findByText("Błąd serwera")).toBeInTheDocument();
    expect(screen.getByLabelText("Delivery Lead")).toBeInTheDocument();
  });
});

describe("JobSettingsPanel — Priorytet", () => {
  it("pokazuje trzy poziomy z zaznaczonym bieżącym", () => {
    renderPanel({ priorityLevel: "p1" });

    expect(
      within(priorityGroup())
        .getAllByRole("radio")
        .map((radio) => radio.textContent),
    ).toEqual(["P1 Pilne", "P2 Standard", "Przyjmujemy kandydatów"]);
    expect(priorityOption("P1 Pilne")).toBeChecked();
    expect(priorityOption("P2 Standard")).not.toBeChecked();
  });

  it.each([
    ["P1 Pilne", "urgent"],
    ["Przyjmujemy kandydatów", "low"],
  ])("kliknięcie „%s” zapisuje PATCH {priority: %s} i odświeża obsadę wszędzie", async (label, raw) => {
    const user = userEvent.setup();
    const { invalidatedKeys } = renderPanel({ priorityLevel: "p2" });

    await user.click(priorityOption(label));

    // Wybór widać od razu, bez czekania na serwer.
    expect(priorityOption(label)).toBeChecked();
    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { priority: raw }),
    );
    await waitFor(() => expect(invalidatedKeys()).toContainEqual(["job", "501"]));
    const keys = invalidatedKeys();
    for (const key of [
      ["job", 501],
      ["jobs-v2"],
      ["jobs-quick-counts"],
      REQUEST_BOARD_QUERY_KEY,
      BOARD_TASKS_QUERY_KEY,
    ]) {
      expect(keys).toContainEqual(key);
    }
    expect(toast.showError).not.toHaveBeenCalled();
  });

  it("powrót na P2 zapisuje „medium”", async () => {
    const user = userEvent.setup();
    renderPanel({ priorityLevel: "p1" });

    await user.click(priorityOption("P2 Standard"));

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { priority: "medium" }),
    );
  });

  it("kliknięcie zaznaczonego poziomu niczego nie zapisuje", async () => {
    const user = userEvent.setup();
    renderPanel({ priorityLevel: "p2" });

    await user.click(priorityOption("P2 Standard"));

    expect(patchMock).not.toHaveBeenCalled();
  });

  it("odmowa serwera cofa wybór i pokazuje jego komunikat", async () => {
    patchMock.mockRejectedValueOnce({
      response: {
        status: 403,
        data: { detail: "Priorytet tej rekrutacji ustawia jej Delivery Lead." },
      },
    });
    const user = userEvent.setup();
    const { invalidatedKeys } = renderPanel({ priorityLevel: "p2" });

    await user.click(priorityOption("P1 Pilne"));

    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith(
        "Priorytet tej rekrutacji ustawia jej Delivery Lead.",
      ),
    );
    expect(priorityOption("P2 Standard")).toBeChecked();
    expect(priorityOption("P1 Pilne")).not.toBeChecked();
    // Także po odmowie: ekran mógł pokazywać nieaktualny stan.
    expect(invalidatedKeys()).toContainEqual(["job", "501"]);
  });

  it("strzałki zapisują po kolei i zostaje ostatni wybór, nie poziom ze środka", async () => {
    // Pierwszy zapis czeka — drugi nie może go wyprzedzić ani zostać cofnięty.
    let releaseFirst: () => void = () => undefined;
    patchMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseFirst = () => resolve({ data: {} });
        }),
    );
    const user = userEvent.setup();
    const { rerenderPanel } = renderPanel({ priorityLevel: "p1" });

    priorityOption("P1 Pilne").focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");

    expect(priorityOption("Przyjmujemy kandydatów")).toBeChecked();
    expect(patchMock).toHaveBeenCalledTimes(1);
    expect(patchMock).toHaveBeenLastCalledWith("/api/jobs/501", { priority: "medium" });

    // Odświeżona rekrutacja po pierwszym zapisie (P2) nie cofa przełącznika,
    // dopóki drugi zapis jest w drodze.
    rerenderPanel({ priorityLevel: "p2" });
    expect(priorityOption("Przyjmujemy kandydatów")).toBeChecked();

    releaseFirst();
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(2));
    expect(patchMock).toHaveBeenLastCalledWith("/api/jobs/501", { priority: "low" });
    expect(priorityOption("Przyjmujemy kandydatów")).toBeChecked();
  });

  it("nowa wartość z serwera (zmiana innej osoby) przestawia przełącznik", () => {
    const { rerenderPanel } = renderPanel({ priorityLevel: "p2" });
    expect(priorityOption("P2 Standard")).toBeChecked();

    rerenderPanel({ priorityLevel: "p1" });

    expect(priorityOption("P1 Pilne")).toBeChecked();
    expect(patchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["p1", "P1 Pilne"],
    ["p2", "P2 Standard"],
    ["accepting", "Przyjmujemy kandydatów"],
  ] as const)("bez prawa zmiany poziom %s jest tylko tekstem „%s”", (level, label) => {
    renderPanel({ priorityLevel: level, canSetPriority: false });

    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByText("Priorytet")).toBeInTheDocument();
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
