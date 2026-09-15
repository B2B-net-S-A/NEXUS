import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { post: (...a: unknown[]) => post(...a) },
  extractErrorMsg: (e: { response?: { data?: { detail?: string } } }) => e?.response?.data?.detail ?? "Błąd",
}));

import { CvReparseAction } from "@/components/candidates/CvReparseAction";

function renderAction() {
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <CvReparseAction candidateId={42} />
    </QueryClientProvider>,
  );
}

beforeEach(() => { post.mockClear(); });

describe("CvReparseAction (UAT B12)", () => {
  it("queues the reparse and says the data comes after the background read", async () => {
    post.mockResolvedValue({ data: { status: "queued", document_id: 7 } });
    renderAction();
    await userEvent.click(screen.getByRole("button", { name: "Odczytaj CV ponownie" }));
    expect(post).toHaveBeenCalledWith("/api/candidates/42/cv/reparse");
    expect(await screen.findByRole("status")).toHaveTextContent("Odczyt CV uruchomiony");
  });

  it("shows the server's reason when there is no primary CV", async () => {
    post.mockImplementation(() =>
      Promise.reject({ response: { data: { detail: "Kandydat nie ma głównego pliku CV do odczytania." } } }),
    );
    renderAction();
    await userEvent.click(screen.getByRole("button", { name: "Odczytaj CV ponownie" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("głównego pliku CV"),
    );
    expect(screen.getByRole("button", { name: "Odczytaj CV ponownie" })).toBeEnabled();
  });
});
