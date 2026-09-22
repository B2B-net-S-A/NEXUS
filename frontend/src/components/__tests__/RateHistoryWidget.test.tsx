import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const showError = vi.fn();
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError }) }));

const list = vi.fn();
const remove = vi.fn();
vi.mock("@/lib/api", () => ({
  phase5Api: {
    rateHistory: {
      list: (...a: unknown[]) => list(...a),
      create: vi.fn(),
      delete: (...a: unknown[]) => remove(...a),
    },
    clientsLookup: () => Promise.resolve({ data: [] }),
  },
}));

import { RateHistoryWidget } from "../RateHistoryWidget";
import { useAuthStore, type User, type UserRole } from "@/store/auth";

function mkUser(role: UserRole): User {
  return {
    id: 3,
    email: `${role}@example.com`,
    name: `Test ${role}`,
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
  } as User;
}

const ROW = {
  id: 7,
  candidate_id: 1,
  rate: 150,
  currency: "PLN",
  contract_type: "b2b",
  start_date: "2026-01-01",
  end_date: null,
  client_id: null,
  job_id: null,
  notes: null,
};

describe("RateHistoryWidget — zapisy tylko dla admina (FE-10)", () => {
  beforeEach(() => {
    list.mockReset();
    remove.mockReset();
    showError.mockReset();
  });
  afterEach(() => {
    act(() => useAuthStore.setState({ user: null }));
  });

  it.each(["delivery_lead", "finance", "recruiter"] as UserRole[])(
    "%s widzi historię bez „Dodaj stawkę” i bez usuwania",
    async (role) => {
      act(() => useAuthStore.setState({ user: mkUser(role), hydrated: true }));
      list.mockResolvedValue({ data: [ROW] });
      render(<RateHistoryWidget candidateId={1} />);
      await screen.findByText("2026-01-01");
      expect(screen.queryByTestId("rate-history-add-toggle")).toBeNull();
      expect(screen.queryByRole("button", { name: "Usuń stawkę" })).toBeNull();
    },
  );

  it("pusty widżet w stopce znika dla roli bez zapisu", async () => {
    act(() => useAuthStore.setState({ user: mkUser("recruiter"), hydrated: true }));
    list.mockResolvedValue({ data: [] });
    const { container } = render(<RateHistoryWidget candidateId={1} hideWhenEmpty />);
    await waitFor(() => expect(list).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("admin może dodać i usunąć; błąd usuwania trafia do toasta", async () => {
    act(() => useAuthStore.setState({ user: mkUser("admin"), hydrated: true }));
    list.mockResolvedValue({ data: [ROW] });
    remove.mockRejectedValue({ response: { status: 403, data: { detail: "Brak uprawnień" } } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<RateHistoryWidget candidateId={1} />);
    await screen.findByText("2026-01-01");
    expect(screen.getByTestId("rate-history-add-toggle")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Usuń stawkę" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(showError.mock.calls[0][0]).toContain("Brak uprawnień");
  });
});
