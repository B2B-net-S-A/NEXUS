import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FinanceSection } from "@/components/consultant-portal/FinanceSection";
import { PortalApiError, portalApi, type PortalFinanceStatus, type PortalMonth } from "@/lib/api/consultant-portal";

const smsRequired = () => new PortalApiError(403, { detail: { message: "Potwierdź kod SMS.", code: "sms_required" } });
const month = {
  year: 2026,
  month: 10,
  report_label: "Raport: do wysłania",
  invoice_label: "Faktura: po akceptacji raportu",
  issue_invoice: false,
  action: "send_report",
  documents: [],
} as unknown as PortalMonth;
const status: PortalFinanceStatus = { available: true, message: null, verified: true, phone_hint: "••• 123" };

function renderSection() {
  // Ustawienia jak w QueryProvider: bez odświeżania przy powrocie do karty.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: 0, staleTime: 30_000, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <FinanceSection supportEmail={null} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("FinanceSection po wygaśnięciu kodu SMS", () => {
  it("wysłanie dokumentu po 30 minutach przywraca pole kodu", async () => {
    vi.spyOn(portalApi, "financeStatus").mockResolvedValue(status);
    vi.spyOn(portalApi, "financeOverview").mockResolvedValue({ months: [month] });
    vi.spyOn(portalApi, "upload").mockRejectedValue(smsRequired());
    const user = userEvent.setup();
    renderSection();
    await screen.findByRole("button", { name: /Wyślij raport/ });
    await user.upload(screen.getByLabelText("Wyślij raport"), new File(["x"], "r.pdf", { type: "application/pdf" }));
    expect(await screen.findByRole("button", { name: "Wyślij kod SMS" })).toBeTruthy();
  });

  it("poprawny kod chowa pole i wczytuje miesiące ponownie", async () => {
    vi.spyOn(portalApi, "financeStatus").mockResolvedValue(status);
    const overview = vi
      .spyOn(portalApi, "financeOverview")
      .mockRejectedValueOnce(smsRequired())
      .mockResolvedValue({ months: [month] });
    vi.spyOn(portalApi, "sendCode").mockResolvedValue({ phone_hint: "••• 123" });
    vi.spyOn(portalApi, "verifyCode").mockResolvedValue({ verified: true });
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Wyślij kod SMS" }));
    await user.type(await screen.findByLabelText("Kod SMS"), "123456");
    await user.click(screen.getByRole("button", { name: "Potwierdź" }));
    await waitFor(() => expect(screen.queryByLabelText("Kod SMS")).toBeNull());
    expect(overview.mock.calls.length).toBeGreaterThan(1);
    expect(await screen.findByRole("button", { name: /Wyślij raport/ })).toBeTruthy();
  });
});
