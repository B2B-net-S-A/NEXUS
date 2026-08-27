import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  DATE_PASTE_ERROR_MESSAGE,
  DatePasteHandler,
} from "@/components/DatePasteHandler";
import { ToastProvider } from "@/components/Toast";
import { Input } from "@/components/ui/input";
import { DATE_PATTERN } from "@/lib/dateInput";

function dispatchPaste(input: HTMLInputElement, text: string): ClipboardEvent {
  const event = new Event("paste", { bubbles: true, cancelable: true }) as ClipboardEvent;
  Object.defineProperty(event, "clipboardData", {
    value: { getData: () => text },
  });
  fireEvent(input, event);
  return event;
}

function ControlledDateInput({
  uiInput = false,
  onChange = vi.fn(),
}: {
  uiInput?: boolean;
  onChange?: (value: string) => void;
}) {
  const [value, setValue] = useState("2026-01-15");
  const props = {
    "aria-label": "Data testowa",
    type: "date",
    value,
    onChange: (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange(event.target.value);
      setValue(event.target.value);
    },
  } as const;

  return uiInput ? <Input {...props} /> : <input {...props} />;
}

function renderWithHandler(children: React.ReactNode) {
  return render(
    <ToastProvider>
      <DatePasteHandler />
      {children}
    </ToastProvider>
  );
}

describe("DatePasteHandler", () => {
  it.each([false, true])(
    "normalizes a valid paste in a controlled date input (uiInput=%s)",
    (uiInput) => {
      const onChange = vi.fn();
      renderWithHandler(<ControlledDateInput uiInput={uiInput} onChange={onChange} />);
      const input = screen.getByLabelText("Data testowa") as HTMLInputElement;

      const event = dispatchPaste(input, "01.02.2026");

      expect(event.defaultPrevented).toBe(true);
      expect(input).toHaveValue("2026-02-01");
      expect(onChange).toHaveBeenCalledOnce();
      expect(onChange).toHaveBeenCalledWith("2026-02-01");
      expect(screen.queryByText(DATE_PASTE_ERROR_MESSAGE)).not.toBeInTheDocument();
    }
  );

  it("supports legacy text date inputs marked with the shared date pattern", () => {
    const onChange = vi.fn();
    renderWithHandler(
      <input
        aria-label="Tekstowa data"
        type="text"
        pattern={DATE_PATTERN}
        defaultValue=""
        onChange={(event) => onChange(event.target.value)}
      />
    );
    const input = screen.getByLabelText("Tekstowa data") as HTMLInputElement;

    dispatchPaste(input, "2026.02.01");

    expect(input).toHaveValue("2026-02-01");
    expect(onChange).toHaveBeenCalledOnce();
  });

  it("leaves the previous value untouched and shows an accessible error for invalid input", () => {
    renderWithHandler(<ControlledDateInput />);
    const input = screen.getByLabelText("Data testowa") as HTMLInputElement;

    const event = dispatchPaste(input, "31.02.2026");

    expect(event.defaultPrevented).toBe(true);
    expect(input).toHaveValue("2026-01-15");
    expect(screen.getByRole("alert")).toHaveTextContent(DATE_PASTE_ERROR_MESSAGE);
  });

  it.each(["text", "datetime-local", "month"])("ignores a regular %s input", (type) => {
    renderWithHandler(<input aria-label="Inne pole" type={type} defaultValue="" />);
    const input = screen.getByLabelText("Inne pole") as HTMLInputElement;

    const event = dispatchPaste(input, "01.02.2026");

    expect(event.defaultPrevented).toBe(false);
    expect(input).toHaveValue("");
    expect(screen.queryByText(DATE_PASTE_ERROR_MESSAGE)).not.toBeInTheDocument();
  });

  it.each(["disabled", "readOnly"] as const)("ignores a %s date input", (state) => {
    renderWithHandler(
      <input
        aria-label="Nieedytowalna data"
        type="date"
        defaultValue="2026-01-15"
        disabled={state === "disabled"}
        readOnly={state === "readOnly"}
      />
    );
    const input = screen.getByLabelText("Nieedytowalna data") as HTMLInputElement;

    const event = dispatchPaste(input, "01.02.2026");

    expect(event.defaultPrevented).toBe(false);
    expect(input).toHaveValue("2026-01-15");
  });
});
