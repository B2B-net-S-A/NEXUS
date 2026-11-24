/**
 * Numer kandydata na górze okna debriefu (prośba zespołu 24.11.2026): debrief
 * robi się przez telefon po rozmowie u klienta, a numeru nie było w oknie.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import { DebriefDialog } from "@/components/calendar/cycle/DebriefDialog";

function renderDialog(extra: Partial<React.ComponentProps<typeof DebriefDialog>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <DebriefDialog
        open
        onOpenChange={vi.fn()}
        eventId={null}
        pair={{ candidateId: 5, jobId: 22 }}
        title="Debrief po rozmowie u klienta"
        {...extra}
      />
    </QueryClientProvider>,
  );
}

const candidateCalls = () =>
  mocks.get.mock.calls.filter(([url]) => String(url).startsWith("/api/candidates/"));

describe("DebriefDialog — telefon kandydata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: url === "/api/candidates/5" ? { id: 5, phone: "500100200" } : null,
      }),
    );
  });

  it("pokazuje numer podany przez wołającego bez pytania o profil", async () => {
    renderDialog({ candidatePhone: "+48 601 202 303" });
    const dialog = await screen.findByRole("dialog");
    const line = within(dialog).getByTestId("debrief-candidate-phone");
    expect(within(line).getByRole("link", { name: /601 202 303/ })).toHaveAttribute(
      "href",
      expect.stringMatching(/^tel:/),
    );
    expect(within(line).getByRole("button", { name: "Kopiuj" })).toBeInTheDocument();
    expect(candidateCalls()).toHaveLength(0);
  });

  it("kandydat bez numeru: nie ma wiersza i nie ma zapytania o profil", async () => {
    renderDialog({ candidatePhone: null });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByTestId("debrief-candidate-phone")).toBeNull();
    expect(candidateCalls()).toHaveLength(0);
  });

  it("bramka bez numeru od wołającego czyta go z profilu kandydata", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await waitFor(() =>
      expect(within(dialog).getByTestId("debrief-candidate-phone")).toHaveTextContent(/500 100 200/),
    );
    expect(candidateCalls()).toEqual([["/api/candidates/5"]]);
  });

  it("profil bez numeru albo błąd odczytu: okno działa bez wiersza", async () => {
    mocks.get.mockImplementation((url: string) =>
      url.startsWith("/api/candidates/")
        ? Promise.reject(new Error("403"))
        : Promise.resolve({ data: null }),
    );
    renderDialog();
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(candidateCalls()).toHaveLength(1));
    expect(within(dialog).queryByTestId("debrief-candidate-phone")).toBeNull();
    expect(within(dialog).getByText("Co mówił kandydat?")).toBeInTheDocument();
  });
});
