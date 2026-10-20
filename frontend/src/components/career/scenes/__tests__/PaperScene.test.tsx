import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { paperReport } from "../PaperScene";
import { renderScene } from "./sceneTestUtils";

describe("scena Papier", () => {
  it("krok scenariusza na PASS liczy się do wyniku", () => {
    const s = renderScene("papier");
    const step = s.full().getByRole("button", { name: /^Kafka/ });
    fireEvent.click(step);
    expect(step).toHaveAttribute("aria-pressed", "true");
    expect(step).toHaveTextContent("PASS");
    expect(s.full().getByText("1 PASS · 4 DO SPR.")).toBeInTheDocument();
    expect(s.score().getByText("Kroki na PASS")).toBeInTheDocument();
    expect(s.score().getByText("1/5")).toBeInTheDocument();
  });

  it("cztery błędy: opis dla czytnika zamiast literówki, zakreślone nie liczą się do wyniku", () => {
    const s = renderScene("papier");
    const full = s.full();
    const bug = full.getByRole("button", { name: /^Błąd 1 z 4: literówka w etykiecie hasła/ });
    expect(bug).not.toHaveAccessibleName(/Hsało/);
    fireEvent.click(bug);
    expect(full.getByText("Hasło").closest("button")).toHaveClass("kr-paper-ok");
    fireEvent.click(full.getByRole("button", { name: /^Błąd 2 z 4:/ }));
    fireEvent.click(full.getByRole("button", { name: /^Błąd 3 z 4:/ }));
    fireEvent.click(full.getByRole("button", { name: /^Błąd 4 z 4:/ }));
    expect(full.getByText("zgłoszenia: 4/4 — komplet")).toBeInTheDocument();
    expect(full.getByText("Nieprawidłowy login lub hasło")).toBeInTheDocument();
    expect(s.score().getByText("0/5")).toBeInTheDocument();
    // Ekran logowania na telefonie to ten sam stan.
    expect(s.compact().getByText("zgłoszenia: 4/4 — komplet")).toBeInTheDocument();
    expect(paperReport(2)).toBe("zgłoszenia: 2/4");
  });
});
