import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, default: { get: vi.fn(() => Promise.resolve({ data: [] })) } };
});

import {
  StageFilterPanel,
  type StageFilterValue,
} from "@/components/v2/filters/StageFilterPanel";

const EMPTY: StageFilterValue = {
  columns: [],
  stages: [],
  currentOnly: false,
  clientIds: [],
  movedByIds: [],
  movedAfter: "",
  movedBefore: "",
};

function renderPanel(patch: Partial<StageFilterValue> = {}) {
  const onChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StageFilterPanel value={{ ...EMPTY, ...patch }} onChange={onChange} />
    </QueryClientProvider>,
  );
  return onChange;
}

describe("StageFilterPanel — „Dodany na etap / przez / od–do” (19.10.2026)", () => {
  it("nazywa pola tak, jak pyta rekruter", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole("button", { name: /Etap/ }));
    expect(await screen.findByText("Dodany na etap")).toBeInTheDocument();
    expect(screen.getByText("Dodany przez")).toBeInTheDocument();
    expect(screen.getByText("Kto przesunął osobę na ten etap.")).toBeInTheDocument();
    expect(screen.getByText("Dodany od – do")).toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "Tylko osoby, które nadal są na tym etapie" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Umieszczony przez użytkownika")).toBeNull();
  });

  it("lista etapów to kolumny Tablicy z „QC CV”, bez kodów jak „Interview”", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel();
    await user.click(screen.getByRole("button", { name: /Etap/ }));
    await user.click(await screen.findByRole("button", { name: /Dowolny etap/ }));
    const list = await screen.findByRole("listbox");
    const labels = within(list)
      .getAllByRole("option")
      .map((o) => o.textContent?.trim());
    expect(labels).toEqual([
      "Nowi",
      "Screening",
      "Zweryfikowany",
      "QC CV",
      "CV wysłane",
      "Rozmowa u klienta",
      "Akceptacja i umowa",
      "Zatrudniony",
      "Zamknięci",
    ]);
    await user.click(within(list).getByText("QC CV"));
    expect(onChange).toHaveBeenLastCalledWith({ columns: ["cv_qc"] });
  });

  it("wybór kilku kolumn zapisuje się w kolejności Tablicy", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel({ columns: ["cv_sent"] });
    await user.click(screen.getByRole("button", { name: /Etap: CV wysłane/ }));
    await user.click(await screen.findByRole("button", { name: /^CV wysłane$/ }));
    await user.click(within(await screen.findByRole("listbox")).getByText("Nowi"));
    expect(onChange).toHaveBeenLastCalledWith({ columns: ["new", "cv_sent"] });
  });

  it("kod etapu ze starego linku widać i da się go zdjąć", async () => {
    const user = userEvent.setup();
    const onChange = renderPanel({ stages: ["interview"] });
    await user.click(screen.getByRole("button", { name: /Etap: Interview/ }));
    expect(await screen.findByText("Ze starego linku: Interview")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Usuń" }));
    expect(onChange).toHaveBeenLastCalledWith({ stages: [] });
  });
});
