import { render, screen } from "@testing-library/react";
import Link from "next/link";
import { describe, expect, it } from "vitest";
import { Button } from "@/components/ui/button";

describe("Button asChild (UAT B74)", () => {
  it("renders a link as the button without throwing a Slot error", () => {
    render(
      <Button asChild variant="outline">
        <Link href="/candidates">Wróć do kandydatów</Link>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Wróć do kandydatów" });
    expect(link).toHaveAttribute("href", "/candidates");
    expect(link.className).toContain("border");
  });

  it("keeps the loader for a regular button", () => {
    const { container } = render(<Button loading>Zapisz</Button>);
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
