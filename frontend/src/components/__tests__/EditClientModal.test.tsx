import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EditClientModal } from "@/components/AppShell";
import api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

/**
 * Kontrakt zapisu nazwy klienta (ticket #1 bug 4): edycja pisze do
 * sync-odpornego `display_name` (Traffit nadpisuje `name` codziennie),
 * i TYLKO gdy pole faktycznie zmieniono — bezwarunkowy zapis zamroziłby
 * nazwę względem Traffita przy każdej edycji np. branży.
 */

// GET zwraca nazwę EFEKTYWNĄ w `name` (coalesce(display_name, name)).
const CLIENT = {
  id: 42,
  name: "Acme Sp. z o.o.",
  industry: "IT",
  website: null,
  address: null,
  status: "active",
  nda_signed: false,
  contract_type: null,
  notes: null,
};

function renderModal() {
  return render(
    <EditClientModal client={CLIENT} onClose={() => {}} onSuccess={() => {}} />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
});

describe("EditClientModal — display_name contract", () => {
  it("does not send name nor display_name when the name field is untouched", async () => {
    const user = userEvent.setup();
    renderModal();

    // Zmiana INNEGO pola (branża) — nazwa nietknięta.
    const industry = screen.getByPlaceholderText("IT / Finance...");
    await user.clear(industry);
    await user.type(industry, "Fintech");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(api.patch).mock.calls[0][1] as Record<
      string,
      unknown
    >;
    expect(payload.industry).toBe("Fintech");
    // `name` nigdy nie jest wysyłane; `display_name` tylko przy zmianie.
    expect("name" in payload).toBe(false);
    expect("display_name" in payload).toBe(false);
  });

  it("sends the edited name as display_name (never as name)", async () => {
    const user = userEvent.setup();
    renderModal();

    const nameInput = screen.getByPlaceholderText("Acme Sp. z o.o.");
    await user.clear(nameInput);
    await user.type(nameInput, "Nordea Bank Abp");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith(
      "/api/clients/42",
      expect.objectContaining({ display_name: "Nordea Bank Abp" }),
    );
    const payload = vi.mocked(api.patch).mock.calls[0][1] as Record<
      string,
      unknown
    >;
    expect("name" in payload).toBe(false);
  });

  it("sends display_name: null when the name field is cleared (revert to source)", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.clear(screen.getByPlaceholderText("Acme Sp. z o.o."));
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith(
      "/api/clients/42",
      expect.objectContaining({ display_name: null }),
    );
  });
});
