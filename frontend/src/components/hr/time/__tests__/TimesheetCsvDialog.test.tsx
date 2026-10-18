import type React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ download: vi.fn() }));

vi.mock("@/lib/api/hr", () => ({ downloadHrFile: mocks.download }));

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
    const trigger = elements.find((child) => child.type === SelectTrigger) as
      | React.ReactElement<{ id?: string }>
      | undefined;
    const content = elements.find((child) => child.type === SelectContent) as
      | React.ReactElement<{ children?: React.ReactNode }>
      | undefined;
    const items = ReactModule.Children.toArray(content?.props.children).filter(
      ReactModule.isValidElement,
    ) as React.ReactElement<{ value: string; children?: React.ReactNode }>[];
    return (
      <select
        id={trigger?.props.id}
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

import { TimesheetCsvDialog, rangeError } from "../TimesheetCsvDialog";

const PERIOD = { year: 2031, month: 3 };

describe("rangeError", () => {
  it("od ≤ do, najwyżej 24 miesiące", () => {
    expect(rangeError("2031-01", "2031-03")).toBeNull();
    expect(rangeError("2030-01", "2031-12")).toBeNull();
    expect(rangeError("2031-04", "2031-03")).toMatch(/przed miesiącem/);
    expect(rangeError("2030-01", "2032-01")).toMatch(/24/);
    expect(rangeError("", "2031-03")).toMatch(/Wybierz/);
  });
});

describe("TimesheetCsvDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.download.mockResolvedValue(undefined);
  });

  it("osoba pobiera własne godziny za zakres", async () => {
    const onOpenChange = vi.fn();
    render(
      <TimesheetCsvDialog open onOpenChange={onOpenChange} mode={{ kind: "self" }} period={PERIOD} />,
    );
    fireEvent.change(screen.getByLabelText("Od miesiąca"), { target: { value: "2031-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Pobierz CSV" }));
    await waitFor(() =>
      expect(mocks.download).toHaveBeenCalledWith(
        "/api/hr/time/me/export.csv?from=2031-01&to=2031-03",
        "godziny-2031-01_2031-03.csv",
      ),
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("zły zakres zatrzymuje się w oknie", async () => {
    render(
      <TimesheetCsvDialog open onOpenChange={() => undefined} mode={{ kind: "self" }} period={PERIOD} />,
    );
    fireEvent.change(screen.getByLabelText("Od miesiąca"), { target: { value: "2031-05" } });
    fireEvent.click(screen.getByRole("button", { name: "Pobierz CSV" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/przed miesiącem/);
    expect(mocks.download).not.toHaveBeenCalled();
  });

  it("Płace i Kadry: domyślnie cały zespół za miesiąc, potem jedna osoba", async () => {
    render(
      <TimesheetCsvDialog
        open
        onOpenChange={() => undefined}
        period={PERIOD}
        mode={{
          kind: "team",
          allowMonth: true,
          people: [
            { user_id: 7, name: "Anna Przykładowa" },
            { user_id: 8, name: "Jan Testowy" },
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Pobierz CSV" }));
    await waitFor(() =>
      expect(mocks.download).toHaveBeenCalledWith(
        "/api/hr/time/export/2031/3/csv",
        "godziny-2031-03.csv",
      ),
    );

    fireEvent.click(screen.getByRole("radio", { name: "Jedna osoba" }));
    fireEvent.change(screen.getByLabelText("Osoba"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "Pobierz CSV" }));
    await waitFor(() =>
      expect(mocks.download).toHaveBeenLastCalledWith(
        "/api/hr/time/people/8/export.csv?from=2031-03&to=2031-03",
        "godziny-2031-03_2031-03.csv",
      ),
    );
  });

  it("przełożony nie ma eksportu całego zespołu", () => {
    render(
      <TimesheetCsvDialog
        open
        onOpenChange={() => undefined}
        period={PERIOD}
        mode={{ kind: "team", allowMonth: false, people: [{ user_id: 7, name: "Anna Przykładowa" }] }}
      />,
    );
    expect(screen.queryByRole("radio", { name: /Cały zespół/ })).toBeNull();
    expect(screen.getByLabelText("Osoba")).toBeInTheDocument();
  });

  it("błąd pobrania zostaje w oknie", async () => {
    mocks.download.mockRejectedValueOnce({
      response: { status: 404, data: { detail: "Nie ma takiej osoby." } },
    });
    render(
      <TimesheetCsvDialog open onOpenChange={() => undefined} mode={{ kind: "self" }} period={PERIOD} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Pobierz CSV" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie ma takiej osoby.");
  });
});
