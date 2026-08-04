import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OwnersTab } from "./OwnersTab";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  getTeam: vi.fn(),
  addTac: vi.fn(),
  removeTac: vi.fn(),
  setTacFirstPriority: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: mocks.get },
  clientTeamApi: {
    get: mocks.getTeam,
    addTac: mocks.addTac,
    removeTac: mocks.removeTac,
    setTacFirstPriority: mocks.setTacFirstPriority,
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
  }),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: { id: 1, role: "admin" } }),
}));

function renderOwners() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OwnersTab clientId={42} />
    </QueryClientProvider>,
  );
}

const createdAt = "2026-08-03T10:00:00Z";

describe("OwnersTab — równorzędni TAC-y", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ data: [] });
    mocks.addTac.mockResolvedValue({ data: { ok: true } });
    mocks.removeTac.mockResolvedValue({ data: undefined });
    mocks.setTacFirstPriority.mockResolvedValue({ data: { ok: true } });
  });

  it("pokazuje osobiste priorytety bez wyznaczania głównego TAC-a klienta", async () => {
    mocks.getTeam.mockResolvedValue({
      data: {
        tacs: [
          {
            id: 10,
            user_id: 7,
            name: "Anna TAC",
            email: "anna@example.com",
            role: "tac",
            created_at: createdAt,
            is_first_priority_for_tac: true,
          },
          {
            id: 11,
            user_id: 8,
            name: "Ola TAC",
            email: "ola@example.com",
            role: "tac",
            created_at: createdAt,
            is_first_priority_for_tac: true,
          },
        ],
        delivery_leads: [],
      },
    });

    const user = userEvent.setup();
    renderOwners();

    expect(await screen.findByText("Anna TAC")).toBeInTheDocument();
    expect(screen.getByText("Ola TAC")).toBeInTheDocument();
    expect(screen.getAllByText("1. priorytet tego TAC-a")).toHaveLength(2);
    expect(screen.queryByText(/primary/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/wszyscy przypisani TAC-owie.*równorzędni/i),
    ).toBeInTheDocument();

    expect(
      screen.getAllByText(
        "Ustaw innego klienta jako priorytet #1 z jego karty",
      ),
    ).toHaveLength(2);

    // Bieżącego priorytetu nie można wyłączyć bez następcy. Promocja klienta
    // odbywa się z karty innego klienta i atomowo demotuje poprzedni.
    expect(mocks.setTacFirstPriority).not.toHaveBeenCalled();
  });

  it("promuje klienta na pierwszy priorytet wyłącznie przez enabled=true", async () => {
    mocks.getTeam.mockResolvedValue({
      data: {
        tacs: [
          {
            id: 11,
            user_id: 8,
            name: "Ola TAC",
            email: "ola@example.com",
            role: "tac",
            created_at: createdAt,
            is_first_priority_for_tac: false,
          },
        ],
        delivery_leads: [],
      },
    });

    const user = userEvent.setup();
    renderOwners();
    await screen.findByText("Ola TAC");
    await user.click(screen.getByRole("button", { name: "Ustaw 1. priorytet" }));

    await waitFor(() =>
      expect(mocks.setTacFirstPriority).toHaveBeenCalledWith(42, 8, {
        enabled: true,
      }),
    );
  });

  it("wyjaśnia konflikt 409 przy usuwaniu priorytetowego klienta TAC-a", async () => {
    mocks.getTeam.mockResolvedValue({
      data: {
        tacs: [
          {
            id: 10,
            user_id: 7,
            name: "Anna TAC",
            email: "anna@example.com",
            role: "tac",
            created_at: createdAt,
            is_first_priority_for_tac: true,
          },
        ],
        delivery_leads: [],
      },
    });
    mocks.removeTac.mockRejectedValue({ response: { status: 409 } });

    const user = userEvent.setup();
    renderOwners();
    await screen.findByText("Anna TAC");
    await user.click(screen.getByTitle("Usuń przypisanie"));

    await waitFor(() =>
      expect(mocks.showError).toHaveBeenCalledWith(
        "Nie można usunąć TAC-a z jego klienta priorytetowego. Najpierw ustaw innego klienta jako priorytet #1 z jego karty.",
      ),
    );
    expect(mocks.removeTac).toHaveBeenCalledTimes(1);
  });

  it("wysyła nową flagę przy dodaniu TAC-a i nie używa is_primary", async () => {
    mocks.getTeam.mockResolvedValue({
      data: { tacs: [], delivery_leads: [] },
    });
    mocks.get.mockResolvedValue({
      data: [
        {
          id: 9,
          name: "Nowy TAC",
          email: "nowy@example.com",
          role: "tac",
          is_active: true,
        },
      ],
    });

    const user = userEvent.setup();
    renderOwners();
    await screen.findByText("Brak przypisanych TAC-ów.");

    await user.click(screen.getByRole("button", { name: "Dodaj TAC" }));
    await user.selectOptions(screen.getByRole("combobox"), "9");
    await user.click(
      screen.getByRole("checkbox", {
        name: "Ustaw tego klienta jako pierwszy priorytet tego TAC-a",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Dodaj" }));

    await waitFor(() =>
      expect(mocks.addTac).toHaveBeenCalledWith(42, {
        user_id: 9,
        is_first_priority_for_tac: true,
      }),
    );
    expect(mocks.addTac.mock.calls[0]?.[1]).not.toHaveProperty("is_primary");
  });

  it("pomija false, aby backend mógł auto-wybrać pierwszy klient TAC-a", async () => {
    mocks.getTeam.mockResolvedValue({
      data: { tacs: [], delivery_leads: [] },
    });
    mocks.get.mockResolvedValue({
      data: [
        {
          id: 9,
          name: "Nowy TAC",
          email: "nowy@example.com",
          role: "tac",
          is_active: true,
        },
      ],
    });

    const user = userEvent.setup();
    renderOwners();
    await screen.findByText("Brak przypisanych TAC-ów.");
    await user.click(screen.getByRole("button", { name: "Dodaj TAC" }));
    await user.selectOptions(screen.getByRole("combobox"), "9");
    await user.click(screen.getByRole("button", { name: "Dodaj" }));

    await waitFor(() =>
      expect(mocks.addTac).toHaveBeenCalledWith(42, { user_id: 9 }),
    );
    expect(mocks.addTac.mock.calls[0]?.[1]).not.toHaveProperty(
      "is_first_priority_for_tac",
    );
  });
});
