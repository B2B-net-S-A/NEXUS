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
    sendInterviews: vi.fn(() => Promise.resolve({ created: 3, skipped: [] })),
    ...overrides,
  };
}

describe("panel klienta dla zespołu", () => {
  it("pokazuje stanowiska, cenę od–do i skład startowy", async () => {
    renderTeam(transport());
    expect(await screen.findByText("Zespół testowy, 3 osoby")).toBeInTheDocument();
    expect(screen.getByText(/· 2 stanowiska ·/)).toBeInTheDocument();
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

  it("odrzucony e-mail (422 z walidacji) to zdanie po polsku, nie surowy komunikat API", async () => {
    const user = userEvent.setup();
    const sendSelection = vi.fn(() =>
      Promise.reject({
        response: {
          status: 422,
          data: {
            detail: [
              {
                type: "value_error",
                loc: ["body", "author_email"],
                msg: "value is not a valid email address: An email address must have an @-sign.",
              },
            ],
          },
        },
      }),
    );
    renderTeam(transport({ sendSelection }));
    await screen.findByText("Zespół testowy, 3 osoby");
    await user.click(screen.getByRole("button", { name: "Wyślij skład opiekunowi" }));
    await user.clear(screen.getByLabelText("Twoje imię"));
    await user.type(screen.getByLabelText("Twoje imię"), "Anna");
    await user.clear(screen.getByLabelText("Twój e-mail"));
    await user.type(screen.getByLabelText("Twój e-mail"), "anna@firma.example");
    await user.click(screen.getByRole("button", { name: "Wyślij skład" }));
    expect(
      await screen.findByText("Sprawdź adres e-mail — nie wygląda na poprawny."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/value is not a valid email/)).not.toBeInTheDocument();
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

describe("panel zespołu: kolejność kart", () => {
  it("klik nie przestawia kart, a wybrana osoba spoza pierwszych czterech jest widoczna", async () => {
    const user = userEvent.setup();
    const team = fictionalTeam();
    const extra = ["t4", "t5", "t6"].map((id) => ({
      ...team.positions[1].view.candidates[0],
      public_id: id,
      name: `Osoba ${id}`,
      available_from: "2026-10-01",
    }));
    team.positions[1].view.candidates.push(...extra);
    renderTeam(transport({ fetchTeam: () => Promise.resolve(team) }));
    await screen.findByText("Zespół testowy, 3 osoby");
    const tester = screen.getByTestId("position-bbbbbbbbbbbbbbbb");
    const names = () =>
      Array.from(tester.querySelectorAll("button[aria-pressed]")).map((b) => b.getAttribute("data-testid"));
    // Najwcześniej dostępni (t4, t5) są wybrani, choć stoją za pierwszą czwórką.
    expect(names()).toEqual(["alt-t1", "alt-t2", "alt-t3", "alt-t4", "alt-t5"]);
    await user.click(screen.getByTestId("alt-t2"));
    // Pełne stanowisko: t2 zastępuje ostatnio wybraną (t5), karty stoją w miejscu.
    expect(names()).toEqual(["alt-t1", "alt-t2", "alt-t3", "alt-t4"]);
    expect(screen.getByTestId("alt-t2")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("alt-t4")).toHaveAttribute("aria-pressed", "true");
  });
});

describe("panel zespołu: gotowe składy i rozmowy (Z3)", () => {
  function withVariants() {
    const team = fictionalTeam();
    team.variants = [
      { key: "cheap", name: "Najniższa cena", why: "Najtańsze osoby.", picks: { aaaaaaaaaaaaaaaa: ["a2"], bbbbbbbbbbbbbbbb: ["t1", "t2"] } },
      { key: "fast", name: "Najszybszy start", why: "", picks: { aaaaaaaaaaaaaaaa: ["a1"], bbbbbbbbbbbbbbbb: ["t1", "t3"] } },
    ];
    return team;
  }

  it("bez zatwierdzonych składów nie ma zakładki", async () => {
    renderTeam(transport());
    await screen.findByText("Zespół testowy, 3 osoby");
    expect(screen.queryByRole("tab", { name: /Gotowe składy/ })).not.toBeInTheDocument();
  });

  it("pierwszy zatwierdzony skład jest startowym, wybór innego go podmienia", async () => {
    const user = userEvent.setup();
    renderTeam(transport({ fetchTeam: () => Promise.resolve(withVariants()) }));
    await screen.findByText("Zespół testowy, 3 osoby");
    expect(screen.getByText("Skład: Najniższa cena")).toBeInTheDocument();
    expect(screen.getByTestId("alt-a2")).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("tab", { name: "Gotowe składy (2)" }));
    await user.click(within(screen.getByTestId("variant-fast")).getByRole("button", { name: "Wybierz ten skład" }));
    expect(screen.getByText("Skład: Najszybszy start")).toBeInTheDocument();
    expect(screen.getByTestId("alt-a1")).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByTestId("alt-a2"));
    expect(screen.getByText("Skład ułożony przez Ciebie")).toBeInTheDocument();
  });

  it("rozmowy z całym składem: jedna siatka, prośba dla zaznaczonych osób", async () => {
    const user = userEvent.setup();
    const sendInterviews = vi.fn(() => Promise.resolve({ created: 2, skipped: [] }));
    renderTeam(transport({ sendInterviews }));
    await screen.findByText("Zespół testowy, 3 osoby");
    await user.click(screen.getByRole("button", { name: "Poproś o rozmowy z tym składem (3)" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("checkbox", { name: /Osoba t3/ }));
    const slot = within(dialog).getAllByRole("button", { pressed: false }).find((b) => b.getAttribute("aria-label"));
    await user.click(slot!);
    await user.clear(within(dialog).getByLabelText("Twoje imię"));
    await user.type(within(dialog).getByLabelText("Twoje imię"), "Anna");
    await user.clear(within(dialog).getByLabelText("Twój e-mail"));
    await user.type(within(dialog).getByLabelText("Twój e-mail"), "anna@firma.example");
    await user.click(within(dialog).getByRole("button", { name: "Wyślij prośbę o 2 rozmów" }));
    expect(within(dialog).queryByRole("alert")?.textContent ?? null).toBeNull();
    await waitFor(() => expect(sendInterviews).toHaveBeenCalledTimes(1));
    const body = (sendInterviews.mock.calls[0] as unknown as [{ picks: Record<string, string[]>; slots: unknown[] }])[0];
    expect(body.picks).toEqual({ aaaaaaaaaaaaaaaa: ["a1"], bbbbbbbbbbbbbbbb: ["t1"] });
    expect(body.slots).toHaveLength(1);
  });
});

describe("panel zespołu: szacunek dla stanowiska bez CV (Z4)", () => {
  it("stanowisko bez CV z szacunkiem wchodzi do ceny od–do i jest nazwane", async () => {
    const team = fictionalTeam();
    team.positions.push({
      key: "cccccccccccccccc",
      short: "Architekt",
      headcount: 1,
      view: { ...team.positions[0].view, candidates: [] },
      estimate: { min: 200, max: 220 },
    });
    renderTeam(transport({ fetchTeam: () => Promise.resolve(team) }));
    await screen.findByText("Zespół testowy, 4 osoby");
    const band = screen.getByTestId("team-price-band");
    // (320 + 200) × 168 = 87 360, (340 + 220) × 168 = 94 080.
    expect(within(band).getByText(/od 87 tys\. zł do 94 tys\. zł/)).toBeInTheDocument();
    expect(within(band).getByText(/szacunek dla: Architekt/)).toBeInTheDocument();
    expect(screen.getByText(/Szacunek stawki: 200 zł\/h – 220 zł\/h/)).toBeInTheDocument();
  });
});
