/**
 * „Szuka aktywnie” zmieniane jednym kliknięciem (18.11.2026): uprawnienie jak
 * w oknie „Dostępność” (fakty profilu + zapis kandydata), zapis od razu.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  caps: new Set<string>(),
  patch: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapability: (cap: string) => mocks.caps.has(cap),
}));
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { patch: (...args: unknown[]) => mocks.patch(...args) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

import { AvailabilityStatusPicker } from "@/components/v2/candidates/AvailabilityStatusPicker";

function renderPicker(status: string | null) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AvailabilityStatusPicker candidateId={30909} status={status} />
    </QueryClientProvider>,
  );
}

describe("AvailabilityStatusPicker", () => {
  beforeEach(() => {
    mocks.caps = new Set(["candidate.profile_fact.manage", "candidate.write"]);
    mocks.patch.mockReset();
    mocks.showError.mockReset();
  });

  it("bez prawa zapisu kandydata zostaje sama pigułka", () => {
    mocks.caps = new Set(["candidate.profile_fact.manage"]);
    renderPicker("actively_looking");
    expect(screen.getByText("Szuka aktywnie")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Czy szuka pracy — zmień" })).toBeNull();
  });

  it("bez prawa do faktów profilu i bez statusu nic się nie rysuje", () => {
    mocks.caps = new Set(["candidate.write"]);
    const { container } = renderPicker(null);
    expect(container.textContent).toBe("");
  });

  it("klik w pigułkę i wybór „Nie szuka” zapisuje status od razu", async () => {
    mocks.patch.mockResolvedValue({ data: {} });
    renderPicker("actively_looking");
    fireEvent.click(screen.getByRole("button", { name: "Czy szuka pracy — zmień" }));
    const options = screen.getAllByRole("radio");
    expect(options).toHaveLength(4);
    expect(options[0].getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("radio", { name: /Nie szuka/ }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/candidates/30909", {
        availability_status: "not_looking",
      }),
    );
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalled());
  });

  it("bez statusu pokazuje „+ Czy szuka?”, a błąd zapisu idzie do komunikatu", async () => {
    mocks.patch.mockRejectedValue(new Error("boom"));
    renderPicker("unknown");
    fireEvent.click(screen.getByRole("button", { name: "Czy szuka pracy — zmień" }));
    expect(screen.getAllByText("+ Czy szuka?").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("radio", { name: /Otwarty na oferty/ }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalled());
  });
});
