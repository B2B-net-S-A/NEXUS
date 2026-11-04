import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import {
  PortalListingForm,
  dictionaryBoard,
  salaryFromInputs,
  withWorkplace,
} from "../PortalListingForm";
import {
  EMPTY_LISTING_OPTIONS,
  jobPortalKeys,
  type PortalConfigItem,
  type PortalListingOptions,
} from "@/lib/api/jobPortals";

describe("logika formularza ogłoszenia", () => {
  it("słownik z pierwszego zaznaczonego portalu dostawcy", () => {
    expect(dictionaryBoard(["pracuj_pl", "justjoinit", "rocketjobs"])).toBe("justjoinit");
    expect(dictionaryBoard(["pracuj_pl"])).toBeNull();
    expect(dictionaryBoard([])).toBeNull();
  });

  it("zmiana trybu pracy zdejmuje dni w biurze poza hybrydą", () => {
    const hybrid = { ...EMPTY_LISTING_OPTIONS, workplace_type: "hybrid", office_days: 2 };
    expect(withWorkplace(hybrid, "remote")).toMatchObject({ workplace_type: "remote", office_days: null });
    expect(withWorkplace(hybrid, "hybrid")).toMatchObject({ office_days: 2 });
  });

  it("widełki z pól: puste = bez widełek, przecinek dziesiętny, jedno puste = 0", () => {
    expect(salaryFromInputs("", " ", "hour")).toBeNull();
    expect(salaryFromInputs("120,5", "150", "hour")).toEqual({ from: 120.5, to: 150, unit: "hour" });
    expect(salaryFromInputs("15 000", "", "month")).toEqual({ from: 15000, to: 0, unit: "month" });
  });
});

const PORTALS: PortalConfigItem[] = [
  { portal: "rocketjobs", label: "RocketJobs", state: "ready", enabled: true },
  { portal: "justjoinit", label: "JustJoin.IT", state: "ready", enabled: true },
];

function renderForm(props: {
  value?: PortalListingOptions;
  selected?: ("rocketjobs" | "justjoinit")[];
  seedDictionary?: boolean;
  onChange?: (v: PortalListingOptions) => void;
  onSelectedChange?: (v: string[]) => void;
}) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  if (props.seedDictionary !== false) {
    qc.setQueryData(jobPortalKeys.dictionaries("rocketjobs"), {
      categories: [{ key: "java", name: "Java" }],
      experience_levels: [],
      working_times: [],
      workplace_types: [],
    });
  }
  return render(
    <QueryClientProvider client={qc}>
      <PortalListingForm
        value={props.value ?? EMPTY_LISTING_OPTIONS}
        onChange={props.onChange ?? vi.fn()}
        portals={PORTALS}
        selected={props.selected ?? ["rocketjobs"]}
        onSelectedChange={props.onSelectedChange}
        problems={["Wpisz miasto — portal wymaga lokalizacji."]}
      />
    </QueryClientProvider>,
  );
}

describe("PortalListingForm", () => {
  it("kategorie ze słownika i braki pod formularzem", () => {
    renderForm({});
    expect(screen.getByRole("option", { name: "Java" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Wpisz miasto");
  });

  it("awaria słownika to komunikat z „Ponów”, nie pusta lista", async () => {
    apiMock.get.mockRejectedValueOnce({ response: { status: 409, data: { detail: "Konto portalu niepołączone." } } });
    renderForm({ seedDictionary: false });
    expect(await screen.findByText(/Nie udało się wczytać kategorii portalu/)).toHaveTextContent(
      "Konto portalu niepołączone.",
    );
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Kategoria")).toBeNull();
  });

  it("zaznaczanie portali i widełki", () => {
    const onSelectedChange = vi.fn();
    const onChange = vi.fn();
    renderForm({ onSelectedChange, onChange });
    fireEvent.click(screen.getByRole("checkbox", { name: "JustJoin.IT" }));
    expect(onSelectedChange).toHaveBeenCalledWith(["rocketjobs", "justjoinit"]);
    fireEvent.change(screen.getByLabelText("Widełki od"), { target: { value: "120" } });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ salary: { from: 120, to: 0, unit: "hour" } }),
    );
  });

  it("dni w biurze tylko przy hybrydzie", () => {
    renderForm({ value: { ...EMPTY_LISTING_OPTIONS, workplace_type: "remote" } });
    expect(screen.queryByLabelText("Dni w biurze w tygodniu")).toBeNull();
  });
});
