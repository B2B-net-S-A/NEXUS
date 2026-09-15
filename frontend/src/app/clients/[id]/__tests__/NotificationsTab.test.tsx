import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationsTab } from "@/app/clients/[id]/NotificationsTab";

const mocks = vi.hoisted(() => ({
  templatesList: vi.fn(),
  templatesGet: vi.fn(),
  overridesList: vi.fn(),
  overridesCreate: vi.fn(),
  overridesUpdate: vi.fn(),
  overridesDelete: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn() },
  pipelineTemplatesApi: {
    list: (...args: unknown[]) => mocks.templatesList(...args),
    get: (...args: unknown[]) => mocks.templatesGet(...args),
  },
  clientNotificationOverridesApi: {
    list: (...args: unknown[]) => mocks.overridesList(...args),
    create: (...args: unknown[]) => mocks.overridesCreate(...args),
    update: (...args: unknown[]) => mocks.overridesUpdate(...args),
    delete: (...args: unknown[]) => mocks.overridesDelete(...args),
  },
}));

const CLIENT_ID = 42;

function stage(id: number, name: string) {
  return { id, name, template_id: 1, order: id };
}

const TEMPLATE = {
  id: 1,
  name: "Default B2B",
  is_default: true,
  stages: [stage(10, "Screening"), stage(11, "CV Wysłane")],
};

function override(overrides: Record<string, unknown> = {}) {
  return {
    id: 500,
    client_id: CLIENT_ID,
    stage_def_id: 11,
    recipient_type: "job_recruiter",
    specific_user_id: null,
    role: null,
    notify_inapp: true,
    notify_email: true,
    is_active: true,
    ...overrides,
  };
}

function mockLoad(overrideRows: unknown[] = [], templates = [TEMPLATE]) {
  mocks.templatesList.mockResolvedValue({
    data: templates.map(({ id, name }) => ({ id, name })),
  });
  mocks.templatesGet.mockImplementation((id: number) =>
    Promise.resolve({ data: templates.find((t) => t.id === id) }),
  );
  mocks.overridesList.mockResolvedValue({ data: overrideRows });
}

