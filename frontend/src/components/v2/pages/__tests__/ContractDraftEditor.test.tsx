import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
  finalize: vi.fn(),
  openFile: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  contractsApi: { draft: { get: mocks.get, update: mocks.update, finalize: mocks.finalize } },
}));
vi.mock("@/lib/authenticated-files", () => ({ openAuthenticatedFile: mocks.openFile }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: mocks.error, showToast: vi.fn() }),
}));

// TipTap/ProseMirror zastąpiony atrapą: test sprawdza logikę wczytania,
// autozapisu i finalizacji, nie sam edytor.
type Handler = () => void;
interface FakeEditor {
  html: string;
  handlers: Set<Handler>;
  setContent: ReturnType<typeof vi.fn>;
  on: (event: string, handler: Handler) => void;
  off: (event: string, handler: Handler) => void;
  getHTML: () => string;
  commands: { setContent: ReturnType<typeof vi.fn> };
  type: (html: string) => void;
}
let editor: FakeEditor;
function makeEditor(): FakeEditor {
  const handlers = new Set<Handler>();
  const setContent = vi.fn((html: string) => {
    fake.html = html;
  });
  const fake: FakeEditor = {
    html: "",
    handlers,
    setContent,
    on: (_event, handler) => handlers.add(handler),
    off: (_event, handler) => handlers.delete(handler),
    getHTML: () => fake.html,
    commands: { setContent },
    type: (html) => {
      fake.html = html;
      handlers.forEach((h) => h());
    },
  };
  return fake;
}
vi.mock("@tiptap/react", () => ({
  useEditor: () => editor,
  EditorContent: () => <div data-testid="editor" />,
}));
vi.mock("@tiptap/starter-kit", () => ({ default: {} }));

import { DraftEditor } from "../ContractDraftEditor";
import type { ContractDraftResponse } from "@/lib/api";

function draft(overrides: Partial<ContractDraftResponse> = {}): ContractDraftResponse {
  return {
    contract_id: 11,
    content_html: "<p>Umowa B2B z Firma Testowa sp. z o.o.</p>",
    template_id: 1,
    updated_at: "2026-11-24T09:00:00Z",
    updated_by: 2,
    updated_by_name: "Jan Testowy",
    available_templates: [
      { id: 1, name: "B2B standard", is_default: true },
      { id: 2, name: "B2B z NDA", is_default: false },
    ] as ContractDraftResponse["available_templates"],
    rendered_from_default: false,
    ...overrides,
  };
}

