/**
 * „Akceptuj” w skrzynce „Akceptacje” zawsze potwierdza decyzję (20.10.2026).
 *
 * Szczegół sprawy ma `key` sprawy: po akceptacji lista odświeża się bez niej,
 * szczegół się odmontowuje, a callback przekazany do `mutate()` TanStack Query
 * wtedy pomija — przełożona nie dostawała „Wniosek zaakceptowany” (e2e
 * flow-hr-leave padał na tym niestabilnie).
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-approvals",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrApprovalsPreviewPage from "../hr-approvals/page";

vi.setConfig({ testTimeout: 20_000 });

// Sieć zastąpiona w całości: decyzja przechodzi, a lista do decyzji wraca pusta
// (sprawa zniknęła), jak na serwerze po akceptacji. Reszta odświeżanych zapytań
// kończy się później — `invalidate` w hooku czeka na wszystkie, a lista bez
// sprawy zdąży odmontować szczegół.
const request = vi.spyOn(Axios.prototype, "request").mockImplementation((config) => {
  const { method, url } = config as { method?: string; url?: string };
  if (method?.toLowerCase() === "post" && url?.endsWith("/approve")) {
    return Promise.resolve({ data: { id: "approved", status: "approved", payroll_warning: null } });
  }
  if (method?.toLowerCase() === "post" && url?.endsWith("/reject")) {
    return Promise.resolve({ data: { id: "rejected", status: "rejected", payroll_warning: null } });
  }
  if (url?.endsWith("/approvals/pending")) {
    return Promise.resolve({ data: { items: [], total: 0, covering: [], reported: [] } });
  }
  return new Promise((_, reject) => setTimeout(() => reject(new Error("offline")), 100));
});

afterEach(() => {
  cleanup();
  request.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/hr-approvals — potwierdzenie decyzji", () => {
  it("po „Akceptuj” toast „Wniosek zaakceptowany”, choć sprawa znika z listy", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-approvals");
    render(<HrApprovalsPreviewPage />);

    const detail = await screen.findByRole("region", { name: "Szczegóły: Kamil Testowy" });
    await user.click(within(detail).getByRole("button", { name: "Akceptuj" }));

    expect(await screen.findByText("Wniosek zaakceptowany")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Szczegóły: Kamil Testowy" })).toBeNull();
  });

  it("po „Odrzuć wniosek” toast „Wniosek odrzucony”, choć okno znika razem ze sprawą", async () => {
    // Okno odrzucenia siedzi w szczególe sprawy: po odrzuceniu szczegół się
    // odmontowuje, a callback `mutate()` z okna przepadał (audyt 21.10.2026).
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-approvals");
    render(<HrApprovalsPreviewPage />);

    const detail = await screen.findByRole("region", { name: "Szczegóły: Kamil Testowy" });
    await user.click(within(detail).getByRole("button", { name: "Odrzuć" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Powód/), "Termin koliduje z wdrożeniem");
    await user.click(within(dialog).getByRole("button", { name: "Odrzuć wniosek" }));

    expect(await screen.findByText("Wniosek odrzucony")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Szczegóły: Kamil Testowy" })).toBeNull();
  });
});
