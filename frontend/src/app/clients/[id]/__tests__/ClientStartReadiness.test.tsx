import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get } }));

import { ClientStartReadiness } from "../ClientStartReadiness";
import { packFixture } from "./pack-fixture";

function forbidden() {
  return Object.assign(new Error("403"), { isAxiosError: true, response: { status: 403, data: {} } });
}

function serve(routes: Record<string, () => Promise<unknown>>) {
  mocks.get.mockImplementation((url: string) => {
    const route = routes[url];
    if (!route) throw new Error(`niespodziewane zapytanie: ${url}`);
    return route();
  });
}

const DOCS = "/api/start-documents/clients/7";
const SETTLEMENT = "/api/consultant-panel/clients/7/settlement";
const PACK = "/api/client-onboarding/clients/7/pack";

function renderCard(docsOn: boolean, packOn: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientStartReadiness clientId={7} docsOn={docsOn} packOn={packOn} />
    </QueryClientProvider>,
  );
}

describe("ClientStartReadiness", () => {
  beforeEach(() => {
    mocks.get.mockReset();
  });

  it("admin: cztery pola, domyślne wartości się nie liczą", async () => {
    serve({
      [DOCS]: async () => ({ data: { items: [], not_required: null } }),
      [SETTLEMENT]: async () => ({
        data: { client_id: 7, mode: null, instructions: "", updated_at: null },
      }),
      [PACK]: async () => ({
        data: packFixture({
          equipment: { ...packFixture().equipment, provider: "klienta" },
          first_day: { contact_id: null, place: null, time: null, bring: null },
        }),
      }),
    });
    renderCard(true, true);
    const card = await screen.findByRole("region", { name: "Start u klienta" });
    expect(within(card).getByText("1 z 4 ustalone")).toBeInTheDocument();
    expect(within(card).getByText("brak listy")).toBeInTheDocument();
    expect(within(card).getByText("nie wybrano")).toBeInTheDocument();
    expect(within(card).getByText("od klienta")).toBeInTheDocument();
    expect(within(card).getByText("nie wpisano miejsca")).toBeInTheDocument();
  });

  it("DL przy wyłączonym module: jedna część, bez licznika i bez zapytań o resztę", async () => {
    serve({ [DOCS]: async () => ({ data: { items: [], not_required: null } }) });
    const { container } = renderCard(true, false);
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(DOCS));
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalledWith(SETTLEMENT);
    expect(mocks.get).not.toHaveBeenCalledWith(PACK);
  });

  it("rozliczenie poza uprawnieniem (403) wypada z mianownika", async () => {
    serve({
      [DOCS]: async () => ({ data: { items: [], not_required: { at: "2026-11-20", by_name: null } } }),
      [SETTLEMENT]: async () => {
        throw forbidden();
      },
      [PACK]: async () => ({ data: packFixture() }),
    });
    renderCard(true, true);
    const card = await screen.findByRole("region", { name: "Start u klienta" });
    expect(within(card).getByText("3 z 3 ustalone")).toBeInTheDocument();
    expect(within(card).queryByText("Sposób rozliczania")).toBeNull();
  });
});
