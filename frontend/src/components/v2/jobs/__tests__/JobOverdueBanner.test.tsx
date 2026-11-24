import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const update = vi.fn();
const changeWorkStates = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({ jobsApi: { update: (...a: unknown[]) => update(...a) } }));
vi.mock("@/lib/api/requestAllocation", () => ({
  changeWorkStates: (...a: unknown[]) => changeWorkStates(...a),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

import { JobOverdueBanner, overdueAgoText } from "@/components/v2/jobs/JobOverdueBanner";

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const props = {
  jobId: 42,
  deadline: "2026-11-19",
  today: "2026-11-24",
  onClose: vi.fn(),
  onChanged: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  update.mockResolvedValue({ data: {} });
  changeWorkStates.mockResolvedValue({ changed: [42], unchanged: 0 });
});

describe("JobOverdueBanner (24.11.2026)", () => {
  it("mówi, kiedy minął termin, i daje trzy decyzje Delivery Leadowi", () => {
    wrap(<JobOverdueBanner {...props} canMarkClientSilent />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Termin minął 19.11 (5 dni temu). Rekrutacja nie jest już „Szukamy”, tylko „Po terminie”.",
    );
    for (const name of ["Klient przedłużył…", "Klient milczy", "Zamknij…"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Zamknij…" }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("bez uprawnienia do stanu pracy nie pokazuje „Klient milczy”", () => {
    wrap(<JobOverdueBanner {...props} canMarkClientSilent={false} />);
    expect(screen.queryByRole("button", { name: "Klient milczy" })).not.toBeInTheDocument();
  });

  it("nowy termin zapisuje tylko datę od dziś wzwyż", async () => {
    wrap(<JobOverdueBanner {...props} canMarkClientSilent />);
    fireEvent.click(screen.getByRole("button", { name: "Klient przedłużył…" }));
    const input = screen.getByLabelText("Nowy termin od klienta");
    const save = screen.getByRole("button", { name: "Zapisz termin" });
    expect(save).toBeDisabled();

    fireEvent.change(input, { target: { value: "2026-11-20" } });
    expect(save).toBeDisabled();

    fireEvent.change(input, { target: { value: "2026-12-05" } });
    fireEvent.click(save);
    await waitFor(() => expect(update).toHaveBeenCalledWith(42, { deadline: "2026-12-05" }));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalled());
    expect(showSuccess).toHaveBeenCalledWith("Nowy termin 05.12 — rekrutacja wraca do „Szukamy”.");
  });

  it("„Klient milczy” zapisuje stan pracy, błąd idzie do komunikatu", async () => {
    changeWorkStates.mockRejectedValueOnce(new Error("boom"));
    wrap(<JobOverdueBanner {...props} canMarkClientSilent />);
    fireEvent.click(screen.getByRole("button", { name: "Klient milczy" }));
    await waitFor(() =>
      expect(changeWorkStates).toHaveBeenCalledWith([{ job_id: 42, state: "client_silent" }]),
    );
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(props.onChanged).not.toHaveBeenCalled();
  });

  it("dzień po terminie to „wczoraj”", () => {
    expect(overdueAgoText("2026-11-23", "2026-11-24")).toBe("wczoraj");
    expect(overdueAgoText("2026-10-05", "2026-11-24")).toBe("50 dni temu");
  });
});
