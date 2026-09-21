import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StageStrip } from "@/components/v2/recruitment/StageStrip";

import { item, template } from "./recruitment-fixtures";

const columns = template({
  1: [item(1)],
  3: [item(2)],
  4: [item(3), item(4)],
  5: [item(5)],
  10: [item(6)],
});

function renderStrip(over: Partial<React.ComponentProps<typeof StageStrip>> = {}) {
  const onSegmentChange = vi.fn();
  render(
    <StageStrip
      columns={columns}
      openProposalsCount={52}
      shortlistCount={3}
      segment="in-process"
      onSegmentChange={onSegmentChange}
      {...over}
    />,
  );
  return { onSegmentChange, nav: screen.getByRole("navigation", { name: "Etapy rekrutacji" }) };
}

const segmentLabels = (nav: HTMLElement) =>
  within(nav)
    .getAllByRole("button")
    .filter((b) => b.hasAttribute("aria-pressed"))
    .map((b) => b.textContent);

describe("StageStrip", () => {
  it("segmenty w stałej kolejności, z licznikami; „Poza szablonem” tylko gdy ktoś tam jest", () => {
    const { nav } = renderStrip();
    expect(segmentLabels(nav)).toEqual([
      "52Propozycje z bazy",
      "3Shortlista",
      "5W procesie",
      "1Nowi",
      "0Screening",
      "3Zweryfikowani",
      "1U klienta",
      "0Umowa → zatrudnieni",
      "1Odrzuceni",
    ]);
  });

  it("kubełek poza szablonem dostaje segment i wchodzi do „W procesie”", () => {
    const { nav } = renderStrip({ offTemplate: { count: 2, items: [item(8), item(9)] } });
    expect(segmentLabels(nav)).toContain("2Poza szablonem");
    expect(segmentLabels(nav)).toContain("7W procesie");
  });

  it("nieznany licznik propozycji to „—”, nie zero", () => {
    const { nav } = renderStrip({ openProposalsCount: null });
    expect(segmentLabels(nav)[0]).toBe("—Propozycje z bazy");
  });

  it("aria-pressed wskazuje aktywny segment; klik zgłasza segment grupy", async () => {
    const { onSegmentChange } = renderStrip({ segment: "group:client" });
    expect(screen.getByRole("button", { name: /^\d+U klienta$/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /W procesie/ })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: /^\d+Screening/ }));
    expect(onSegmentChange).toHaveBeenCalledWith("group:screening");
    await userEvent.click(screen.getByRole("button", { name: /Odrzuceni/ }));
    expect(onSegmentChange).toHaveBeenCalledWith("closed");
  });

  it("grupa z kilkoma etapami ma menu zawężenia do jednego etapu", async () => {
    const { onSegmentChange } = renderStrip();
    // „Nowi" ma jeden etap — menu nie ma sensu.
    expect(screen.queryByRole("button", { name: /Zawęź „Nowi”/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Zawęź „Zweryfikowani”/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Wysłać do Cpro/ }));
    expect(onSegmentChange).toHaveBeenCalledWith("stage:4");
  });

  it("zawężenie do etapu podświetla segment jego grupy i pokazuje nazwę etapu", () => {
    renderStrip({ segment: "stage:4" });
    const button = screen.getByRole("button", { name: /^2Zweryfikowani.*Wysłać do Cpro$/ });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveTextContent(/^2/);
  });
});
