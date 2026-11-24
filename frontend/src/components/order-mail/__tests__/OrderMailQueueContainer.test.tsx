/**
 * Kontener `OrderMailQueue` (react-query + mutacje): które zapytania idą,
 * jak awaria i 403 przechodzą na ekran, dokument z `?doc=` spoza listy,
 * błędy zapisu i „Pobierz zamówienia z maila” z odpytywaniem stanu.
 * Warstwę prezentacyjną testuje `OrderMailQueueView.test.tsx`.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listQueue: vi.fn(),
  getItem: vi.fn(),
  apply: vi.fn(),
  dismiss: vi.fn(),
  refreshPlan: vi.fn(),
  syncStatus: vi.fn(),
  triggerSync: vi.fn(),
  recheckRuns: vi.fn(),
  search: new URLSearchParams(),
}));

vi.mock("@/lib/api/orderMail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/orderMail")>()),
  orderMailApi: {
    listQueue: mocks.listQueue,
    getItem: mocks.getItem,
    apply: mocks.apply,
    dismiss: mocks.dismiss,
    refreshPlan: mocks.refreshPlan,
    syncStatus: mocks.syncStatus,
    triggerSync: mocks.triggerSync,
    recheckRuns: mocks.recheckRuns,
    fileUrl: (id: number) => `/api/order-mail/queue/${id}/file`,
  },
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => mocks.search }));
vi.mock("@/lib/authenticated-files", () => ({ fetchAuthenticatedBlob: vi.fn(), openAuthenticatedFile: vi.fn() }));
vi.mock("@/components/finance/OrderPdfViewer", () => ({
  OrderPdfViewer: ({ file }: { file: { id: number } }) => <div data-testid="pdf-viewer">PDF {file.id}</div>,
}));
vi.mock("@/components/order-mail/OrderMailDetail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/order-mail/OrderMailDetail")>()),
  OrderMailDetail: (p: {
    doc: { id: number };
    onApply: (choices?: unknown) => void;
    onDismiss: () => void;
    onRefreshPlan?: () => void;
    busy: boolean;
    applyError: string | null;
    preview?: { open: boolean; onToggle: () => void };
  }) => (
    <div data-testid="order-mail-detail">
      <span>Szczegół #{p.doc.id}</span>
      <button type="button" onClick={() => p.onApply()} disabled={p.busy}>
        Zastosuj
      </button>
      <button type="button" onClick={() => p.onApply({ 0: { choice: "start_after" } })}>
        Zastosuj z wyborem
      </button>
      <button type="button" onClick={p.onDismiss}>
        Odrzuć
      </button>
      {p.onRefreshPlan ? (
        <button type="button" onClick={p.onRefreshPlan}>
          Przelicz plan
        </button>
      ) : null}
      {p.preview ? (
        <button type="button" onClick={p.preview.onToggle}>
          {p.preview.open ? "Ukryj podgląd" : "Pokaż podgląd"}
        </button>
      ) : null}
      {p.applyError ? <p role="alert">{p.applyError}</p> : null}
    </div>
  ),
}));

import { OrderMailQueue } from "@/components/order-mail/OrderMailQueue";
import type { OrderMailDocument, OrderMailOutcome, OrderMailSyncStatus } from "@/lib/api/orderMail";

function doc(over: Partial<OrderMailDocument> = {}): OrderMailDocument {
  return {
    id: 1,
    received_at: "2026-11-23T08:00:00Z",
    sender_email: "zamowienia@example.com",
    subject: "Zamówienie",
    attachment_name: "zamowienie.pdf",
    outcome: "needs_review",
    client_id: 1,
    client_name: "Firma Testowa sp. z o.o.",
    identification_method: "registry_id",
    identification_reason: null,
    client_policy: null,
    gate_verdict: "review",
    gate_reasons: [],
    document_meta: null,
    extraction: null,
    proposal: null,
    applied_order_id: null,
    applied_at: null,
    reviewed_at: null,
    error: null,
    can_apply: true,
    has_file: true,
    ...over,
  } as OrderMailDocument;
}

function syncStatus(over: Partial<OrderMailSyncStatus> = {}, finishedAt = "2026-11-24T07:00:00Z"): OrderMailSyncStatus {
  return {
    enabled: true,
    interval_minutes: 60,
    autoapply_enabled: false,
    running: false,
    started_at: "2026-11-24T06:59:00Z",
    interrupted: false,
    can_trigger: true,
    last_completed: {
      reason: "scheduled",
      started_at: "2026-11-24T06:59:00Z",
      finished_at: finishedAt,
      status: "ok",
      error: null,
      messages: 1,
      new_messages: 0,
      attachments: 0,
      auto_applied: 0,
      needs_review: 0,
      unrecognized: 0,
      duplicates: 0,
      skipped_existing: 0,
      ignored_no_pdf: 0,
      ignored_sender: 0,
      failed: 0,
      rechecked: 0,
      recheck_applied: 0,
      recheck_held: 0,
      recheck_alerts: 0,
      errors: [],
    },
    ...over,
  } as OrderMailSyncStatus;
}

const http = (status: number, detail?: unknown) => ({ isAxiosError: true, response: { status, data: detail === undefined ? {} : { detail } } });

function queue(byOutcome: Partial<Record<OrderMailOutcome, OrderMailDocument[]>>, counts: Partial<Record<OrderMailOutcome, number | Error>> = {}) {
  mocks.listQueue.mockImplementation(async ({ outcome, limit }: { outcome: OrderMailOutcome; limit: number }) => {
    if (limit === 1) {
      const count = counts[outcome] ?? (byOutcome[outcome]?.length ?? 0);
      if (count instanceof Error) throw count;
      return { data: { items: [], total: count } };
    }
    const items = byOutcome[outcome] ?? [];
    return { data: { items, total: items.length } };
  });
}

function renderQueue() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OrderMailQueue />
    </QueryClientProvider>,
  );
}

function tab(name: RegExp) {
  return screen.getByRole("tab", { name });
}

beforeEach(() => {
  for (const [key, fn] of Object.entries(mocks)) if (key !== "search") (fn as ReturnType<typeof vi.fn>).mockReset();
  mocks.search = new URLSearchParams();
  mocks.syncStatus.mockResolvedValue({ data: syncStatus() });
  mocks.recheckRuns.mockResolvedValue({ data: { items: [], scoped: false, last_checked_at: null, unchanged_runs: 0 } });
});

describe("OrderMailQueue — kolejka", () => {
  it("pyta o „Do weryfikacji” z limitem 100, a liczniki zakładek idą osobno z limitem 1", async () => {
    queue({ needs_review: [doc({ id: 1 }), doc({ id: 2, client_name: null, applied_order_id: 55 })] }, { failed: 3, auto_applied: new Error("500") });
    renderQueue();
    expect(await screen.findByText("Szczegół #1")).toBeInTheDocument();
    expect(mocks.listQueue).toHaveBeenCalledWith({ outcome: "needs_review", limit: 100 });
    for (const outcome of ["needs_review", "auto_applied", "applied", "unrecognized_client", "failed"]) {
      expect(mocks.listQueue).toHaveBeenCalledWith({ outcome, limit: 1 });
    }
    await waitFor(() => expect(tab(/Nieudane/)).toHaveTextContent("Nieudane3"));
    // Licznik, który się nie wczytał, nie udaje zera.
    expect(tab(/Zapisane automatycznie/)).toHaveTextContent(/^Zapisane automatycznie$/);
    expect(tab(/Do weryfikacji/)).toHaveTextContent("Do weryfikacji2");
    const list = screen.getByTestId("order-mail-list");
    expect(within(list).getByText("Nierozpoznany klient")).toBeInTheDocument();
    expect(within(list).getByText("Zamówienie #55")).toBeInTheDocument();
  });

  it("awaria listy to błąd z ponowieniem, nie pusta kolejka", async () => {
    mocks.listQueue.mockRejectedValue(http(500));
    const user = userEvent.setup();
    renderQueue();
    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent("Nie udało się pobrać kolejki.");
    expect(screen.queryByText("Nic do pokazania")).not.toBeInTheDocument();
    const calls = mocks.listQueue.mock.calls.filter(([p]) => p.limit === 100).length;
    await user.click(within(notice).getByRole("button"));
    await waitFor(() => expect(mocks.listQueue.mock.calls.filter(([p]) => p.limit === 100).length).toBe(calls + 1));
  });

  it("403 to brak dostępu bez zakładek, a nie awaria", async () => {
    mocks.listQueue.mockRejectedValue(http(403));
    renderQueue();
    expect(await screen.findByText(/Nie masz dostępu do kolejki zamówień z maila/)).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByText("Pobierz zamówienia z maila")).not.toBeInTheDocument();
  });

  it("pusta zakładka po udanym odczycie mówi, że nic nie czeka", async () => {
    queue({});
    renderQueue();
    expect(await screen.findByText("Nic do pokazania")).toBeInTheDocument();
    expect(screen.getByText(/Nic nie czeka na weryfikację — każde zamówienie z maila jest zapisane albo odrzucone/)).toBeInTheDocument();
  });

  it("zmiana zakładki pyta o nowy stan i zdejmuje wybór", async () => {
    queue({ needs_review: [doc({ id: 1 }), doc({ id: 2 })], failed: [doc({ id: 9, outcome: "failed" })] });
    const user = userEvent.setup();
    renderQueue();
    await screen.findByText("Szczegół #1");
    await user.click(screen.getAllByRole("button", { name: /Firma Testowa/ })[1]);
    expect(screen.getByText("Szczegół #2")).toBeInTheDocument();
    await user.click(tab(/Nieudane/));
    await waitFor(() => expect(mocks.listQueue).toHaveBeenCalledWith({ outcome: "failed", limit: 100 }));
    expect(await screen.findByText("Szczegół #9")).toBeInTheDocument();
    expect(within(screen.getByTestId("order-mail-list")).getByText("Nie udało się przetworzyć")).toBeInTheDocument();
  });
});

describe("OrderMailQueue — dokument z adresu (?doc=)", () => {
  it("dokument spoza listy doczytuje się po id i nie podstawia pierwszego z kolejki", async () => {
    mocks.search = new URLSearchParams("doc=77");
    queue({ needs_review: [doc({ id: 1 })] });
    mocks.getItem.mockResolvedValue({ data: doc({ id: 77, outcome: "applied" }) });
    renderQueue();
    expect(await screen.findByText("Szczegół #77")).toBeInTheDocument();
    expect(mocks.getItem).toHaveBeenCalledWith(77);
    expect(screen.queryByText("Szczegół #1")).not.toBeInTheDocument();
  });

  it("dokument, którego nie ma albo do którego nie ma dostępu, mówi to wprost", async () => {
    mocks.search = new URLSearchParams("doc=77");
    queue({ needs_review: [doc({ id: 1 })] });
    mocks.getItem.mockRejectedValue(http(404));
    renderQueue();
    expect(await screen.findByText(/Nie znaleziono dokumentu #77 albo nie masz do niego dostępu/)).toBeInTheDocument();
    expect(screen.queryByText("Szczegół #1")).not.toBeInTheDocument();
  });

  it("dokument z adresu, który jest na liście, nie idzie osobnym zapytaniem", async () => {
    mocks.search = new URLSearchParams("doc=2");
    queue({ needs_review: [doc({ id: 1 }), doc({ id: 2 })] });
    renderQueue();
    expect(await screen.findByText("Szczegół #2")).toBeInTheDocument();
    expect(mocks.getItem).not.toHaveBeenCalled();
  });
});

describe("OrderMailQueue — zapis, odrzucenie, przeliczenie", () => {
  it("„Zastosuj” woła apply z id i wyborem nakładania; błąd idzie z powodem z API", async () => {
    queue({ needs_review: [doc({ id: 4 })] });
    mocks.apply.mockResolvedValueOnce({ data: { ok: true } }).mockRejectedValueOnce(http(409, "Zamówienie 7/2026 już istnieje."));
    const user = userEvent.setup();
    renderQueue();
    await user.click(await screen.findByRole("button", { name: "Zastosuj" }));
    await waitFor(() => expect(mocks.apply).toHaveBeenCalledWith(4, undefined));
    await user.click(screen.getByRole("button", { name: "Zastosuj z wyborem" }));
    await waitFor(() => expect(mocks.apply).toHaveBeenLastCalledWith(4, { 0: { choice: "start_after" } }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Zamówienie 7/2026 już istnieje.");
  });

  it("błąd odrzucenia i przeliczenia planu ma własny komunikat", async () => {
    queue({ needs_review: [doc({ id: 4 })] });
    mocks.dismiss.mockRejectedValue(http(500));
    mocks.refreshPlan.mockRejectedValue(http(422, "PDF jest nieczytelny."));
    const user = userEvent.setup();
    renderQueue();
    await user.click(await screen.findByRole("button", { name: "Odrzuć" }));
    await waitFor(() => expect(mocks.dismiss).toHaveBeenCalledWith(4));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się odrzucić wpisu");
    await user.click(screen.getByRole("button", { name: "Przelicz plan" }));
    await waitFor(() => expect(mocks.refreshPlan).toHaveBeenCalledWith(4));
    // Błąd przeliczenia ma pierwszeństwo przed błędem odrzucenia.
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("PDF jest nieczytelny."));
  });

  it("udany zapis odświeża kolejkę", async () => {
    queue({ needs_review: [doc({ id: 4 })] });
    mocks.apply.mockResolvedValue({ data: { ok: true } });
    const user = userEvent.setup();
    renderQueue();
    const button = await screen.findByRole("button", { name: "Zastosuj" });
    await waitFor(() => expect(mocks.listQueue).toHaveBeenCalledTimes(6));
    await user.click(button);
    await waitFor(() => expect(mocks.listQueue.mock.calls.length).toBeGreaterThan(6));
  });

  it("podgląd PDF otwiera się przyciskiem w szczegółach", async () => {
    queue({ needs_review: [doc({ id: 4, has_file: true })] });
    const user = userEvent.setup();
    renderQueue();
    await user.click(await screen.findByRole("button", { name: "Pokaż podgląd" }));
    expect(await screen.findByTestId("pdf-viewer")).toHaveTextContent("PDF 4");
    await user.click(screen.getByRole("button", { name: "Ukryj podgląd" }));
    expect(screen.queryByTestId("pdf-viewer")).not.toBeInTheDocument();
  });
});

describe("OrderMailQueue — „Pobierz zamówienia z maila”", () => {
  it("po nowym wyniku biegu odświeża kolejkę i liczniki", async () => {
    queue({ needs_review: [doc({ id: 1 })] });
    mocks.syncStatus
      .mockResolvedValueOnce({ data: syncStatus() })
      .mockResolvedValue({ data: syncStatus({}, "2026-11-24T09:00:00Z") });
    mocks.triggerSync.mockResolvedValue({ data: { status: "started" } });
    const user = userEvent.setup();
    renderQueue();
    await screen.findByText("Szczegół #1");
    const button = await screen.findByRole("button", { name: /Pobierz zamówienia z maila/ });
    const before = mocks.listQueue.mock.calls.length;
    await user.click(button);
    await waitFor(() => expect(mocks.triggerSync).toHaveBeenCalled());
    await waitFor(() => expect(mocks.listQueue.mock.calls.length).toBeGreaterThan(before));
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("409 (bieg już trwa) dołącza do biegu bez komunikatu błędu", async () => {
    queue({ needs_review: [doc({ id: 1 })] });
    mocks.triggerSync.mockRejectedValue(http(409, "Sprawdzanie już trwa."));
    const user = userEvent.setup();
    renderQueue();
    const button = await screen.findByRole("button", { name: /Pobierz zamówienia z maila/ });
    const before = mocks.syncStatus.mock.calls.length;
    await user.click(button);
    await waitFor(() => expect(mocks.syncStatus.mock.calls.length).toBeGreaterThan(before));
    expect(screen.queryByText("Sprawdzanie już trwa.")).not.toBeInTheDocument();
  });

  it("inny błąd uruchomienia pokazuje powód z API albo ogólny komunikat", async () => {
    queue({ needs_review: [doc({ id: 1 })] });
    mocks.triggerSync.mockRejectedValueOnce(http(503, "Skrzynka jest wyłączona.")).mockRejectedValueOnce(http(500, { code: "x" }));
    const user = userEvent.setup();
    renderQueue();
    const button = await screen.findByRole("button", { name: /Pobierz zamówienia z maila/ });
    await user.click(button);
    expect(await screen.findByText("Skrzynka jest wyłączona.")).toBeInTheDocument();
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(await screen.findByText("Nie udało się uruchomić sprawdzenia skrzynki.")).toBeInTheDocument();
  });

  it("bieg przerwany po kliknięciu (restart) prosi o ponowne kliknięcie", async () => {
    queue({ needs_review: [doc({ id: 1 })] });
    mocks.syncStatus
      .mockResolvedValueOnce({ data: syncStatus() })
      .mockResolvedValue({ data: syncStatus({ interrupted: true, started_at: "2026-11-24T09:00:00Z" }) });
    mocks.triggerSync.mockResolvedValue({ data: { status: "started" } });
    const user = userEvent.setup();
    renderQueue();
    await user.click(await screen.findByRole("button", { name: /Pobierz zamówienia z maila/ }));
    expect(await screen.findByText("Sprawdzanie zostało przerwane (restart aplikacji). Kliknij ponownie.")).toBeInTheDocument();
  });

  it("bez prawa uruchomienia nie ma przycisku; wyłączone pobieranie blokuje go z wyjaśnieniem", async () => {
    queue({ needs_review: [doc({ id: 1 })] });
    mocks.syncStatus.mockResolvedValue({ data: syncStatus({ enabled: false }) });
    renderQueue();
    const button = await screen.findByRole("button", { name: /Pobierz zamówienia z maila/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Pobieranie zamówień z maila jest wyłączone");
  });
});
