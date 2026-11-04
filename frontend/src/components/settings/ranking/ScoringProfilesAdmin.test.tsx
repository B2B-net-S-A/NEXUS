import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Decyzja Artura 22.10.2026 (audyt F60): stary edytor tworzy tylko profile
// klienta albo osoby; wagi ogólne zmienia wyłącznie panel z pomiarem.

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  scoringWeightsApi: {
    list: () => mocks.list(),
    create: (payload: unknown) => mocks.create(payload),
    update: (id: number, payload: unknown) => mocks.update(id, payload),
    remove: (id: number) => mocks.remove(id),
  },
}));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => true, confirmDialog: null }),
}));

import { ScoringProfilesAdmin } from "./ScoringProfilesAdmin";

const WEIGHTS = {
  semantic: 60,
  skills: 10,
  salary: 15,
  location: 5,
  availability: 0,
  champion_fit: 10,
};

const GENERAL = {
  id: 1,
  name: "Wagi ogólne (panel)",
  user_id: null,
  client_id: null,
  weights: { ...WEIGHTS, semantic: 49.0909, skills: 20.9091 },
  active: true,
  created_at: "2026-10-21T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
};

const CLIENT = {
  ...GENERAL,
  id: 2,
  name: "Bankowość",
  client_id: 5,
  weights: WEIGHTS,
};

function renderAdmin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ScoringProfilesAdmin />
    </QueryClientProvider>,
  );
}

describe("ScoringProfilesAdmin — tylko profile klienta albo osoby", () => {
  beforeEach(() => {
    mocks.apiGet.mockReset();
    mocks.list.mockReset();
    mocks.create.mockReset();
    mocks.apiGet.mockImplementation(async (url: string) =>
      url === "/api/users"
        ? {
            data: [
              { id: 7, name: "Olga Rekrutacyjna", is_active: true },
              { id: 8, name: "Konto Wyłączone", is_active: false },
            ],
          }
        : { data: [] },
    );
    mocks.list.mockResolvedValue({ data: [GENERAL, CLIENT] });
    mocks.create.mockResolvedValue({ data: { ...CLIENT, id: 3 } });
  });

  it("profil ogólny jest tylko do odczytu i odsyła do panelu", async () => {
    renderAdmin();
    const general = await screen.findByTestId("scoring-weight-profile-1");
    expect(within(general).queryByRole("button", { name: "Edytuj" })).toBeNull();
    expect(within(general).queryByTitle("Usuń")).toBeNull();
    expect(general).toHaveTextContent("zmienia się w panelu");

    const client = screen.getByTestId("scoring-weight-profile-2");
    expect(within(client).getByRole("button", { name: "Edytuj" })).toBeInTheDocument();
  });

  it("nowy profil wymaga klienta albo osoby i wysyła zakres", async () => {
    renderAdmin();
    fireEvent.click(await screen.findByTestId("add-scoring-weight-profile"));

    const save = screen.getByRole("button", { name: "Utwórz profil" });
    expect(save).toBeDisabled();

    fireEvent.click(screen.getByRole("radio", { name: "Osoba" }));
    const person = await screen.findByRole("combobox", { name: "Osoba" });
    await within(person).findByText("Olga Rekrutacyjna");
    expect(within(person).queryByText("Konto Wyłączone")).toBeNull();
    fireEvent.change(person, { target: { value: "7" } });
    expect(save).toBeEnabled();

    fireEvent.click(save);
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const payload = mocks.create.mock.calls[0][0];
    expect(payload).toMatchObject({ user_id: 7 });
    expect(payload.client_id ?? null).toBeNull();
  });
});
