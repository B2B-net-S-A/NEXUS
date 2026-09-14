import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecruitmentCombobox } from "../RecruitmentCombobox";

// UAT M05-B05: własna lupa i wrapper wokół `CommandInput` (który sam renderuje
// ikonę i wrapper) dawały dwie lupy i pole o szerokości ~80 px z uciętą
// podpowiedzią.
describe("RecruitmentCombobox — pole wyszukiwania", () => {
  it("renderuje jedną lupę, a pole nie jest zamknięte w dodatkowym wrapperze", () => {
    render(
      <RecruitmentCombobox
        recruitments={[]}
        value=""
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    const input = screen.getByPlaceholderText(
      "Szukaj po numerze requestu lub nazwie…",
    );
    const wrapper = input.parentElement as HTMLElement;
    expect(wrapper.hasAttribute("cmdk-input-wrapper")).toBe(true);
    expect(wrapper.querySelectorAll("svg")).toHaveLength(1);
    // Wrapper `CommandInput` jest bezpośrednio w `Command`, nie w ciasnym divie.
    expect(wrapper.parentElement?.hasAttribute("cmdk-root")).toBe(true);
  });

  it("pickery kandydata w generatorze nie dokładają drugiej lupy", () => {
    const source = readFileSync(
      resolve(__dirname, "../../pages/CVGeneratorStandaloneV2.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(/<Search\b[^>]*\/>\s*<CommandInput/);
  });
});
