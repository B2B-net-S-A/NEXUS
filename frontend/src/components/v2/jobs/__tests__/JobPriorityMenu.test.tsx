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

function renderMenu(level: PriorityLevel, canSet: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <JobPriorityMenu jobId={42} level={level} canSet={canSet} />
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
});
