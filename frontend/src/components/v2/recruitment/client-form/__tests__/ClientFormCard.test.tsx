import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientFormField, ClientFormView } from "@/lib/api/clientForms";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
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

describe("ClientFormCard — tabela punktowa (0525)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const scoreView = (over: Partial<ClientFormView> = {}): ClientFormView =>
    view({
      kind: "score",
      template: { file_id: 12, filename: "Zal 5b Tabela punktowa.xlsx", summary: "7 pól" },
      points: { total: 6, max: 13 },
      fields: [
        field({}),
        field({
          id: "s0.r12.c4",
          kind: "cell",
          label: "Wynik (0–5 pkt)",
          row_label: "Długość doświadczenia w automatyzacji testów",
          table: "Kryteria punktowane",
          value: null,
          source: null,
          max_points: 5,
        }),
      ],
      missing: ["s0.r12.c4"],
      ...over,
    });

  it("bez wzoru Excela karty nie ma", async () => {
    api.get.mockResolvedValue({
      data: scoreView({ status: "no_template", template: null, fields: [], missing: [] }),
    });
    const { container } = renderCard({ kind: "score" });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/candidates/stages/41/client-form?kind=score"));
    await waitFor(() => expect(container.querySelector("[data-testid=client-score-card]")).toBeNull());
  });

  it("pokazuje punkty i pobiera Excel, wypełnia z parametrem rodzaju", async () => {
    api.get.mockResolvedValue({ data: scoreView({ status: "not_filled", points: { total: 0, max: 13 } }) });
    api.post.mockResolvedValue({ data: scoreView() });
    renderCard({ kind: "score" });
    fireEvent.click(await screen.findByText("Wypełnij z CV i screeningu"));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/candidates/stages/41/client-form/fill?kind=score",
        null,
        expect.objectContaining({ timeout: 180_000 }),
      ),
    );
    expect(await screen.findByText("Punkty: 6 z 13")).toBeInTheDocument();
    expect(screen.getByText("Pobierz Excel")).toBeInTheDocument();
    expect(screen.queryByText("Wygeneruj też CV firmowe")).toBeNull();
  });

  it("0755: wgrany z dysku — zielony wiersz, plik idzie zamiast wypełnienia, „Zastąp” i „Usuń”", async () => {
    api.get.mockResolvedValue({ data: view({ status: "not_filled", missing: [], fields: FIELDS, filled_at: null }) });
    const uploaded = view({
      status: "not_filled",
      filled_at: null,
      uploaded: {
        filename: "Formularz CV Anna — wypełniony.docx",
        content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size: 4096,
        uploaded_at: "2026-11-23T13:03:00Z",
      },
    });
    api.post.mockResolvedValue({ data: uploaded });
    renderCard();
    const button = await screen.findByRole("button", { name: /Wgraj wypełniony formularz/ });
    expect(button).toBeInTheDocument();
    const input = screen.getByTestId("client-form-upload-input") as HTMLInputElement;
    expect(input.accept).toBe(".docx,.pdf");
    const file = new File(["x"], "Formularz CV Anna — wypełniony.docx");
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const [url, body] = api.post.mock.calls[0] as [string, FormData];
    expect(url).toBe("/api/candidates/stages/41/client-form/upload");
    expect((body.get("file") as File).name).toBe("Formularz CV Anna — wypełniony.docx");
    const row = await screen.findByTestId("client-form-uploaded");
    expect(row).toHaveTextContent("Formularz CV Anna — wypełniony.docx");
    expect(row).toHaveTextContent(/Wgrany z dysku · 23\.11\.2026.*14:03/);
    expect(row).toHaveTextContent("ten plik idzie do QC i do klienta zamiast wypełnienia z NEXUSA");
    expect(screen.getByRole("button", { name: /Zastąp plik/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz wgrany plik/ })).toBeInTheDocument();

    api.delete.mockResolvedValue({ data: view({ status: "not_filled", filled_at: null, uploaded: null }) });
    fireEvent.click(screen.getByRole("button", { name: /^Usuń$/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Usuń plik" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith("/api/candidates/stages/41/client-form/upload"),
    );
    await waitFor(() => expect(screen.queryByTestId("client-form-uploaded")).toBeNull());
  });

  it("0755: tabela punktowa przyjmuje tylko Excel", async () => {
    api.get.mockResolvedValue({ data: view({ kind: "score", status: "not_filled", filled_at: null }) });
    renderCard({ kind: "score" });
    expect(await screen.findByRole("button", { name: /Wgraj wypełniony Excel/ })).toBeInTheDocument();
    expect((screen.getByTestId("client-score-upload-input") as HTMLInputElement).accept).toBe(".xlsx");
  });

  it("0755: bez uprawnień zapisu nie ma wgrywania", async () => {
    api.get.mockResolvedValue({ data: view() });
    renderCard({ readOnly: true });
    await screen.findByTestId("client-form-card");
    expect(screen.queryByRole("button", { name: /Wgraj wypełniony/ })).toBeNull();
  });
});
