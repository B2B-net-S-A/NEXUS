import type React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FillResult, TimesheetTemplate } from "@/lib/api/hr-time";

const mocks = vi.hoisted(() => ({ confirm: vi.fn(async () => true) }));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

// Lista wyboru Radix nie działa w jsdom — zwykły <select> o tych samych wartościach.
vi.mock("@/components/ui/select", async () => {
  const ReactModule = await import("react");
  const SelectTrigger = (_props: { id?: string; children?: React.ReactNode }) => null;
  const SelectContent = (_props: { children?: React.ReactNode }) => null;
  const SelectItem = (_props: { value: string; children?: React.ReactNode }) => null;
  const SelectValue = (_props: { placeholder?: string }) => null;
  function Select({
    children,
    value,
    onValueChange,
  }: {
    children: React.ReactNode;
    value?: string;
    onValueChange?: (value: string) => void;
  }) {
    const elements = ReactModule.Children.toArray(children).filter(ReactModule.isValidElement);
    const content = elements.find((child) => child.type === SelectContent) as
      | React.ReactElement<{ children?: React.ReactNode }>
      | undefined;
    const items = ReactModule.Children.toArray(content?.props.children).filter(
      ReactModule.isValidElement,
    ) as React.ReactElement<{ value: string; children?: React.ReactNode }>[];
    return (
      <select
        aria-label="Szablon"
        value={value}
        onChange={(event) => onValueChange?.(event.target.value)}
      >
        {items.map((item) => (
          <option key={item.props.value} value={item.props.value}>
            {item.props.children}
          </option>
        ))}
      </select>
    );
  }
  return { Select, SelectTrigger, SelectContent, SelectItem, SelectValue };
});

import { FillMonthDialog, fillPayload } from "../FillMonthDialog";

const TEMPLATES: TimesheetTemplate[] = [
  { id: 4, name: "Code review", description: "Przegląd kodu", project: "Alfa", sort_order: 0 },
  { id: 5, name: "Analiza", description: "Analiza wymagań", project: null, sort_order: 1 },
];

const RESULT: FillResult = {
  inserted: 20,
  skipped_existing: 1,
  skipped_leave: 0,
  working_days: 21,
  removed: 0,
  hours_per_day: 8,
  description: "Praca standardowa",
  project: null,
};

function renderDialog(props: Partial<Parameters<typeof FillMonthDialog>[0]> = {}) {
  const onFill = vi.fn(async () => RESULT);
  const onDone = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <FillMonthDialog
      open
      onOpenChange={onOpenChange}
      period={{ year: 2031, month: 3 }}
      templates={TEMPLATES}
      roleDefault={{ label: "Rekruter", description: "Rekrutacje IT", project: null }}
      onFill={onFill}
      onDone={onDone}
      {...props}
    />,
  );
  return { onFill, onDone, onOpenChange };
}

describe("fillPayload", () => {
  it("wysyła tylko wybrane źródło opisu i niepusty projekt", () => {
    const base = {
      hours: 6,
      templateId: 4,
      description: "  Własny  ",
      project: " ",
      overwrite: false,
    };
    expect(fillPayload({ ...base, source: "default" })).toEqual({
      hours_per_day: 6,
      overwrite: false,
    });
    expect(fillPayload({ ...base, source: "template" })).toEqual({
      hours_per_day: 6,
      overwrite: false,
      template_id: 4,
    });
    expect(fillPayload({ ...base, source: "custom", project: "Beta", overwrite: true })).toEqual({
      hours_per_day: 6,
      overwrite: true,
      description: "Własny",
      project: "Beta",
    });
  });
});