function renderEditor(meta: Record<string, unknown> = { client_name: "Firma Testowa sp. z o.o.", contract_type: "b2b" }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DraftEditor contractId={11} candidateName="Anna Przykładowa" contractMeta={meta} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
  editor = makeEditor();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-11-24T10:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("DraftEditor — wczytanie", () => {
  it("pokazuje kontrakt, klienta, kto i kiedy zapisał, i wczytuje treść do edytora", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    renderEditor();
    expect(await screen.findByText(/kontrakt #\s*11/)).toHaveTextContent("Draft umowy dla Anna Przykładowa — kontrakt #11 (Firma Testowa sp. z o.o.)");
    expect(screen.getByText("zapisano 1h temu przez Jan Testowy")).toBeInTheDocument();
    await waitFor(() =>
      expect(editor.setContent).toHaveBeenCalledWith("<p>Umowa B2B z Firma Testowa sp. z o.o.</p>", { emitUpdate: false }),
    );
    expect(screen.getByRole("option", { name: "B2B standard(domyślny)" })).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("1");
  });

  it("pusty draft bez szablonów: ostrzeżenie o typie umowy, druk i finalizacja wyłączone", async () => {
    mocks.get.mockResolvedValue({
      data: draft({ content_html: null, template_id: null, updated_at: null, updated_by_name: null, available_templates: [] }),
    });
    renderEditor({ contract_type: "uop" });
    expect(await screen.findByText("jeszcze nie zapisano")).toBeInTheDocument();
    expect(screen.getByText(/Brak szablonu dla typu/)).toHaveTextContent("Brak szablonu dla typu uop.");
    expect(screen.getByRole("button", { name: /Drukuj \/ PDF/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Sfinalizuj umowę/ })).toBeDisabled();
    await waitFor(() => expect(editor.setContent).toHaveBeenCalledWith("<p></p>", { emitUpdate: false }));
  });

  it.todo(
    "awaria GET /api/contracts/{id}/draft pokazuje błąd z ponowieniem — dziś ContractDraftEditor.tsx:145 (`isLoading || !data`) zostawia „Ładowanie draftu…” na zawsze",
  );
});

describe("DraftEditor — autozapis i szablon", () => {
  it("ręczna edycja zapisuje się po 2 s z treścią z edytora; bez zmian nie ma zapisu", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    mocks.update.mockResolvedValue({ data: draft() });
    renderEditor();
    await screen.findByText(/kontrakt #/);
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    expect(mocks.update).not.toHaveBeenCalled();
    act(() => editor.type("<p>Stawka 150 zł/h netto</p>"));
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(11, { content_html: "<p>Stawka 150 zł/h netto</p>" }));
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Zapisano draft"));
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    expect(mocks.update).toHaveBeenCalledTimes(1);
  });

  it("nieudany autozapis mówi o błędzie", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    mocks.update.mockRejectedValue(new Error("500"));
    renderEditor();
    await screen.findByText(/kontrakt #/);
    act(() => editor.type("<p>x</p>"));
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith("Nie udało się zapisać draftu"));
  });

  it("zmiana szablonu pyta o nadpisanie; „Anuluj” nic nie zmienia, „Wczytaj szablon” wysyła template_id", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    mocks.update.mockResolvedValue({ data: draft({ template_id: 2 }) });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();
    await screen.findByText(/kontrakt #/);
    await user.selectOptions(screen.getByRole("combobox"), "2");
    expect(screen.getByText(/nadpisze obecną treść draftu/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByText(/nadpisze obecną treść draftu/)).not.toBeInTheDocument();
    expect(mocks.update).not.toHaveBeenCalled();
    await user.selectOptions(screen.getByRole("combobox"), "2");
    await user.click(screen.getByRole("button", { name: "Wczytaj szablon" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(11, { template_id: 2 }));
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Wczytano nowy szablon"));
  });

  it("wybór tego samego szablonu albo pustej pozycji nie pyta o nadpisanie", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();
    await screen.findByText(/kontrakt #/);
    await user.selectOptions(screen.getByRole("combobox"), "");
    expect(screen.queryByText(/nadpisze obecną treść draftu/)).not.toBeInTheDocument();
  });

  it("błąd wczytania szablonu idzie komunikatem", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    mocks.update.mockRejectedValue(new Error("500"));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();
    await screen.findByText(/kontrakt #/);
    await user.selectOptions(screen.getByRole("combobox"), "2");
    await user.click(screen.getByRole("button", { name: "Wczytaj szablon" }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith("Nie udało się wczytać szablonu"));
  });
});

describe("DraftEditor — druk i finalizacja", () => {
  it("druk otwiera HTML z autoryzacją; błąd otwarcia idzie komunikatem", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    mocks.openFile.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("401"));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();
    await user.click(await screen.findByRole("button", { name: /Drukuj \/ PDF/ }));
    expect(mocks.openFile).toHaveBeenCalledWith("/api/contracts/11/draft/render-pdf", "text/html");
    await user.click(screen.getByRole("button", { name: /Drukuj \/ PDF/ }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith("Nie udało się otworzyć umowy do druku."));
  });

  it("finalizacja po potwierdzeniu zmienia status umowy", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    mocks.finalize.mockResolvedValue({ data: { contract_id: 11, status: "active", document_id: 5, document_filename: "umowa.pdf" } });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();
    await user.click(await screen.findByRole("button", { name: /Sfinalizuj umowę/ }));
    expect(screen.getByText(/status kontraktu zmieni się z draft na active/)).toBeInTheDocument();
    expect(mocks.finalize).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Tak, finalizuj" }));
    await waitFor(() => expect(mocks.finalize).toHaveBeenCalledWith(11));
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Umowa sfinalizowana — status: aktywna"));
    expect(screen.queryByText(/status kontraktu zmieni się/)).not.toBeInTheDocument();
  });

  it("odmowa finalizacji z listą braków mówi, co uzupełnić; inna odmowa — ogólny komunikat", async () => {
    mocks.get.mockResolvedValue({ data: draft() });
    mocks.finalize
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: { message: "Missing required fields", missing: ["start_date", "rate_client"] } } } })
      .mockRejectedValueOnce({ response: { status: 500, data: { detail: "boom" } } });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();
    await user.click(await screen.findByRole("button", { name: /Sfinalizuj umowę/ }));
    await user.click(screen.getByRole("button", { name: "Tak, finalizuj" }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(expect.stringMatching(/^Uzupełnij wymagane pola: /)));
    // Okno zostaje — można spróbować ponownie albo anulować.
    await user.click(screen.getByRole("button", { name: "Tak, finalizuj" }));
    await waitFor(() => expect(mocks.error).toHaveBeenLastCalledWith("Nie udało się sfinalizować draftu"));
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByText(/status kontraktu zmieni się/)).not.toBeInTheDocument();
  });

  it.todo(
    "odmowa finalizacji z `missing` pokazuje polskie nazwy pól (CONTRACT_FIELD_LABELS z lib/api-error) — dziś ContractDraftEditor.tsx:138 skleja surowe klucze bez spacji: „Uzupełnij wymagane pola: start_date,rate_client”",
  );
});
