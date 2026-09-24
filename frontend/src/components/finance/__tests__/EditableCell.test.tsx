import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EditableCell } from "@/components/finance/EditableCell";

describe("EditableCell finance read access", () => {
  it("nie otwiera edycji w trybie tylko do odczytu", () => {
    const onSave = vi.fn();
    render(
      <table>
        <tbody>
          <tr>
            <EditableCell
              value={1250}
              display={<span>1 250 zł</span>}
              ariaLabel="Stawka"
              needsCompletion={false}
              onSave={onSave}
              onError={vi.fn()}
              readOnly
            />
          </tr>
        </tbody>
      </table>,
    );

    fireEvent.doubleClick(screen.getByText("1 250 zł"));

    expect(screen.queryByRole("textbox", { name: "Stawka" })).not.toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("EditableCell na dotyku", () => {
  function renderCell() {
    render(
      <table>
        <tbody>
          <tr>
            <EditableCell
              value={1250}
              display={<span>1 250 zł</span>}
              ariaLabel="Stawka"
              needsCompletion={false}
              onSave={vi.fn()}
              onError={vi.fn()}
            />
          </tr>
        </tbody>
      </table>,
    );
  }

  // jsdom nie ma `matchMedia` — podstawiamy go na czas testu.
  function mockPointer(coarse: boolean) {
    const original = window.matchMedia;
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: (query: string) =>
        ({
          matches: coarse && query === "(pointer: coarse)",
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        }) as unknown as MediaQueryList,
    });
    return {
      mockRestore: () =>
        Object.defineProperty(window, "matchMedia", {
          configurable: true,
          writable: true,
          value: original,
        }),
    };
  }

  it("otwiera edycję pojedynczym stuknięciem przy wskaźniku coarse", () => {
    const spy = mockPointer(true);
    renderCell();
    fireEvent.click(screen.getByText("1 250 zł"));
    expect(screen.getByRole("textbox", { name: "Stawka" })).toBeInTheDocument();
    spy.mockRestore();
  });

  it("myszą pojedyncze kliknięcie nie otwiera edycji (zostaje dwuklik)", () => {
    const spy = mockPointer(false);
    renderCell();
    fireEvent.click(screen.getByText("1 250 zł"));
    expect(screen.queryByRole("textbox", { name: "Stawka" })).not.toBeInTheDocument();
    fireEvent.doubleClick(screen.getByText("1 250 zł"));
    expect(screen.getByRole("textbox", { name: "Stawka" })).toBeInTheDocument();
    spy.mockRestore();
  });
});
