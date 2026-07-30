import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExpandableText } from "../ExpandableText";

describe("ExpandableText", () => {
  it("wraps unbroken tokens and keeps its toggle at least 44x44px", () => {
    const longToken = "VeryLongUnbrokenToken".repeat(20);

    render(<ExpandableText text={longToken} collapseThreshold={10} />);

    const text = screen.getByText(longToken);
    expect(text.classList).toContain("break-words");
    expect(text.classList).toContain("[overflow-wrap:anywhere]");
    const toggle = screen.getByRole("button", { name: "Rozwiń" });
    expect(toggle.classList).toContain("min-h-11");
    expect(toggle.classList).toContain("min-w-11");
  });
});
