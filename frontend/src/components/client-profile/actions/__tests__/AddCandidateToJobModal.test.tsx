import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { AddCandidateToJobModal } from "@/components/client-profile/actions/AddCandidateToJobModal";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: (...args: unknown[]) => mocks.post(...args),
  },
}));

// Runda 6 audytu (G2): awaria wyszukiwania kandydata pokazywała „Brak
// wyników” (czyli „nie ma takiej osoby”), a dodanie do rekrutacji nie
// odświeżało Tablicy tej rekrutacji.
function renderModal(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AddCandidateToJobModal
          jobId={101}
          jobTitle="Security Engineer"
          clientId={7}
          onClose={vi.fn()}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function typeQuery(value: string) {
  fireEvent.change(
    screen.getByPlaceholderText("Szukaj po imieniu, emailu, skillu..."),
    { target: { value } },
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
});

describe("AddCandidateToJobModal", () => {
  it("awaria wyszukiwania to komunikat błędu, nie „Brak wyników”", async () => {
    mocks.get.mockRejectedValue({
      response: { status: 503, data: { detail: "Baza chwilowo niedostępna" } },
    });
    renderModal(new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    typeQuery("Jan");

    expect(await screen.findByText(/Baza chwilowo niedostępna/)).toBeInTheDocument();
    expect(screen.queryByText(/Brak wyników/)).not.toBeInTheDocument();
  });

  it("pusta lista nadal mówi „Brak wyników”", async () => {
    mocks.get.mockResolvedValue({ data: { items: [] } });
    renderModal(new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    typeQuery("Jan");

    expect(await screen.findByText(/Brak wyników/)).toBeInTheDocument();
  });

  it("po dodaniu unieważnia oba klucze kanbana rekrutacji", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue({
      data: { items: [{ id: 5, name: "Jan", lastname: "Kowalski" }] },
    });
    mocks.post.mockResolvedValue({ data: {} });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    renderModal(queryClient);
    typeQuery("Jan");

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));

    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "101"] }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 101] });
  });
});
