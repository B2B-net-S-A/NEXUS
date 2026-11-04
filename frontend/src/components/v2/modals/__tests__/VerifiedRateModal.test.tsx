/**
 * Okno „Przesuń na Zweryfikowany” — R2 (17.10.2026): stawka ponad budżetem,
 * a „Stawka od” mieści się w budżecie → ramka mówi to wprost i „Użyj” ją
 * wpisuje. Dane fikcyjne.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VerifiedRateModal } from "@/components/v2/modals/VerifiedRateModal";

function mount(props: Partial<React.ComponentProps<typeof VerifiedRateModal>> = {}) {
  render(
    <VerifiedRateModal
      open
      onOpenChange={vi.fn()}
      candidateName="Jan Fikcyjny"
      jobBudgetHourly={135}
      initialRateHourly={140}
      rateFromHourly="90.00"
      onConfirm={vi.fn()}
      {...props}
    />,
  );
}

describe("VerifiedRateModal — niższa znana stawka (R2)", () => {
  it("ponad budżet przy „Stawce od” w budżecie — dopisek i „Użyj”", async () => {
    const user = userEvent.setup();
    mount();

    const note = screen.getByTestId("rate-lower-known");
    expect(note).toHaveTextContent("Znana też niższa stawka: 90 zł/h (Stawka od) — mieści się w budżecie.");
    await user.click(within(note).getByRole("button", { name: "Użyj 90 zł/h" }));
    expect(screen.getByLabelText("Kwota")).toHaveValue(90);
    expect(screen.queryByTestId("rate-lower-known")).toBeNull();
  });

  it("„Stawka od” też ponad budżetem — bez dopisku", () => {
    mount({ rateFromHourly: 138 });
    expect(screen.queryByTestId("rate-lower-known")).toBeNull();
  });
});
