import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MaterialsTab } from "@/app/clients/[id]/MaterialsTab";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: (...args: unknown[]) => mocks.post(...args),
    patch: (...args: unknown[]) => mocks.patch(...args),
    put: (...args: unknown[]) => mocks.put(...args),
    delete: (...args: unknown[]) => mocks.delete(...args),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

const CLIENT_ID = 7;
const ONE_PAGERS_URL = `/api/clients/${CLIENT_ID}/one-pagers`;
const REQUIRED_DOCS_URL = `/api/clients/${CLIENT_ID}/required-documents`;
const TERMS_URL = `/api/clients/${CLIENT_ID}/contract-terms`;

function pager(id: number, title: string) {
  return {
    id,
    client_id: CLIENT_ID,
    title,
    description: null,
    version: null,
    filename: `${title}.pdf`,
    content_type: "application/pdf",
    size_bytes: 2048,
    uploaded_by: 1,
    uploaded_by_email: "dl@example.com",
    created_at: "2026-09-01T10:00:00Z",
  };
}

function requiredDoc(id: number, name: string) {
  return {
    id,
    client_id: CLIENT_ID,
    template_id: 3,
    name,
    description: null,
    is_mandatory: true,
    status: "pending",
    filename: null,
    content_type: null,
    size_bytes: null,
    uploaded_by: null,
    uploaded_by_email: null,
    uploaded_at: null,
    notes: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
  };
}

/** Kolejne odpowiedzi GET per URL; ostatnia zostaje na kolejne wywołania. */
function routeGets(routes: Record<string, unknown[]>) {
  const calls: Record<string, number> = {};
  mocks.get.mockImplementation((url: string) => {
    const responses = routes[url];
    if (!responses) return Promise.reject(new Error(`unexpected GET ${url}`));
    const i = calls[url] ?? 0;
    calls[url] = i + 1;
    return Promise.resolve({ data: responses[Math.min(i, responses.length - 1)] });
  });
}

function getCallsFor(url: string) {
  return mocks.get.mock.calls.filter(([u]) => u === url).length;
}

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MaterialsTab clientId={CLIENT_ID} />
    </QueryClientProvider>,
  );
}

function uploadDialog() {
  return screen.getByRole("heading", { name: "Dodaj one-pager" }).closest(
    "div.rounded-2xl",
  ) as HTMLElement;
}

function chooseFile(container: HTMLElement, file: File) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("missing file input");
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
});

describe("MaterialsTab — one-pagery (zapis)", () => {
  it("dodaje one-pager: multipart z tytułem z nazwy pliku, toast i odświeżenie listy", async () => {
    routeGets({ [ONE_PAGERS_URL]: [[], [pager(1, "Oferta ACME")]] });
    mocks.post.mockResolvedValue({ data: pager(1, "Oferta ACME") });

    renderTab();
    expect(
      await screen.findByText("Brak one-pagerów. Dodaj pierwszy, aby zacząć."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
    const dialog = uploadDialog();
    const send = within(dialog).getByRole("button", { name: "Wyślij" });
    expect(send).toBeDisabled();

    chooseFile(dialog, new File(["%PDF"], "Oferta ACME.pdf", { type: "application/pdf" }));
    const title = within(dialog).getByPlaceholderText("Oferta B2B dla ACME");
    expect(title).toHaveValue("Oferta ACME");
    fireEvent.change(within(dialog).getByPlaceholderText("1.0"), {
      target: { value: " 2.1 " },
    });
    fireEvent.click(send);

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, body, config] = mocks.post.mock.calls[0] as [string, FormData, unknown];
    expect(url).toBe(ONE_PAGERS_URL);
    expect((body.get("file") as File).name).toBe("Oferta ACME.pdf");
    expect(body.get("title")).toBe("Oferta ACME");
    expect(body.get("version")).toBe("2.1");
    expect(body.get("description")).toBeNull();
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });

    expect(mocks.showSuccess).toHaveBeenCalledWith("Dodano one-pager");
    expect(await screen.findByText("Oferta ACME")).toBeInTheDocument();
    expect(getCallsFor(ONE_PAGERS_URL)).toBe(2);
    expect(screen.queryByRole("heading", { name: "Dodaj one-pager" })).toBeNull();
  });

  it("odrzuca niedozwolony format przed wysyłką", async () => {
    routeGets({ [ONE_PAGERS_URL]: [[]] });

    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: "Dodaj" }));
    const dialog = uploadDialog();

    chooseFile(dialog, new File(["x"], "logo.png", { type: "image/png" }));

    expect(within(dialog).getByText("Tylko pliki PDF/DOCX/DOC")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Wyślij" })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each([
    [403, "Brak uprawnień do materiałów klienta"],
    [422, "Plik jest uszkodzony"],
  ])("błąd %i z backendu → toast z komunikatem i dialog zostaje otwarty", async (status, detail) => {
    routeGets({ [ONE_PAGERS_URL]: [[]] });
    mocks.post.mockRejectedValue({ response: { status, data: { detail } } });

    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: "Dodaj" }));
    const dialog = uploadDialog();
    chooseFile(dialog, new File(["%PDF"], "umowa.pdf", { type: "application/pdf" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Wyślij" }));

    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith(detail));
    expect(within(uploadDialog()).getByText(detail)).toBeInTheDocument();
    expect(mocks.showSuccess).not.toHaveBeenCalled();
    expect(getCallsFor(ONE_PAGERS_URL)).toBe(1);
    expect(within(uploadDialog()).getByRole("button", { name: "Wyślij" })).toBeEnabled();
  });

  it("usuwa one-pager dopiero po potwierdzeniu i odświeża listę", async () => {
    routeGets({ [ONE_PAGERS_URL]: [[pager(1, "Oferta ACME")], []] });
    mocks.delete.mockResolvedValue({});

    renderTab();
    const row = (await screen.findByText("Oferta ACME")).closest("li") as HTMLElement;

    fireEvent.click(within(row).getByTitle("Usuń"));
    expect(within(row).getByText("Na pewno?")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "Anuluj" }));
    expect(mocks.delete).not.toHaveBeenCalled();

    fireEvent.click(within(row).getByTitle("Usuń"));
    fireEvent.click(within(row).getByRole("button", { name: "Usuń" }));

    await waitFor(() =>
      expect(mocks.delete).toHaveBeenCalledWith(`${ONE_PAGERS_URL}/1`),
    );
    expect(await screen.findByText("Brak one-pagerów. Dodaj pierwszy, aby zacząć.")).toBeInTheDocument();
    expect(mocks.showSuccess).toHaveBeenCalledWith("Usunięto one-pager");
  });

  it("nieudane usunięcie (403) → toast błędu, wiersz zostaje", async () => {
    routeGets({ [ONE_PAGERS_URL]: [[pager(1, "Oferta ACME")]] });
    mocks.delete.mockRejectedValue({ response: { status: 403, data: { detail: "Forbidden" } } });

    renderTab();
    const row = (await screen.findByText("Oferta ACME")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByTitle("Usuń"));
    fireEvent.click(within(row).getByRole("button", { name: "Usuń" }));

    // Komponent świadomie pokazuje stały komunikat, nie `detail` z backendu.
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się usunąć"));
    expect(screen.getByText("Oferta ACME")).toBeInTheDocument();
    expect(getCallsFor(ONE_PAGERS_URL)).toBe(1);
  });
});

