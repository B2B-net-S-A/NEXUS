/**
 * Ustawienia → System → Integracje (runda 2, 21.10.2026): stan każdego
 * połączenia w jednym wierszu, szczegóły rozwijane, klucze API osobnym
 * ekranem. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/settings/TeamsPrepStatusCard", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/settings/TeamsPrepStatusCard")>()),
  fetchTeamsPrepHealth: async () => "healthy",
  TeamsPrepStatusCard: () => <p>karta prepów</p>,
}));
vi.mock("@/components/settings/JobBoardsCard", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/settings/JobBoardsCard")>()),
  default: () => <p>karta portali</p>,
}));
vi.mock("@/lib/api/jobPortals", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/jobPortals")>()),
  fetchJobBoardConnection: async () => ({ status: "not_connected", boards: [], oauth_configured: false }),
}));

import { IntegrationsSettings } from "./IntegrationsSettings";

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IntegrationsSettings />
    </QueryClientProvider>,
  );
}

describe("IntegrationsSettings", () => {
  it("stan każdego połączenia w wierszu, szczegóły po rozwinięciu, klucze API i wtyczka LinkedIn jako linki", async () => {
    const user = userEvent.setup();
    renderIt();

    const list = screen.getByRole("region", { name: "Połączenia" });
    expect(await within(list).findByText("Działa")).toBeInTheDocument();
    expect(await within(list).findByText("Niepołączone")).toBeInTheDocument();
    const manageLinks = within(list).getAllByRole("link", { name: "Zarządzaj" });
    expect(manageLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/settings/linkedin-extension",
      "/settings/api-keys",
    ]);

    expect(screen.queryByText("karta portali")).toBeNull();
    const [, boards] = within(list).getAllByRole("button", { name: "Szczegóły" });
    await user.click(boards);
    expect(boards).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("karta portali")).toBeInTheDocument();
    expect(screen.queryByText("karta prepów")).toBeNull();
  });
});