function stageRow(name: string) {
  const label = screen.getByText(name, { selector: "span" });
  return label.closest("div.rounded-md") as HTMLElement;
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NotificationsTab", () => {
  it("pokazuje stan ładowania do czasu odpowiedzi", async () => {
    let resolveList!: (v: unknown) => void;
    mocks.templatesList.mockReturnValue(new Promise((r) => (resolveList = r)));
    mocks.overridesList.mockResolvedValue({ data: [] });

    render(<NotificationsTab clientId={CLIENT_ID} />);

    expect(screen.getByText("Ładuję reguły powiadomień…")).toBeInTheDocument();
    await act(async () => resolveList({ data: [] }));
    expect(screen.queryByText("Ładuję reguły powiadomień…")).toBeNull();
    expect(mocks.overridesList).toHaveBeenCalledWith(CLIENT_ID);
  });

  it("awaria pobrania renderuje błąd, a nie pusty stan", async () => {
    mocks.templatesList.mockResolvedValue({ data: [{ id: 1, name: "X" }] });
    mocks.templatesGet.mockResolvedValue({ data: TEMPLATE });
    mocks.overridesList.mockRejectedValue(new Error("503"));

    render(<NotificationsTab clientId={CLIENT_ID} />);

    expect(await screen.findByText("Nie udało się pobrać reguł.")).toBeInTheDocument();
    expect(screen.queryByText("Brak procesów rekrutacyjnych w systemie.")).toBeNull();
    expect(screen.queryByText("Powiadomienia per stage")).toBeNull();
  });

  it("brak procesów → komunikat pustego stanu", async () => {
    mockLoad([], []);

    render(<NotificationsTab clientId={CLIENT_ID} />);

    expect(
      await screen.findByText("Brak procesów rekrutacyjnych w systemie."),
    ).toBeInTheDocument();
  });

  it("renderuje procesy, etapy i aktywne override'y", async () => {
    mockLoad([
      override(),
      override({ id: 501, recipient_type: "role", role: "tac", notify_email: false, is_active: false }),
    ]);

    render(<NotificationsTab clientId={CLIENT_ID} />);

    expect(await screen.findByText(/Proces: Default B2B/)).toBeInTheDocument();
    expect(screen.getByText("(domyślny)")).toBeInTheDocument();

    const screening = stageRow("Screening");
    expect(within(screening).getByText("Baseline z procesu „Default B2B\"")).toBeInTheDocument();

    const cvSent = stageRow("CV Wysłane");
    expect(
      within(cvSent).getByText("Override aktywny (2) — baseline pominięty"),
    ).toBeInTheDocument();
    expect(within(cvSent).getByText("Rekruter projektu")).toBeInTheDocument();
    expect(within(cvSent).getByText(/Rola \(wszyscy aktywni\) · tac/)).toBeInTheDocument();
    expect(within(cvSent).getByText("(wyłączony)")).toBeInTheDocument();
  });

  it("dodaje override dla etapu i przeładowuje listę", async () => {
    mockLoad([]);
    mocks.overridesCreate.mockResolvedValue({ data: override({ stage_def_id: 10 }) });

    render(<NotificationsTab clientId={CLIENT_ID} />);
    await screen.findByText(/Proces: Default B2B/);

    const screening = stageRow("Screening");
    fireEvent.click(within(screening).getByRole("button", { name: "Dodaj override" }));
    // Formularz ma własny przycisk o tej samej etykiecie — to on zapisuje.
    const saveButtons = within(screening).getAllByRole("button", { name: "Dodaj override" });
    expect(saveButtons).toHaveLength(2);
    fireEvent.click(within(screening).getByRole("checkbox", { name: "Email" }));
    fireEvent.click(saveButtons[1]);

    await waitFor(() => expect(mocks.overridesCreate).toHaveBeenCalledTimes(1));
    expect(mocks.overridesCreate).toHaveBeenCalledWith(CLIENT_ID, {
      recipient_type: "job_recruiter",
      specific_user_id: null,
      role: null,
      notify_inapp: true,
      notify_email: true,
      is_active: true,
      stage_def_id: 10,
    });
    await waitFor(() => expect(mocks.overridesList).toHaveBeenCalledTimes(2));
  });

  it("błąd zapisu override'u zostaje w formularzu z komunikatem backendu", async () => {
    mockLoad([]);
    mocks.overridesCreate.mockRejectedValue({
      response: { status: 422, data: { detail: "Taki override już istnieje" } },
    });

    render(<NotificationsTab clientId={CLIENT_ID} />);
    await screen.findByText(/Proces: Default B2B/);

    const screening = stageRow("Screening");
    fireEvent.click(within(screening).getByRole("button", { name: "Dodaj override" }));
    fireEvent.click(
      within(screening).getAllByRole("button", { name: "Dodaj override" })[1],
    );

    expect(await screen.findByText("Taki override już istnieje")).toBeInTheDocument();
    expect(mocks.overridesList).toHaveBeenCalledTimes(1);
  });

  it("usuwa override po potwierdzeniu, a anulowanie nic nie wysyła", async () => {
    mockLoad([override()]);
    mocks.overridesDelete.mockResolvedValue({});
    const confirmMock = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
    vi.stubGlobal("confirm", confirmMock);

    render(<NotificationsTab clientId={CLIENT_ID} />);
    await screen.findByText(/Proces: Default B2B/);

    fireEvent.click(screen.getByTitle("Usuń"));
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(mocks.overridesDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTitle("Usuń"));
    await waitFor(() =>
      expect(mocks.overridesDelete).toHaveBeenCalledWith(CLIENT_ID, 500),
    );
    await waitFor(() => expect(mocks.overridesList).toHaveBeenCalledTimes(2));
  });

  it("nieudane usunięcie informuje użytkownika", async () => {
    mockLoad([override()]);
    mocks.overridesDelete.mockRejectedValue({ response: { status: 403 } });
    vi.stubGlobal("confirm", vi.fn(() => true));
    const alertMock = vi.fn();
    vi.stubGlobal("alert", alertMock);

    render(<NotificationsTab clientId={CLIENT_ID} />);
    await screen.findByText(/Proces: Default B2B/);

    fireEvent.click(screen.getByTitle("Usuń"));

    await waitFor(() => expect(alertMock).toHaveBeenCalledWith("Nie udało się usunąć."));
    expect(mocks.overridesList).toHaveBeenCalledTimes(1);
  });
});
