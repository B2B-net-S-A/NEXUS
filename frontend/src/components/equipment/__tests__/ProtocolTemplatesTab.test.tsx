import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProtocolTemplateList } from "@/lib/api/client-onboarding";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  toast: vi.fn(),
  confirm: vi.fn(async () => true),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, patch: mocks.patch },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

import { ProtocolTemplatesTab, fileProblem } from "../ProtocolTemplatesTab";

const MB = 1024 * 1024;

// Dane fikcyjne — repo jest publiczne.
const LIST: ProtocolTemplateList = {
  items: [
    {
      id: 11,
      kind: "wydanie",
      name: "Standard z kaucją",
      description: "zwrot do naszego biura",
      file_name: "kaucja.docx",
      file_size: 20_000,
      fields: ["holder_name", "lines", "number", "protocol_date"],
      is_active: true,
      created_at: null,
      packs: 2,
      protocols: 5,
    },
  ],
  fields: [
    { field: "number", label: "numer protokołu", scope: "protocol" },
    { field: "line.name", label: "nazwa sprzętu", scope: "line" },
  ],
  required: {
    wydanie: ["number", "protocol_date", "holder_name", "lines"],
    zwrot: ["number", "protocol_date", "holder_name", "lines"],
  },
  max_bytes: 2 * MB,
};

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProtocolTemplatesTab />
    </QueryClientProvider>,
  );
}

function apiError(status: number, detail: string) {
  return Object.assign(new Error(detail), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });
}

describe("fileProblem", () => {
  it("przepuszcza tylko .docx w limicie", () => {
    const docx = new File(["x"], "wzor.docx");
    expect(fileProblem(docx, 2 * MB)).toBeNull();
    expect(fileProblem(null, 2 * MB)).toMatch(/Wybierz plik/);
    expect(fileProblem(new File(["x"], "wzor.doc"), 2 * MB)).toMatch(/\.docx/);
    expect(fileProblem(new File([], "pusty.docx"), 2 * MB)).toMatch(/pusty albo większy niż 2 MB/);
  });
});

describe("ProtocolTemplatesTab", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.patch.mockReset();
    mocks.toast.mockReset();
    mocks.confirm.mockClear();
  });

  it("pokazuje wzory z użyciem w pakietach i protokołach", async () => {
    mocks.get.mockResolvedValue({ data: LIST });
    renderTab();
    const row = (await screen.findByText("Standard z kaucją")).closest("tr")!;
    expect(within(row).getByText("Wydanie")).toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();
    expect(within(row).getByText("5")).toBeInTheDocument();
    expect(within(row).getByText("w użyciu")).toBeInTheDocument();
    expect(screen.getByText("nazwa sprzętu").previousElementSibling).toHaveTextContent("{{ line.name }}");
  });

  it("odmowa serwera przy wgraniu (np. wzór sięga poza dane) zostaje w oknie", async () => {
    mocks.get.mockResolvedValue({ data: LIST });
    mocks.post.mockRejectedValue(
      apiError(422, "Wzór próbuje sięgnąć poza dane protokołu — takiego wzoru nie da się użyć."),
    );
    renderTab();
    await screen.findByText("Standard z kaucją");
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wzór" }));
    fireEvent.change(screen.getByLabelText(/Nazwa/), { target: { value: "Zwrot u klienta" } });
    const file = new File(["PK"], "zwrot.docx");
    fireEvent.change(screen.getByLabelText(/Plik \.docx/), { target: { files: [file] } });
    fireEvent.click(screen.getAllByRole("button", { name: "Dodaj wzór" }).at(-1)!);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const body = mocks.post.mock.calls[0][1] as FormData;
    expect(body.get("kind")).toBe("wydanie");
    expect(body.get("name")).toBe("Zwrot u klienta");
    expect(await screen.findByRole("alert")).toHaveTextContent(/poza dane protokołu/);
  });

  it("zły plik nie idzie na serwer", async () => {
    mocks.get.mockResolvedValue({ data: LIST });
    renderTab();
    await screen.findByText("Standard z kaucją");
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wzór" }));
    fireEvent.change(screen.getByLabelText(/Nazwa/), { target: { value: "Wzór" } });
    fireEvent.change(screen.getByLabelText(/Plik \.docx/), {
      target: { files: [new File(["x"], "wzor.pdf")] },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Dodaj wzór" }).at(-1)!);
    expect(await screen.findByRole("alert")).toHaveTextContent(/\.docx/);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("wycofanie pyta o potwierdzenie i pokazuje odmowę serwera", async () => {
    mocks.get.mockResolvedValue({ data: LIST });
    mocks.patch.mockRejectedValue(
      apiError(409, "Wzór jest wybrany w pakiecie 2 klientów — najpierw wybierz tam inny wzór."),
    );
    renderTab();
    await screen.findByText("Standard z kaucją");
    fireEvent.click(screen.getByRole("button", { name: "Wycofaj" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledWith(
      "/api/equipment/protocol-templates/11",
      { is_active: false },
    ));
    expect(mocks.confirm).toHaveBeenCalled();
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(expect.stringContaining("w pakiecie 2 klientów"), "error"),
    );
  });

  it("awaria listy nie wygląda jak brak wzorów", async () => {
    mocks.get.mockRejectedValue(apiError(500, "błąd"));
    renderTab();
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma jeszcze własnych wzorów/)).not.toBeInTheDocument();
  });
});