describe("MaterialsTab — wymagane dokumenty i warunki (zapis)", () => {
  it("wgranie pliku do wymogu z błędem 422 pokazuje komunikat backendu", async () => {
    routeGets({
      [ONE_PAGERS_URL]: [[]],
      [REQUIRED_DOCS_URL]: [[requiredDoc(9, "NDA")]],
    });
    mocks.post.mockRejectedValue({
      response: { status: 422, data: { detail: "Nieobsługiwany typ pliku" } },
    });

    renderTab();
    fireEvent.click(screen.getByRole("button", { name: "Wymagane dokumenty" }));
    const row = (await screen.findByText("NDA")).closest("li") as HTMLElement;

    chooseFile(row, new File(["x"], "nda.pdf", { type: "application/pdf" }));

    await waitFor(() =>
      expect(mocks.showError).toHaveBeenCalledWith("Nieobsługiwany typ pliku"),
    );
    expect(mocks.post.mock.calls[0][0]).toBe(`${REQUIRED_DOCS_URL}/9/upload`);
    expect(getCallsFor(REQUIRED_DOCS_URL)).toBe(1);
  });

  it("zmiana statusu wymogu wysyła PATCH i odświeża listę", async () => {
    routeGets({
      [ONE_PAGERS_URL]: [[]],
      [REQUIRED_DOCS_URL]: [
        [requiredDoc(9, "NDA")],
        [{ ...requiredDoc(9, "NDA"), status: "signed" }],
      ],
    });
    mocks.patch.mockResolvedValue({ data: {} });

    renderTab();
    fireEvent.click(screen.getByRole("button", { name: "Wymagane dokumenty" }));
    await screen.findByText("NDA");

    fireEvent.click(screen.getByTitle("Zmień status"));
    fireEvent.click(await screen.findByRole("button", { name: "Podpisany" }));

    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith(`${REQUIRED_DOCS_URL}/9`, {
        status: "signed",
      }),
    );
    expect(mocks.showSuccess).toHaveBeenCalledWith("Status: Podpisany");
    await waitFor(() => expect(getCallsFor(REQUIRED_DOCS_URL)).toBe(2));
  });

  it("zapis warunków kontraktowych wysyła tylko zmienione pola", async () => {
    routeGets({
      [ONE_PAGERS_URL]: [[]],
      [TERMS_URL]: [
        {
          id: 1,
          client_id: CLIENT_ID,
          off_limits_months: 12,
          off_limits_scope: "cała grupa",
          off_limits_notes: null,
          internalization_fee_pct: null,
          internalization_min_months: null,
          internalization_notice_days: null,
          internalization_notes: null,
          payment_net_days: 30,
          payment_currency: "PLN",
          payment_invoice_cycle: null,
          payment_late_fees: null,
          payment_notes: null,
          notice_period_days: null,
          warranty_replacement_days: null,
          warranty_notes: null,
          other_clauses: null,
          updated_at: "2026-09-01T10:00:00Z",
          updated_by_email: "dl@example.com",
        },
      ],
    });
    mocks.put.mockRejectedValueOnce({ response: { status: 403 } });

    renderTab();
    fireEvent.click(screen.getByRole("button", { name: "Warunki kontraktowe" }));
    const scope = await screen.findByDisplayValue("cała grupa");
    fireEvent.change(scope, { target: { value: "tylko spółka matka" } });

    const form = scope.closest("form") as HTMLFormElement;
    fireEvent.submit(form);

    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(TERMS_URL, {
        off_limits_scope: "tylko spółka matka",
      }),
    );
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się zapisać"));
    expect(mocks.showSuccess).not.toHaveBeenCalled();
  });
});
