import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientFormField, ClientFormView } from "@/lib/api/clientForms";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));

vi.mock("@/lib/api", () => ({ default: api }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import { ClientFormCard } from "../ClientFormCard";

const field = (over: Partial<ClientFormField>): ClientFormField => ({
  id: "p2",
  kind: "line",
  label: "Imię i nazwisko",
  section: null,
  row_label: null,
  table: null,
  value: "Anna Fikcyjna",
  source: "profile",
  quote: null,
  ...over,
});

const FIELDS = [
  field({}),
  field({
    id: "t1.r1.c1",
    kind: "cell",
    label: "Miejsce pracy",
    row_label: "Wiersz 1",
    table: "Doświadczenie zawodowe",
    value: "Bank Przykładowy S.A.",
    source: "cv",
  }),
  field({
    id: "t2.r5.c3",
    kind: "cell",
    label: "Stopień zaawansowania w skali 1-10",
    row_label: "Długość doświadczenia z frameworkiem Selenium",
    section: "Kompetencje dodatkowe",
    table: "Kompetencje",
    value: null,
    source: null,
  }),
];

const view = (over: Partial<ClientFormView> = {}): ClientFormView => ({
  client_document: "client_form",
  status: "filled",
  message: null,
  template: { file_id: 9, filename: "Zal 4b do SWZ Formularz CV.docx", summary: "3 pola" },
  template_changed: false,
  fields: FIELDS,
  extra_rows: [],
  missing: ["t2.r5.c3"],
  filled_at: "2026-10-26T10:00:00Z",
  updated_at: "2026-10-26T10:00:00Z",
  model: "claude-sonnet-5",
  ...over,
});

function renderCard(props: Partial<React.ComponentProps<typeof ClientFormCard>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientFormCard stageId={41} candidateName="Anna Fikcyjna" {...props} />
    </QueryClientProvider>,
  );
}

describe("ClientFormCard — formularz CV klienta (0522)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("bez wzoru odsyła do Plików rekrutacji", async () => {
    api.get.mockResolvedValue({ data: view({ status: "no_template", template: null, fields: [], missing: [] }) });
    renderCard();
    expect(await screen.findByTestId("client-form-no-template")).toHaveTextContent(
      "W Plikach rekrutacji nie ma wzoru formularza",
    );
    expect(screen.queryByText("Wypełnij z CV i screeningu")).toBeNull();
  });

  it("u klienta z CV firmowym nic nie pokazuje", async () => {
    api.get.mockResolvedValue({ data: view({ client_document: "company_cv" }) });
    const { container } = renderCard();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector("[data-testid=client-form-card]")).toBeNull());
  });

  it("niewypełniony formularz wypełnia się jednym kliknięciem", async () => {
    api.get.mockResolvedValue({ data: view({ status: "not_filled", missing: [] }) });
    api.post.mockResolvedValue({ data: view() });
    renderCard();
    fireEvent.click(await screen.findByText("Wypełnij z CV i screeningu"));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/candidates/stages/41/client-form/fill",
        null,
        expect.objectContaining({ timeout: 180_000 }),
      ),
    );
    expect(toast.showSuccess).toHaveBeenCalledWith("Formularz wypełniony — 1 do uzupełnienia.");
    expect(await screen.findByText("2 z 3 pól wypełnionych")).toBeInTheDocument();
    expect(screen.getByTestId("client-form-missing")).toHaveTextContent(
      "Długość doświadczenia z frameworkiem Selenium — Stopień zaawansowania w skali 1-10",
    );
  });

  it("model niedostępny — komunikat, formularz do uzupełnienia ręcznie", async () => {
    api.get.mockResolvedValue({ data: view({ status: "not_filled" }) });
    api.post.mockResolvedValue({
      data: view({ message: "Nie udało się wypełnić formularza automatycznie — uzupełnij pola ręcznie." }),
    });
    renderCard();
    fireEvent.click(await screen.findByText("Wypełnij z CV i screeningu"));
    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith(
        "Nie udało się wypełnić formularza automatycznie — uzupełnij pola ręcznie.",
      ),
    );
  });

  it("okno braków zapisuje tylko zmienione pola", async () => {
    api.get.mockResolvedValue({ data: view() });
    api.put.mockResolvedValue({ data: view({ missing: [] }) });
    renderCard();
    fireEvent.click(await screen.findByText("Uzupełnij braki"));
    const dialog = await screen.findByTestId("client-form-dialog");
    const rating = within(dialog).getByLabelText(/Stopień zaawansowania w skali 1-10/);
    fireEvent.change(rating, { target: { value: "7" } });
    fireEvent.click(within(dialog).getByText("Zapisz"));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/candidates/stages/41/client-form", {
        fields: { "t2.r5.c3": "7" },
      }),
    );
  });

  it("rekruter tylko do odczytu nie wypełnia ani nie zapisuje", async () => {
    api.get.mockResolvedValue({ data: view() });
    renderCard({ readOnly: true });
    expect(await screen.findByText("Pokaż formularz")).toBeInTheDocument();
    expect(screen.queryByText("Wypełnij ponownie")).toBeNull();
    expect(screen.queryByText("Wygeneruj też CV firmowe")).toBeNull();
  });

  it("awaria odczytu to komunikat z „Ponów”, nie pustka", async () => {
    api.get.mockRejectedValue(new Error("500"));
    renderCard();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać formularza klienta.",
    );
  });
});

describe("ClientFormDialog — kontekst wiersza", () => {
  it("pusty opis w „Wiersz 1” mówi, której firmy dotyczy", async () => {
    api.get.mockResolvedValue({
      data: view({
        fields: [
          ...FIELDS,
          field({
            id: "t1.r1.c4",
            kind: "cell",
            label: "Opis projektów",
            row_label: "Wiersz 1",
            table: "Doświadczenie zawodowe",
            value: null,
            source: null,
          }),
        ],
        missing: ["t2.r5.c3", "t1.r1.c4"],
      }),
    });
    renderCard();
    fireEvent.click(await screen.findByText("Uzupełnij braki"));
    const dialog = await screen.findByTestId("client-form-dialog");
    expect(within(dialog).getByText("Wiersz 1 · Bank Przykładowy S.A.")).toBeInTheDocument();
  });
});
