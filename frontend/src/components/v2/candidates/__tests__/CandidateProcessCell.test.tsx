/**
 * Kolumna „W procesie” na liście kandydatów: rekrutacje w dymku nazwane jak
 * nagłówek rekrutacji — numer u klienta (kopiuje) i tytuł dla rekrutera (link).
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CandidateProcessCell } from "@/components/v2/candidates/CandidateProcessCell";

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));

describe("CandidateProcessCell", () => {
  it("lists the recruitments with the client number and the recruiter title", async () => {
    render(
      <CandidateProcessCell
        candidateName="Anna Testowa"
        recruitments={[
          {
            job_id: 7,
            job_title: "AI Engineer (ZOB-9001)",
            job_working_title: "Senior AI Engineer · Java, LLM",
            job_client_reference: "ZOB-9001",
            client_name: "Bank Przykładowy",
            stage: "screening",
            moved_at: null,
          },
        ]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /W procesie: Anna Testowa/ }));
    const list = await screen.findByRole("list");
    const link = within(list).getByRole("link", { name: "Senior AI Engineer · Java, LLM" });
    expect(link).toHaveAttribute("href", "/jobs/7");
    // Numer jest osobnym przyciskiem, nie leży w linku.
    const chip = within(list).getByRole("button", { name: "Numer u klienta ZOB-9001 — kopiuj" });
    expect(link).not.toContainElement(chip);
    expect(within(list).queryByText("AI Engineer (ZOB-9001)")).toBeNull();
    expect(within(list).getByText(/Bank Przykładowy/)).toBeInTheDocument();
  });
});
