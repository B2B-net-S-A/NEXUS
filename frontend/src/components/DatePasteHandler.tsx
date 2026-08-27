"use client";

import { useEffect } from "react";
import { useToast } from "@/components/Toast";
import { DATE_PATTERN, parseDateInput } from "@/lib/dateInput";

export const DATE_PASTE_ERROR_MESSAGE =
  "Nie rozpoznano formatu daty. Użyj DD.MM.RRRR, DD-MM-RRRR, DD/MM/RRRR, RRRR.MM.DD lub RRRR-MM-DD.";

function isDateInput(input: HTMLInputElement): boolean {
  return input.type === "date" || (input.type === "text" && input.pattern === DATE_PATTERN);
}

function setNativeInputValue(input: HTMLInputElement, value: string): void {
  const valueSetter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;

  if (valueSetter) {
    valueSetter.call(input, value);
  } else {
    input.value = value;
  }

  const EventConstructor = input.ownerDocument.defaultView?.Event ?? Event;
  input.dispatchEvent(new EventConstructor("input", { bubbles: true, composed: true }));
  input.dispatchEvent(new EventConstructor("change", { bubbles: true, composed: true }));
}

/**
 * One delegated listener covers native date fields, portals and the legacy
 * text date inputs which share DATE_PATTERN. Date-time and month inputs keep
 * their own input contracts and are deliberately ignored.
 */
export function DatePasteHandler() {
  const { showError } = useToast();

  useEffect(() => {
    const handlePaste = (event: ClipboardEvent) => {
      if (event.defaultPrevented) return;

      const input = event.target;
      if (
        !(input instanceof HTMLInputElement) ||
        !isDateInput(input) ||
        input.disabled ||
        input.readOnly ||
        !event.clipboardData
      ) {
        return;
      }

      const pastedText =
        event.clipboardData.getData("text/plain") || event.clipboardData.getData("text");
      const normalizedDate = parseDateInput(pastedText);

      event.preventDefault();

      if (!normalizedDate) {
        showError(DATE_PASTE_ERROR_MESSAGE);
        return;
      }

      setNativeInputValue(input, normalizedDate);
    };

    document.addEventListener("paste", handlePaste);
    return () => document.removeEventListener("paste", handlePaste);
  }, [showError]);

  return null;
}
