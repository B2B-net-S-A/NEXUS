/**
 * „Krytyczne (0–3)” (30.09.2026; trzy od 08.10.2026): wybór z listy MUST, najwyżej trzy pozycje,
 * „Brak krytycznych” = [], podpowiedź z historii, awaria nigdy jako pustka.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CriticalSkillsField } from "@/components/champion/CriticalSkillsField";
import type { CriticalSuggestionState, CriticalValue } from "@/lib/critical-skills";

const MUST = ["Java", "Angular", "Kafka", "komunikatywność"];

function suggestion(overrides: Partial<CriticalSuggestionState> = {}): CriticalSuggestionState {
  return {
    data: {
      suggested: ["Java", "Angular"],
      eligible: ["Java", "Angular", "Kafka"],
      stats: { Java: { rate: 0.96, jobs: 41 }, Angular: { rate: 0.91, jobs: 41 } },
    },
    eligible: ["Java", "Angular", "Kafka"],
    isLoading: false,
    isError: false,
    error: null,
    retry: vi.fn(),
    emptyMust: false,
    ...overrides,
  };
}

function renderField(value: CriticalValue, overrides: Partial<CriticalSuggestionState> = {}) {
  const onChange = vi.fn();
  const state = suggestion(overrides);
  render(<CriticalSkillsField must={MUST} value={value} onChange={onChange} suggestion={state} />);
  return { onChange, state };
}

const chip = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) });

describe("CriticalSkillsField", () => {
  it("pokazuje wyłącznie pozycje MUST i status braku decyzji z podpowiedzią", () => {
    renderField(null);
    const chips = screen.getAllByTestId("critical-chip").map((b) => b.textContent);
    expect(chips).toEqual(MUST);
    expect(screen.getByTestId("critical-status")).toHaveTextContent(
      "Nie zdecydowano — działa podpowiedź: Java, Angular",
    );
    expect(
      screen.getByText(/Kandydat bez umiejętności krytycznej nie pojawi się na listach AI/),
    ).toBeInTheDocument();
  });

  it("kliknięcie pozycji zaznacza ją jako krytyczną", async () => {
    const { onChange } = renderField(null);
    await userEvent.click(chip("Kafka"));
    expect(onChange).toHaveBeenCalledWith(["Kafka"]);
  });

  it("trzecia pozycja da się zaznaczyć (limit 3 od 08.10.2026)", async () => {
    const { onChange } = renderField(["Java", "Angular"]);
    expect(chip("Kafka")).not.toHaveAttribute("aria-disabled");
    await userEvent.click(chip("Kafka"));
    expect(onChange).toHaveBeenCalledWith(["Java", "Angular", "Kafka"]);
  });

  it("najwyżej trzy: czwarta pozycja jest zablokowana, zaznaczoną da się odznaczyć", async () => {
    const onChange = vi.fn();
    render(
      <CriticalSkillsField
        must={[...MUST, "Docker"]}
        value={["Java", "Angular", "Kafka"]}
        onChange={onChange}
        suggestion={suggestion({ eligible: ["Java", "Angular", "Kafka", "Docker"] })}
      />,
    );
    expect(chip("Docker")).toHaveAttribute("aria-disabled", "true");
    expect(chip("Docker")).toHaveAttribute(
      "title",
      "Najwyżej 3 umiejętności krytyczne — najpierw odznacz jedną",
    );
    await userEvent.click(chip("Docker"));
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(chip("Java"));
    expect(onChange).toHaveBeenCalledWith(["Angular", "Kafka"]);
  });

  it("pozycja spoza słownika technologii jest wyszarzona z wyjaśnieniem", async () => {
    const { onChange } = renderField(null);
    const soft = chip("komunikatywność");
    expect(soft).toHaveAttribute("aria-disabled", "true");
    expect(soft).toHaveAttribute(
      "title",
      "To nie jest nazwa technologii ani narzędzia — nie może ukrywać kandydatów",
    );
    await userEvent.click(soft);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("zablokowana pozycja pokazuje powód z serwera", () => {
    const reason = "To umiejętność miękka — daje punkty, nie ukrywa kandydatów.";
    renderField(null, {
      data: {
        suggested: [],
        eligible: ["Java", "Angular", "Kafka"],
        selectable: ["Java", "Angular", "Kafka"],
        blocked: { komunikatywność: reason },
        stats: {},
      },
    });
    expect(chip("komunikatywność")).toHaveAttribute("title", reason);
  });

  it("„Brak krytycznych” ustawia pustą listę", async () => {
    const { onChange } = renderField(null);
    await userEvent.click(screen.getByTestId("critical-none"));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("„Brak krytycznych” zaznaczone — kliknięcie cofa do braku decyzji", async () => {
    const { onChange } = renderField([]);
    expect(screen.getByTestId("critical-none")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("critical-status")).toHaveTextContent(/^Brak krytycznych/);
    await userEvent.click(screen.getByTestId("critical-none"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("przycisk podpowiedzi przyjmuje podpowiedź i pokazuje procent", async () => {
    const { onChange } = renderField(null);
    const button = screen.getByTestId("critical-use-suggestion");
    expect(button).toHaveTextContent("Użyj podpowiedzi: Java, Angular (z historii)");
    expect(screen.getByTestId("critical-suggestion-stats")).toHaveTextContent(
      "Java: 96% wysłanych ją miało",
    );
    await userEvent.click(button);
    expect(onChange).toHaveBeenCalledWith(["Java", "Angular"]);
  });

  it("bez podpowiedzi status mówi, że bramka MUST nikogo nie ukrywa", () => {
    renderField(null, { data: { suggested: [], eligible: ["Java"], stats: {} } });
    expect(screen.queryByTestId("critical-use-suggestion")).toBeNull();
    expect(screen.getByTestId("critical-status")).toHaveTextContent(
      "Nie zdecydowano — brak podpowiedzi, bramka MUST nie ukrywa nikogo",
    );
  });

  it("awaria podpowiedzi to komunikat z „Ponów”, nie pusta podpowiedź", async () => {
    const { state } = renderField(null, { data: undefined, eligible: null, isError: true });
    expect(screen.getByTestId("critical-suggestion-error")).toHaveTextContent(
      "Nie udało się pobrać podpowiedzi z historii.",
    );
    expect(screen.getByTestId("critical-status")).not.toHaveTextContent("brak podpowiedzi");
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(state.retry).toHaveBeenCalled();
  });

  it("wybór, którego nie ma już w MUST, jest opisany", () => {
    renderField(["Scala"]);
    expect(screen.getByTestId("critical-stale")).toHaveTextContent("„Scala” nie ma już w „Musi mieć”");
  });

  it("pusta lista MUST prosi najpierw o pozycje", () => {
    const onChange = vi.fn();
    render(
      <CriticalSkillsField
        must={[]}
        value={null}
        onChange={onChange}
        suggestion={suggestion({ data: undefined, eligible: [], emptyMust: true })}
      />,
    );
    expect(screen.getByTestId("critical-empty-must")).toBeInTheDocument();
  });
});
