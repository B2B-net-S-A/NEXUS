/**
 * Płace → miesiąc → „Rozliczenia” (etap 4, M3, M4, R7, R10).
 *
 * Zakładki tylko dla Płac i przy otwartym module; kolejka według pilności;
 * „Zatwierdź zgodne” bez własnego rozliczenia; porównanie z „Co się nie
 * zgadza” i decyzjami; miesiąc otwarty i awaria zapytania to zdania, nie
 * pusta lista. Dane fikcyjne (fixtures harnessu).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, delete: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/people/payroll/2026-10",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { hrConfig } from "@/app/preview/hr-fixtures";
import { mismatchDetail, queue, settlementScene } from "@/app/preview/hr-settlements/fixtures";
import { ToastProvider } from "@/components/Toast";
import { settlementKeys } from "@/lib/api/hr-settlements";

import { SettlementsQueue, queueStats } from "../SettlementsQueue";
import { payrollMonthTabs } from "../payroll-month-tabs";

function wrap(node: React.ReactNode, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  seed?.(client);
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  window.history.replaceState({}, "", "/");
});

describe("zakładki miesiąca Płac", () => {
  it("tylko Płace przy otwartym module; przełożony widzi sam miesiąc", () => {
    const open = { open_modules: { ...hrConfig().open_modules, settlements: true } };
    expect(payrollMonthTabs(open, true).map((tab) => tab.value)).toEqual([
      "month",
      "settlements",
      "ksef",
      "payments",
    ]);
    expect(payrollMonthTabs(open, false)).toEqual([]);
    expect(payrollMonthTabs(hrConfig(), true)).toEqual([]);
  });
});

describe("SettlementsQueue", () => {
  const scene = settlementScene();

  it("kolejka według pilności, zgodne do zatwierdzenia bez własnego", () => {
    wrap(<SettlementsQueue year={scene.year} month={scene.month} />, (client) =>
      client.setQueryData(settlementKeys.month(scene.year, scene.month), queue(scene)),
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Ewa Makietowa")).toBeInTheDocument();
    expect(within(rows[0]).getByText("rozbieżność +120,00")).toBeInTheDocument();
    // Własne rozliczenie Płac: bez „Zatwierdź”, z dopiskiem.
    const own = rows.find((row) => within(row).queryByText("Twoje — decyduje ktoś inny"));
    expect(own).toBeDefined();
    expect(within(own!).queryByRole("button", { name: "Zatwierdź" })).toBeNull();
    expect(screen.getByRole("button", { name: /Zatwierdź zgodne \(1\)/ })).toBeInTheDocument();
    expect(screen.getByText(/Kwota z NEXUSA to zamrożona linia/)).toBeInTheDocument();
  });

  it("liczby nad kolejką pokazują tylko to, co jest", () => {
    const ids = queueStats(queue(scene)).map((stat) => stat.id);
    expect(ids).toEqual(["people", "to-pay", "ready", "mismatch", "awaiting"]);
  });

  it("miesiąc otwarty i awaria to zdania, nie pusta lista", async () => {
    wrap(<SettlementsQueue year={scene.year} month={scene.month} />, (client) =>
      client.setQueryData(settlementKeys.month(scene.year, scene.month), {
        ...queue(scene),
        period_status: "open",
        rows: [],
      }),
    );
    expect(screen.getByText(/Rozliczenia powstają przy zamknięciu miesiąca/)).toBeInTheDocument();
  });

  it("awaria zapytania — komunikat z ponowieniem", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 500 } }));
    wrap(<SettlementsQueue year={scene.year} month={scene.month} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się wczytać rozliczeń/);
  });

  it("porównanie rozbieżności z decyzjami; „Uznaj różnicę” wymaga powodu", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/people/payroll/x?view=settlements&settlement=5003");
    wrap(<SettlementsQueue year={scene.year} month={scene.month} />, (client) => {
      client.setQueryData(settlementKeys.month(scene.year, scene.month), queue(scene));
      client.setQueryData(settlementKeys.detail(5003), mismatchDetail(scene));
    });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Co się nie zgadza")).toBeInTheDocument();
    expect(within(dialog).getByText(/153,3 na fakturze, 152 w raporcie/)).toBeInTheDocument();
    expect(within(dialog).getByText("Z NEXUSA (zamknięty miesiąc)")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Zatwierdź do zapłaty" })).toBeNull();

    await user.click(within(dialog).getByRole("button", { name: "Uznaj różnicę" }));
    await user.click(within(dialog).getByRole("button", { name: "Poproś drugą osobę" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Podaj powód uznania różnicy.");
    expect(mocks.post).not.toHaveBeenCalled();

    mocks.post.mockResolvedValue({ data: mismatchDetail(scene) });
    await user.type(within(dialog).getByLabelText("Powód uznania różnicy"), "Zaokrąglenie godzin");
    await user.click(within(dialog).getByRole("button", { name: "Poproś drugą osobę" }));
    expect(mocks.post).toHaveBeenCalledWith("/api/hr/settlements/5003/override", {
      reason: "Zaokrąglenie godzin",
    });
  });
});
