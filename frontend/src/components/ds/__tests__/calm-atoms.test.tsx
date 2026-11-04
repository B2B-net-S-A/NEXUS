import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";
import { InlineStats } from "../InlineStats";
import { StatusDot } from "../StatusDot";

describe("StatusDot", () => {
  it("shows the label as text and keeps the dot decorative", () => {
    render(
      <StatusDot tone="warning" note="za 29 dni">
        Kończący się
      </StatusDot>,
    );
    expect(screen.getByText("Kończący się")).toBeInTheDocument();
    expect(screen.getByText("za 29 dni")).toBeInTheDocument();
    const dot = document.querySelector("[aria-hidden]");
    expect(dot).toHaveClass("bg-warning");
  });

  it("renders no note line when there is nothing to say", () => {
    const { container } = render(<StatusDot tone="success">Aktywny</StatusDot>);
    expect(container.textContent).toBe("Aktywny");
  });
});

describe("InlineStats", () => {
  it("pairs every value with its label in a description list", () => {
    render(
      <InlineStats
        stats={[
          { id: "people", label: "aktywnych konsultantów", value: "6" },
          { id: "mrr", label: "aktywne MRR / mc", value: "—", title: "Brak stawek" },
        ]}
      />,
    );
    const terms = screen.getAllByRole("term").map((el) => el.textContent);
    expect(terms).toEqual(["aktywnych konsultantów", "aktywne MRR / mc"]);
    const values = screen.getAllByRole("definition").map((el) => el.textContent);
    expect(values).toEqual(["6", "—"]);
    expect(screen.getByText("aktywne MRR / mc").closest("[title]")).toHaveAttribute(
      "title",
      "Brak stawek",
    );
  });
});

describe("Button quiet variant", () => {
  it("stays grey until hovered or focused", () => {
    render(<Button variant="quiet">Usuń</Button>);
    const button = screen.getByRole("button", { name: "Usuń" });
    expect(button).toHaveClass("text-muted-foreground");
    expect(button).toHaveClass("hover:text-destructive");
    expect(button).not.toHaveClass("bg-destructive");
  });
});
