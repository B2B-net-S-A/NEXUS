/**
 * „?” przy kolumnie „Zatrudniony” (20.10.2026): odpowiedź na „czy tylko DL”
 * i „czy bez zamówienia się da” tam, gdzie pada pytanie.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HiredColumnHelp } from "@/components/v2/jobs/HiredColumnHelp";

describe("HiredColumnHelp", () => {
  it("po kliknięciu mówi, kto przesuwa i że zamówienie nie jest potrzebne", async () => {
    render(<HiredColumnHelp />);
    fireEvent.click(
      screen.getByRole("button", { name: "Kto przesuwa na „Zatrudniony” i co jest potrzebne" }),
    );
    expect(await screen.findByText("Kto przesuwa na „Zatrudniony”?")).toBeInTheDocument();
    expect(screen.getByText("Każdy z zespołu rekrutacji — rekruter też.")).toBeInTheDocument();
    expect(screen.getByText("debrief po rozmowie u klienta,")).toBeInTheDocument();
    expect(screen.getByText(/zamówienie od klienta — szkic powstaje sam/)).toBeInTheDocument();
  });
});
