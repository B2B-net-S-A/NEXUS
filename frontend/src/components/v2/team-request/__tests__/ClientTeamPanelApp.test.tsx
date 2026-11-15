import { readFileSync } from "node:fs";
import { join } from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { TeamPanelTransport } from "@/lib/api/clientTeamPanel";

import { ClientTeamPanelApp } from "../ClientTeamPanelApp";
import { fictionalTeam } from "./team-fixtures";

function renderTeam(transport: TeamPanelTransport) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ClientTeamPanelApp token="zzzzzzzzzzzzzzzz" transport={transport} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function transport(overrides: Partial<TeamPanelTransport> = {}): TeamPanelTransport {
  return {
    fetchTeam: () => Promise.resolve(fictionalTeam()),
    sendSelection: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
}

describe("panel klienta dla zespołu", () => {
  it("pokazuje stanowiska, cenę od–do i skład startowy", async () => {
    renderTeam(transport());
    expect(await screen.findByText("Zespół testowy, 3 osoby")).toBeInTheDocument();
    const band = screen.getByTestId("team-price-band");
    // Od: 120 + 2×100 = 320 zł/h, do: 140 + 2×100 = 340 zł/h, razy 168 h.
    expect(within(band).getByText(/od 54 tys\. zł do 57 tys\. zł/)).toBeInTheDocument();
    // Start: Analityk a1 (od zaraz, 140), Tester t1 i t3 (najwcześniej) = 340 zł/h.
    expect(within(band).getByTestId("team-selection-month")).toHaveTextContent("57 120 zł / mies.");
  });

  it("klik w alternatywę podmienia osobę i przelicza cenę", async () => {
    const user = userEvent.setup();
    renderTeam(transport());
    await screen.findByText("Zespół testowy, 3 osoby");
    await user.click(screen.getByTestId("alt-a2"));
    // 120 + 2×100 = 320 zł/h × 168 = 53 760 zł.
    expect(screen.getByTestId("team-selection-month")).toHaveTextContent("53 760 zł / mies.");
    expect(screen.getByTestId("alt-a2")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("alt-a1")).toHaveAttribute("aria-pressed", "false");
  });

  it("bez stawek w panelu nie ma ceny zespołu", async () => {
    const team = fictionalTeam();
    for (const position of team.positions) {
      position.view.panel.show_rate = false;
      for (const candidate of position.view.candidates) candidate.rate = null;
    }
    renderTeam(transport({ fetchTeam: () => Promise.resolve(team) }));
    await screen.findByText("Zespół testowy, 3 osoby");
    expect(screen.queryByText("Cena zespołu")).not.toBeInTheDocument();
    expect(screen.queryByText(/zł\/h/)).not.toBeInTheDocument();
  });

  it("nieaktualny link to komunikat, nie pusta lista", async () => {
    renderTeam(
      transport({ fetchTeam: () => Promise.reject({ response: { status: 404, data: { detail: "x" } } }) }),
    );
    expect(await screen.findByText("Ten link jest nieaktualny, napisz do opiekuna procesu")).toBeInTheDocument();
    expect(screen.queryByText("Ponów")).not.toBeInTheDocument();
  });

  it("awaria serwera ma „Ponów”", async () => {
    renderTeam(transport({ fetchTeam: () => Promise.reject(new Error("boom")) }));
    expect(await screen.findByText("Nie udało się otworzyć panelu")).toBeInTheDocument();
    expect(screen.getByText("Ponów")).toBeInTheDocument();
  });

  it("„Wyślij skład” wysyła klucze stanowisk i identyfikatory z linku", async () => {
    const user = userEvent.setup();
    const sendSelection = vi.fn(() => Promise.resolve());
    renderTeam(transport({ sendSelection }));
    await screen.findByText("Zespół testowy, 3 osoby");
    await user.click(screen.getByRole("button", { name: "Wyślij skład opiekunowi" }));
    await user.type(screen.getByLabelText("Twoje imię"), "Anna");
    await user.type(screen.getByLabelText("Twój e-mail"), "anna@firma.example");
    await user.click(screen.getByRole("button", { name: "Wyślij skład" }));
    await waitFor(() => expect(sendSelection).toHaveBeenCalledTimes(1));
    expect(sendSelection).toHaveBeenCalledWith({
      author_name: "Anna",
      author_email: "anna@firma.example",
      picks: { aaaaaaaaaaaaaaaa: ["a1"], bbbbbbbbbbbbbbbb: ["t1", "t3"] },
      note: undefined,
    });
  });
});

describe("panel zespołu: granica publiczna", () => {
  const SRC = join(process.cwd(), "src");
  it("ekran klienta i jego logika nie importują klienta API z tokenem", () => {
    for (const file of [
      "components/v2/team-request/ClientTeamPanelApp.tsx",
      "components/v2/team-request/team-logic.ts",
      "lib/api/clientTeamPanel.ts",
    ]) {
      const source = readFileSync(join(SRC, file), "utf8");
      expect(source, file).not.toMatch(/from\s+["']@\/lib\/api["']|jobTeams["']/);
      expect(source, file).not.toMatch(/Authorization|getAccessToken/);
    }
  });

  it("strona ma noindex i nie oddaje adresu w Refererze", () => {
    const source = readFileSync(join(SRC, "app/k/z/[token]/page.tsx"), "utf8");
    expect(source).toMatch(/index:\s*false/);
    expect(source).toMatch(/referrer:\s*"no-referrer"/);
  });
});
