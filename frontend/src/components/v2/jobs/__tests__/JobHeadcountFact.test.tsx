/**
 * `JobHeadcountFact` — „Szukamy N osób ✎” w nagłówku rekrutacji (07.11.2026).
 *
 * Ten sam zapis co wiersz „Liczba osób” w Profilu Championa › Zespół
 * (`PATCH /api/jobs/{id}` z samym `headcount`); bez pełnej edycji sam odczyt.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JobHeadcountFact,
  headcountFactText,
} from "@/components/v2/jobs/JobHeadcountFact";

const patchMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    patch: (...args: unknown[]) => patchMock(...args),
  },
}));

function renderFact(props: Partial<React.ComponentProps<typeof JobHeadcountFact>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <JobHeadcountFact jobId={501} headcount={1} canEdit {...props} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

beforeEach(() => {
  patchMock.mockReset();
});

describe("headcountFactText", () => {
  it("mówi dopełniaczem po „szukamy”", () => {
    expect(headcountFactText(1)).toBe("Szukamy 1 osoby");
    expect(headcountFactText(2)).toBe("Szukamy 2 osób");
    expect(headcountFactText(5)).toBe("Szukamy 5 osób");
    expect(headcountFactText(22)).toBe("Szukamy 22 osób");
  });

  it("bez liczby i w zamkniętej rekrutacji nie mówi „szukamy”", () => {
    expect(headcountFactText(null)).toBe("Liczba osób: nie podano");
    expect(headcountFactText(3, true)).toBe("Liczba osób: 3");
  });
});

describe("JobHeadcountFact", () => {
  it("bez prawa edycji to sam odczyt — bez przycisku i okienka", () => {
    renderFact({ canEdit: false, headcount: 3 });
    const chip = screen.getByTestId("job-header-headcount");
    expect(chip.tagName).toBe("SPAN");
    expect(chip).toHaveAccessibleName("Szukamy 3 osób");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("poniżej 2xl sama liczba, pełne zdanie od 2xl i w nazwie przycisku", () => {
    renderFact({ headcount: 4 });
    const chip = screen.getByRole("button", { name: "Szukamy 4 osób — zmień liczbę osób" });
    expect(chip.querySelector(".\\32xl\\:hidden")).toHaveTextContent("4");
    expect(chip.querySelector(".\\32xl\\:inline")).toHaveTextContent("Szukamy 4 osób");
  });

  it("zapisuje samą liczbę osób przez PATCH i odświeża rekrutację", async () => {
    patchMock.mockResolvedValue({ data: {} });
    const { invalidate } = renderFact({ headcount: 1 });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /Szukamy 1 osoby — zmień/ }));
    const input = await screen.findByRole("spinbutton", { name: "Liczba osób" });
    expect(input).toHaveValue(1);
    await user.clear(input);
    await user.type(input, "3");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith("/api/jobs/501", { headcount: 3 }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "501"] });
    await waitFor(() =>
      expect(screen.queryByTestId("job-headcount-popover")).not.toBeInTheDocument(),
    );
  });

  it("nie zapisuje zera ani pustego pola", async () => {
    renderFact({ headcount: 2 });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Szukamy 2 osób — zmień/ }));
    const input = await screen.findByRole("spinbutton", { name: "Liczba osób" });
    await user.clear(input);
    await user.type(input, "0");
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
    expect(screen.getByText("Podaj liczbę od 1 w górę.")).toBeInTheDocument();
    expect(patchMock).not.toHaveBeenCalled();
  });

  it("odmowa serwera zostaje w okienku przy polu", async () => {
    patchMock.mockRejectedValue({
      isAxiosError: true,
      response: { status: 403, data: { detail: "Brak uprawnień do zmiany rekrutacji." } },
    });
    renderFact({ headcount: 1 });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Szukamy 1 osoby — zmień/ }));
    await user.click(await screen.findByRole("button", { name: "Zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/./);
    expect(screen.getByTestId("job-headcount-popover")).toBeInTheDocument();
  });
});
