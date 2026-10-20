import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { vi } from "vitest";

import { buildBar, parseTerminalCommand } from "../TerminalScene";
import { mockMatchMedia, renderScene } from "./sceneTestUtils";

afterEach(() => vi.unstubAllGlobals());

function run(full: ReturnType<ReturnType<typeof renderScene>["full"]>, cmd: string) {
  const input = full.getByLabelText("Polecenie terminala");
  fireEvent.change(input, { target: { value: cmd } });
  fireEvent.keyDown(input, { key: "Enter" });
}

describe("scena Terminal", () => {
  it("rozpoznaje polecenia niezależnie od wielkości liter i spacji", () => {
    expect(parseTerminalCommand("  CAT   wymagania ")).toEqual({ kind: "wym", text: "cat wymagania" });
    expect(parseTerminalCommand("./sprawdz --ja").kind).toBe("spr");
    expect(parseTerminalCommand("git log").kind).toBe("log");
    expect(parseTerminalCommand("rm -rf /").kind).toBe("err");
    expect(parseTerminalCommand("").kind).toBe("help");
    expect(buildBar(0, 5)).toBe("[----------]");
    expect(buildBar(2, 5)).toBe("[####------]");
    expect(buildBar(3, 3)).toBe("[##########]");
  });

  it("cat wymagania → zaznaczenie [x] liczy się do wyniku przy „Aplikuj”", () => {
    const s = renderScene("terminal");
    const full = s.full();
    fireEvent.click(full.getByRole("button", { name: "cat wymagania" }));
    const kafka = full.getByRole("button", { name: "Kafka — architektura zdarzeniowa" });
    expect(kafka).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(kafka);
    expect(kafka).toHaveAttribute("aria-pressed", "true");
    expect(kafka).toHaveTextContent("[x]");
    expect(s.score().getByText("1/5")).toBeInTheDocument();
    expect(s.score().getByRole("link", { name: "Aplikuj — masz 1 z 5" })).toHaveAttribute("href", "#aplikuj");
    expect(s.score().getByText("Nie musisz mieć wszystkiego — aplikuj.")).toBeInTheDocument();
    // Lista na telefonie to ten sam stan.
    expect(s.compact().getByRole("button", { name: "Kafka — architektura zdarzeniowa" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("piąta pozycja to mile widziane; reszta mile widzianych jako ozdoba", () => {
    const s = renderScene("terminal");
    fireEvent.click(s.full().getByRole("button", { name: "cat wymagania" }));
    expect(s.full().getByRole("button", { name: "Kubernetes (mile widziane)" })).toBeInTheDocument();
    expect(s.full().getByText("[--] mile widziane: aws · płatności")).toBeInTheDocument();
  });

  it("wpisane ./sprawdz --ja kompiluje wynik i wymienia braki", () => {
    const s = renderScene("terminal");
    const compact = s.compact();
    fireEvent.click(compact.getByRole("button", { name: /^Java Spring Boot/ }));
    fireEvent.click(compact.getByRole("button", { name: /^Kafka/ }));
    fireEvent.click(compact.getByRole("button", { name: /^PostgreSQL/ }));
    run(s.full(), "./sprawdz --ja");
    expect(s.full().getByText("BUILD SUCCESS")).toBeInTheDocument();
    expect(s.full().getByText(/brakuje: english, kubernetes — nie szkodzi, aplikuj/)).toBeInTheDocument();
  });

  it("git log --proces pokazuje kroki, ./aplikuj podświetla przycisk, nieznane → błąd", () => {
    const s = renderScene("terminal");
    run(s.full(), "git log --proces");
    expect(s.full().getByText("rozmowa z Martą")).toBeInTheDocument();
    expect(s.full().getByText("decyzja i start")).toBeInTheDocument();
    run(s.full(), "./aplikuj");
    expect(s.score().getByRole("link", { name: /^Aplikuj/ })).toHaveAttribute("data-hot");
    expect(s.full().getByRole("link", { name: /przejdź do formularza/ })).toHaveAttribute("href", "#aplikuj");
    run(s.full(), "sudo zatrudnij");
    expect(s.full().getByText("zsh: nie znam „sudo zatrudnij”")).toBeInTheDocument();
  });

  it("proces ukryty przez rekrutera — git log nie zmyśla kroków", () => {
    const s = renderScene("terminal", { process: false });
    run(s.full(), "git log --proces");
    expect(s.full().queryByText("weryfikacja techniczna")).toBeNull();
    expect(s.full().getByText(/kroki opowie Marta/)).toBeInTheDocument();
  });

  it("ograniczenie ruchu: bez pisania znak po znaku, interakcja działa", () => {
    mockMatchMedia((q) => q.includes("reduce"));
    const s = renderScene("terminal");
    const box = screen.getByTestId("scene-full");
    expect(box).toHaveAttribute("data-kr-still");
    run(s.full(), "cat wymagania");
    expect(s.full().getByText("cat wymagania", { selector: ".kr-term-cmd" }).className).not.toMatch(/kr-ty-/);
    fireEvent.click(s.full().getByRole("button", { name: /^Kafka/ }));
    expect(s.score().getByText("1/5")).toBeInTheDocument();
  });

  it("bez ograniczenia ruchu polecenie się „pisze”, a kursor działa tylko z myszą", () => {
    mockMatchMedia((q) => q.includes("pointer: fine"));
    const s = renderScene("terminal");
    const box = screen.getByTestId("scene-full");
    expect(box).not.toHaveAttribute("data-kr-still");
    run(s.full(), "cat wymagania");
    expect(s.full().getByText("cat wymagania", { selector: ".kr-term-cmd" }).className).toMatch(/kr-ty-/);
  });
});