describe("FillMonthDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.confirm.mockResolvedValue(true);
  });

  it("domyślnie 8 h i opis domyślny roli, bez pytania o nadpisanie", async () => {
    const { onFill, onDone, onOpenChange } = renderDialog();
    expect(screen.getByText("Rekruter: „Rekrutacje IT”")).toBeInTheDocument();
    expect((screen.getByLabelText("Godziny dziennie") as HTMLInputElement).value).toBe("8");
    fireEvent.click(screen.getByRole("button", { name: "Wypełnij" }));
    await waitFor(() =>
      expect(onFill).toHaveBeenCalledWith({ hours_per_day: 8, overwrite: false }),
    );
    expect(mocks.confirm).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledWith(RESULT);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("ponad 8 h zatrzymuje się w oknie — nadgodziny wpisuje się w dniu", async () => {
    const { onFill } = renderDialog();
    fireEvent.change(screen.getByLabelText("Godziny dziennie"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Wypełnij" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/nadgodziny wpisuje się w dniu/);
    expect(onFill).not.toHaveBeenCalled();
  });

  it("B2B: „godziny ponad 8 h wpisuje się w dniu” zamiast nadgodzin (21.10.2026)", async () => {
    renderDialog({ form: "b2b" });
    fireEvent.change(screen.getByLabelText("Godziny dziennie"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Wypełnij" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/godziny ponad 8 h wpisuje się w dniu, z krótkim opisem/);
    expect(alert.textContent).not.toMatch(/nadgodzin/);
  });

  it("bez opisu roli: B2B i zlecenie „Realizacja usług zgodnie z umową”, UoP „Praca standardowa” (28.10.2026)", () => {
    renderDialog({ form: "b2b", roleDefault: null });
    expect(screen.getByText("„Realizacja usług zgodnie z umową”")).toBeInTheDocument();
    cleanup();
    renderDialog({ form: "uop", roleDefault: null });
    expect(screen.getByText("„Praca standardowa”")).toBeInTheDocument();
  });

  it("szablon z listy i 6,5 h", async () => {
    const { onFill } = renderDialog();
    fireEvent.click(screen.getByRole("radio", { name: "Mój szablon" }));
    fireEvent.change(screen.getByLabelText("Szablon"), { target: { value: "5" } });
    expect(screen.getByText("„Analiza wymagań”")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Godziny dziennie"), { target: { value: "6,5" } });
    fireEvent.click(screen.getByRole("button", { name: "Wypełnij" }));
    await waitFor(() =>
      expect(onFill).toHaveBeenCalledWith({ hours_per_day: 6.5, overwrite: false, template_id: 5 }),
    );
  });

  it("bez szablonów opcja szablonu jest wyłączona", () => {
    renderDialog({ templates: [] });
    expect(screen.getByRole("radio", { name: "Mój szablon" })).toBeDisabled();
  });

  it("nadpisanie pyta o zgodę; odmowa nic nie wysyła", async () => {
    mocks.confirm.mockResolvedValueOnce(false);
    const { onFill } = renderDialog();
    fireEvent.click(screen.getByRole("checkbox", { name: "Nadpisz istniejące wpisy" }));
    fireEvent.click(screen.getByRole("radio", { name: "Własny opis" }));
    fireEvent.change(screen.getByLabelText("Własny opis"), { target: { value: "Wdrożenie" } });
    fireEvent.click(screen.getByRole("button", { name: "Wypełnij" }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledTimes(1));
    expect(onFill).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Wypełnij" }));
    await waitFor(() =>
      expect(onFill).toHaveBeenCalledWith({
        hours_per_day: 8,
        overwrite: true,
        description: "Wdrożenie",
      }),
    );
  });

  it("błąd serwera zostaje w oknie", async () => {
    const onFill = vi.fn(async () => {
      throw { response: { status: 409, data: { detail: "Miesiąc zamknięty w płacach." } } };
    });
    const { onDone } = renderDialog({ onFill });
    fireEvent.click(screen.getByRole("button", { name: "Wypełnij" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Miesiąc zamknięty w płacach.");
    expect(onDone).not.toHaveBeenCalled();
  });
});
