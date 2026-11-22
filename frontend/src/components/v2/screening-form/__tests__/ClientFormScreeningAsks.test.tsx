import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientFormField, ClientFormView } from "@/lib/api/clientForms";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: api }));

import { ClientFormScreeningAsks } from "../ClientFormScreeningAsks";

const ask = (id: string, question: string, over: Partial<ClientFormField> = {}): ClientFormField => ({
  id,
  kind: "cell",
  label: "Liczba lat doświadczenia",
  section: null,
  row_label: null,
  table: null,
  value: null,
  source: null,
  quote: null,
  years: {
    kind: "competency",
    basis: [],
    skills: null,
    minimum_months: null,
    thresholds: [],
    max_points: null,
    question,
    ask: true,
    months: 0,
  },
  ...over,
});

const view = (fields: ClientFormField[], status: ClientFormView["status"] = "filled"): ClientFormView => ({
  client_document: "client_form",
  status,
  message: null,
  template: null,
  template_changed: false,
  fields,
  extra_rows: [],
  missing: [],
  filled_at: null,
  updated_at: null,
  model: null,
});

function renderAsks() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientFormScreeningAsks stageId={7} />
    </QueryClientProvider>,
  );
}

describe("ClientFormScreeningAsks — braki lat w ściądze screeningu", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje pytania wysłane z okna formularza, bez już uzupełnionych", async () => {
    api.get.mockResolvedValue({
      data: view([
        ask("a", "Xray — w której firmie i od kiedy do kiedy?"),
        ask("b", "SQL — w której firmie i od kiedy do kiedy?", { value: "2 lata" }),
        ask("c", "Rejestry — w której firmie i od kiedy do kiedy?", {
          years: { ...ask("c", "x").years!, ask: false },
        }),
      ]),
    });
    renderAsks();
    expect(await screen.findByText("Do dopytania pod formularz klienta · 1")).toBeInTheDocument();
    expect(screen.getByText("Xray — w której firmie i od kiedy do kiedy?")).toBeInTheDocument();
    expect(screen.queryByText(/SQL —/)).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/api/candidates/stages/7/client-form");
  });

  it("u klienta bez formularza nic nie pokazuje", async () => {
    api.get.mockResolvedValue({ data: view([], "no_template") });
    const { container } = renderAsks();
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria odczytu nie psuje formularza screeningu — podpowiedzi po prostu nie ma", async () => {
    api.get.mockRejectedValue(new Error("500"));
    const { container } = renderAsks();
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
