import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HighlightedCvText } from "./HighlightedCvText";

describe("HighlightedCvText", () => {
  it("preserves Unicode and uses the server's literal bold runs", () => {
    const { container } = render(<HighlightedCvText text="🚀 Python i SQL" runs={[
      { text: "🚀 ", bold: false }, { text: "Python", bold: true },
      { text: " i ", bold: false }, { text: "SQL", bold: true },
    ]} />);
    expect(container.textContent).toBe("🚀 Python i SQL");
    expect([...container.querySelectorAll("strong")].map((node) => node.textContent)).toEqual(["Python", "SQL"]);
  });
  it("does not replace content with stale formatting metadata", () => {
    const { container } = render(<HighlightedCvText text="Aktualne CV" runs={[{ text: "Inna wersja", bold: true }]} />);
    expect(container.textContent).toBe("Aktualne CV");
    expect(container.querySelector("strong")).toBeNull();
  });
  it("renders formatting text as literal text rather than markup", () => {
    const text = "<img src=x onerror=alert(1)>";
    const { container } = render(<HighlightedCvText text={text} runs={[{ text, bold: true }]} />);
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
