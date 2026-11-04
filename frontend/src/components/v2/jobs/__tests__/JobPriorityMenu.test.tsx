/**
 * Plakietka priorytetu przed tytułem rekrutacji (14.10.2026, makiety A2/A4/K1):
 * ta sama krótka nazwa co na liście, menu z trzema poziomami dla osób
 * z prawem zmiany, sama plakietka dla pozostałych.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobPriorityMenu } from "@/components/v2/jobs/JobPriorityMenu";
import type { PriorityLevel } from "@/lib/request-priority";

const patchMock = vi.fn();
const toast = vi.hoisted(() => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { patch: (...args: unknown[]) => patchMock(...args) },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

function renderMenu(
  level: PriorityLevel,
  canSet: boolean,
  team?: { workingNames?: readonly string[]; closed?: boolean },
  paused?: boolean,
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <JobPriorityMenu jobId={42} level={level} canSet={canSet} team={team} paused={paused} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

const chip = () => screen.getByTestId("job-header-priority");

describe("JobPriorityMenu", () => {
  beforeEach(() => {
    patchMock.mockReset();
    toast.showError.mockReset();
  });

  it("bez prawa: sama plakietka z dymkiem, kto zmienia priorytet — bez menu", () => {
    renderMenu("p1", false);
    expect(chip().tagName).toBe("SPAN");
    expect(chip()).toHaveTextContent("P1");
    expect(chip()).toHaveAttribute(
      "title",
      "P1 Pilne. Priorytet zmienia Delivery Lead albo Head of Recruitment.",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("P1 wstrzymany przez championa: szara plakietka z pauzą, w menu zdanie dlaczego (D6)", async () => {
    const hint = "P1 wstrzymany, bo mamy championa. Wróci, gdy odpadnie ostatni champion.";
    renderMenu("p1", true, undefined, true);
    expect(chip()).toHaveAttribute("data-paused", "true");
    expect(chip()).toHaveTextContent("P1");
    expect(chip().className).toContain("border-dashed");
    expect(chip().className).not.toContain("bg-destructive-muted");
    await userEvent.click(chip());
    const menu = await screen.findByTestId("job-priority-menu");
    expect(within(menu).getByTestId("job-priority-paused-note")).toHaveTextContent(hint);
  });

  it("wstrzymany P1 bez prawa zmiany: ten sam wariant i dymek z powodem", () => {
    renderMenu("p1", false, undefined, true);
    expect(chip().tagName).toBe("SPAN");
    expect(chip()).toHaveAttribute("data-paused", "true");
    expect(chip().getAttribute("title")).toContain("P1 wstrzymany, bo mamy championa.");
  });

  it("„Bez priorytetu” też stoi w nagłówku — pole widać, choć na liście nie ma plakietki", () => {
    renderMenu("p2", false);
    expect(chip()).toHaveTextContent("Bez priorytetu");
  });

  it("z prawem: menu z trzema poziomami i zdaniem, co poziom robi", async () => {
    renderMenu("p1", true);
    expect(chip()).toHaveAccessibleName(/Priorytet: P1 Pilne/);
    await userEvent.click(chip());
    const menu = await screen.findByTestId("job-priority-menu");
    expect(
      within(menu)
        .getAllByRole("menuitemradio")
        .map((item) => item.getAttribute("data-testid")),
    ).toEqual([
      "job-priority-option-p1",
      "job-priority-option-p2",
      "job-priority-option-accepting",
    ]);
    expect(within(menu).getByTestId("job-priority-option-p1")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(menu).toHaveTextContent("Gdy nikt nie pracuje, automat proponuje rekrutera.");
    expect(menu).toHaveTextContent("Zmienia Delivery Lead, Head of Recruitment i administrator.");
  });

  it("wybór zapisuje od razu (`PATCH {priority}`) i odświeża obsadę wszędzie", async () => {
    patchMock.mockResolvedValue({ data: {} });
    const { invalidate } = renderMenu("p1", true);
    await userEvent.click(chip());
    await userEvent.click(await screen.findByTestId("job-priority-option-accepting"));
    expect(chip()).toHaveTextContent("Przyjmujemy");
    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/42", { priority: "low" }),
    );
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["jobs-v2"] })),
    );
  });

  it("odmowa serwera cofa plakietkę i mówi dlaczego", async () => {
    patchMock.mockRejectedValue({ response: { status: 403, data: { detail: "Brak uprawnień." } } });
    renderMenu("p1", true);
    await userEvent.click(chip());
    await userEvent.click(await screen.findByTestId("job-priority-option-p2"));
    await waitFor(() => expect(toast.showError).toHaveBeenCalled());
    expect(chip()).toHaveTextContent("P1");
  });

  it("ponowny wybór bieżącego poziomu niczego nie zapisuje", async () => {
    renderMenu("p1", true);
    await userEvent.click(chip());
    await userEvent.click(await screen.findByTestId("job-priority-option-p1"));
    expect(patchMock).not.toHaveBeenCalled();
  });

  it("zejście z P1 pyta o potwierdzenie — zespół przejdzie do „Poprzedni rekruter” (14.10.2026)", async () => {
    patchMock.mockResolvedValue({ data: {} });
    renderMenu("p1", true, { workingNames: ["Anna Kowalska"] });

    await userEvent.click(chip());
    await userEvent.click(await screen.findByTestId("job-priority-option-p2"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Anna Kowalska przejdzie do „Poprzedni rekruter”",
    );
    expect(patchMock).not.toHaveBeenCalled();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Zmień na „Bez priorytetu”" }),
    );
    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/42", { priority: "medium" }),
    );
  });
});

describe("JobPriorityMenu — P0 (27.10.2026)", () => {
  const p0 = { is_p0: true, p0_until: new Date(Date.now() + 23 * 3_600_000 + 60_000).toISOString(), p0_reason: "Klient chce 2 CV", status: "published" };

  function renderP0(canSet: boolean, canSetP0: boolean, source: typeof p0 | null = p0) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobPriorityMenu jobId={42} level="p1" canSet={canSet} p0={source} canSetP0={canSetP0} jobTitle="Konsultant GCP" />
      </QueryClientProvider>,
    );
  }

  it("aktywne P0 zastępuje plakietkę poziomu także bez prawa zmiany", () => {
    renderP0(false, false);
    expect(chip()).toHaveAttribute("data-priority", "p0");
    expect(screen.getByTestId("p0-chip")).toHaveTextContent("P0 · 23 h");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("Delivery Lead (bez can_set_p0) nie widzi opcji P0 w menu", async () => {
    renderP0(true, false, null);
    await userEvent.click(chip());
    expect(await screen.findByTestId("job-priority-menu")).toBeInTheDocument();
    expect(screen.queryByTestId("job-priority-option-p0")).toBeNull();
  });

  it("Head of Recruitment: opcja P0 otwiera okno z powodem", async () => {
    renderP0(true, true, null);
    await userEvent.click(chip());
    await userEvent.click(await screen.findByTestId("job-priority-option-p0"));
    const dialog = await screen.findByTestId("set-p0-dialog");
    expect(within(dialog).getByLabelText(/Po co P0/)).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: "24 h" })).toHaveAttribute("aria-checked", "true");
  });

  function renderDl(pending: boolean) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobPriorityMenu
          jobId={42}
          level="p1"
          canSet
          p0={null}
          canSetP0={false}
          canRequestP0
          p0RequestPending={pending}
          jobTitle="Konsultant GCP"
        />
      </QueryClientProvider>,
    );
  }

  it("Delivery Lead tej rekrutacji: „Poproś o P0…” otwiera okno prośby (28.10.2026)", async () => {
    renderDl(false);
    await userEvent.click(chip());
    expect(screen.queryByTestId("job-priority-option-p0")).toBeNull();
    await userEvent.click(await screen.findByTestId("job-priority-option-p0-request"));
    const dialog = await screen.findByTestId("set-p0-dialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Poproś o P0");
    expect(within(dialog).getByRole("button", { name: "Wyślij prośbę" })).toBeInTheDocument();
  });

  it("oczekująca prośba: menu mówi, że czeka na Head of Recruitment", async () => {
    renderDl(true);
    await userEvent.click(chip());
    const option = await screen.findByTestId("job-priority-option-p0-request");
    expect(option).toHaveTextContent("Zmień prośbę o P0");
    expect(option).toHaveTextContent("Twoja prośba czeka na Head of Recruitment.");
  });
});
