import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MailTemplatesSettings } from "../MailTemplatesSettings";

vi.mock("@/components/settings/CandidateEmailTemplates", () => ({
  CandidateEmailTemplates: () => <div>Biblioteka szablonów do kandydatów</div>,
}));
vi.mock("@/components/settings/EmailTemplatesCard", () => ({
  default: () => <div>Moje podpowiedzi w Outlooku</div>,
}));

describe("MailTemplatesSettings — oba rodzaje szablonów w jednej pozycji (20.10.2026)", () => {
  it("otwiera się na szablonach do kandydatów, Outlook jest drugą zakładką", async () => {
    const user = userEvent.setup();
    render(<MailTemplatesSettings />);
    expect(screen.getByText("Biblioteka szablonów do kandydatów")).toBeInTheDocument();
    expect(screen.queryByText("Moje podpowiedzi w Outlooku")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Moje w Outlooku" }));
    expect(screen.getByText("Moje podpowiedzi w Outlooku")).toBeInTheDocument();
    expect(screen.queryByText("Biblioteka szablonów do kandydatów")).not.toBeInTheDocument();
  });

  it("nie odsyła już do osobnego edytora odrzuceń", () => {
    render(<MailTemplatesSettings />);
    expect(screen.queryByText(/otwórz szablony odrzuceń/)).not.toBeInTheDocument();
  });
});
