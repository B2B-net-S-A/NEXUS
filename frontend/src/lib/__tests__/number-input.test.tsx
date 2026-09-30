import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { blurNumberInputOnWheel } from "@/lib/number-input";

describe("blurNumberInputOnWheel", () => {
  it("zdejmuje fokus z aktywnego pola liczbowego przy kółku myszy", () => {
    render(<input aria-label="Dni w biurze" type="number" defaultValue="1" onWheel={blurNumberInputOnWheel} />);
    const input = screen.getByLabelText("Dni w biurze") as HTMLInputElement;
    input.focus();
    expect(document.activeElement).toBe(input);
    fireEvent.wheel(input, { deltaY: 100 });
    expect(document.activeElement).not.toBe(input);
    expect(input.value).toBe("1");
  });

  it("nie rusza fokusu innego pola", () => {
    render(
      <>
        <input aria-label="Miasto" />
        <input aria-label="Dni w biurze" type="number" onWheel={blurNumberInputOnWheel} />
      </>,
    );
    const city = screen.getByLabelText("Miasto");
    city.focus();
    fireEvent.wheel(screen.getByLabelText("Dni w biurze"), { deltaY: 100 });
    expect(document.activeElement).toBe(city);
  });
});
