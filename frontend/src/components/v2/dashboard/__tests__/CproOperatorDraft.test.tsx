import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const download = vi.fn();
const downloadBlob = vi.fn();
const copy = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...args: unknown[]) => get(...args), post: (...args: unknown[]) => post(...args) } }));
vi.mock("@/lib/authenticated-files", () => ({ fetchAuthenticatedDownload: (...args: unknown[]) => download(...args), downloadBlob: (...args: unknown[]) => downloadBlob(...args) }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: (...args: unknown[]) => copy(...args) }));

import { CproOperatorDraft } from "../CproOperatorDraft";
import type { CproOperatorDraft as Draft, CproOperatorRun } from "@/lib/api/boardTasks";

const savedRun = (overrides: Partial<CproOperatorRun> = {}): CproOperatorRun => ({
  run_id: 3, stage_id: 1, delivery_lead_id: 27, request_number: "12345", status: "started", allow_create: true,
  candidate: { first_name: "Demo", last_name: "Tester", citizenship: "Polish", profile_title: "Engineer", profile_description: "Synthetic profile" },
  offer: { rate: "160", currency: "PLN", available_from: "2026-12-01", physical_location: "Synthetic location", former_employee: false, former_consultant: true, motivation: "Synthetic motivation", cv_file_name: "Demo.pdf", cv_format: "pdf", cv_version: 2 },
  ...overrides,
});

function renderPanel(draft: Draft = { delivery_lead_id: 27, request_number: "12345", run_id: null, state: "ready" }) {
  const active = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <CproOperatorDraft stageId={1} draft={draft} onActiveChange={active} />
  </QueryClientProvider>);
  return active;
}

async function start() {
  await userEvent.click(screen.getByRole("button", { name: "Przygotuj jeden szkic" }));
  await userEvent.click(screen.getByRole("button", { name: "Potwierdzam konto i request — otwórz zlecenie" }));
  await screen.findByText("Demo");
}

describe("CproOperatorDraft — jeden zapisany szkic, bez tokenów i ruchu etapu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    post.mockResolvedValue({ data: { run_id: 3, created: true } });
    get.mockResolvedValue({ data: savedRun() });
    download.mockResolvedValue({ blob: new Blob(["%PDF-demo"], { type: "application/pdf" }), filename: "Demo.pdf" });
    copy.mockResolvedValue(true);
  });

  it("wymaga jawnego potwierdzenia konta/requestu; pokazuje dokładne pola i kopiuje tylko wybrane", async () => {
    const active = renderPanel();
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByText(/konto Cpro: Marcin · request 12345/)).toBeInTheDocument();
    await start();
    expect(active).toHaveBeenCalledWith(true);
    expect(post).toHaveBeenCalledExactlyOnceWith("/api/board-tasks/cpro/operator/stages/1/draft", { delivery_lead_id: 27, request_number: "12345" });
    expect(get).toHaveBeenCalledWith("/api/board-tasks/cpro/operator/runs/3");
    await userEvent.click(screen.getByRole("button", { name: "Kopiuj Motivation" }));
    expect(copy).toHaveBeenCalledWith("Synthetic motivation");
    expect(screen.queryByRole("button", { name: /Wrzucone|Submit|Send/ })).not.toBeInTheDocument();
  });

  it("request DL32 pokazuje konto Marcina, ale rezerwacja i wznowienie zachowują prawdziwy DL32", async () => {
    get.mockResolvedValue({ data: savedRun({ delivery_lead_id: 32, cpro_account_name: "Marcin" }) });
    renderPanel({ delivery_lead_id: 32, cpro_account_name: "Marcin", request_number: "12345", run_id: null, state: "ready" });
    expect(screen.getByText(/konto Cpro: Marcin · request 12345/)).toBeInTheDocument();
    await start();
    expect(post).toHaveBeenCalledExactlyOnceWith("/api/board-tasks/cpro/operator/stages/1/draft", { delivery_lead_id: 32, request_number: "12345" });
    await userEvent.click(screen.getByRole("button", { name: "Zamknij panel szkicu" }));
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    await screen.findByText("Demo");
    expect(screen.getByText(/Najpierw sprawdź konto Marcin i request 12345/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(2);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it.each([
    { delivery_lead_id: 27, cpro_account_name: "Marcin" as const },
    { delivery_lead_id: 32, cpro_account_name: "Igor" as const },
    { delivery_lead_id: 32, cpro_account_name: undefined },
  ])("wznowienie requestu DL32 odrzuca innego właściciela lub niespójne konto: %j", async (overrides) => {
    get.mockResolvedValue({ data: savedRun(overrides) });
    renderPanel({ delivery_lead_id: 32, cpro_account_name: "Marcin", request_number: "12345", run_id: 3, state: "started" });
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Zlecenie nie pasuje");
    expect(screen.queryByRole("button", { name: "Pobierz firmowy PDF" })).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it.each([
    { delivery_lead_id: 32 },
    { delivery_lead_id: 27, cpro_account_name: "Nieznane" as never },
    { delivery_lead_id: 14, cpro_account_name: null },
  ])("brak mapowania nowego DL lub jawna błędna nazwa nie pozwalają na claim: %j", async (routing) => {
    renderPanel({ ...routing, request_number: "12345", run_id: null, state: "ready" });
    expect(screen.getByText(/konto Cpro: nieznane — przerwij/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj jeden szkic" }));
    expect(screen.getByRole("button", { name: "Potwierdzam konto i request — otwórz zlecenie" })).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("po PDF i ponownym otwarciu oferty potwierdza tylko ID oraz DRAFT/PDF", async () => {
    renderPanel();
    await start();
    const confirm = screen.getByRole("button", { name: "Potwierdź zapisany szkic DRAFT i PDF" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "ID istniejącej oferty w Cpro" }), "8844");
    await userEvent.click(screen.getByRole("checkbox", { name: /Ponownie otworzyłem/ }));
    expect(screen.getByRole("checkbox", { name: /Otworzyłem PDF/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Pobierz firmowy PDF" }));
    expect(download).toHaveBeenCalledWith("/api/board-tasks/cpro/operator/runs/3/cv");
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "Demo.pdf");
    await userEvent.click(screen.getByRole("checkbox", { name: /Otworzyłem PDF/ }));
    await userEvent.click(confirm);
    expect(post).toHaveBeenLastCalledWith("/api/board-tasks/cpro/operator/runs/3/confirm", { offer_id: "8844", confirmed_draft: true, confirmed_pdf: true });
    expect(await screen.findByText(/Potwierdzony szkic DRAFT · ID oferty 8844/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Potwierdź zapisany szkic DRAFT i PDF" })).not.toBeInTheDocument();
  });

  it("wznowienie i kolejne otwarcie używa wyłącznie GET, nigdy kolejnego tworzenia", async () => {
    renderPanel({ delivery_lead_id: 27, request_number: "12345", run_id: 3, state: "started" });
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    await screen.findByText("Demo");
    expect(screen.getByText(/Wznawiasz zapisane zlecenie/)).toHaveTextContent("nie twórz nowej oferty");
    await userEvent.click(screen.getByRole("button", { name: "Zamknij panel szkicu" }));
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(post).not.toHaveBeenCalled();
  });

  it.each([
    { created: false, allow_create: true },
    { created: true, allow_create: false },
  ])("nie pozwala tworzyć bez obu zgód serwera: %j", async ({ created, allow_create }) => {
    post.mockResolvedValue({ data: { run_id: 3, created } });
    get.mockResolvedValue({ data: savedRun({ allow_create }) });
    renderPanel();
    await start();
    expect(screen.getByText(/Wznawiasz zapisane zlecenie/)).toHaveTextContent("nie twórz nowej oferty");
    expect(screen.queryByText(/To nowe zlecenie w tej sesji/)).not.toBeInTheDocument();
  });

  it("po zamknięciu świeżego panelu nie zachowuje prawa pierwszego tworzenia", async () => {
    renderPanel();
    await start();
    expect(screen.getByText(/To nowe zlecenie w tej sesji/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "ID istniejącej oferty w Cpro" }), "8844");
    await userEvent.click(screen.getByRole("checkbox", { name: /Ponownie otworzyłem/ }));
    await userEvent.click(screen.getByRole("button", { name: "Zamknij panel szkicu" }));
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    await screen.findByText("Demo");
    expect(screen.getByText(/Wznawiasz zapisane zlecenie/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "ID istniejącej oferty w Cpro" })).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: /Ponownie otworzyłem/ })).not.toBeChecked();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("odtwarza przerwany szkic przez potwierdzenie istniejącej oferty, bez nowego PDF ani tworzenia", async () => {
    get.mockResolvedValue({ data: savedRun({ status: "expired", allow_create: false }) });
    renderPanel({ delivery_lead_id: 27, request_number: "12345", run_id: 3, state: "started" });
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    await screen.findByText("Demo");
    await userEvent.type(screen.getByRole("textbox", { name: "ID istniejącej oferty w Cpro" }), "8844");
    await userEvent.click(screen.getByRole("checkbox", { name: /Ponownie otworzyłem/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Otworzyłem PDF/ }));
    await userEvent.click(screen.getByRole("button", { name: "Potwierdź zapisany szkic DRAFT i PDF" }));
    expect(post).toHaveBeenCalledExactlyOnceWith("/api/board-tasks/cpro/operator/runs/3/confirm", { offer_id: "8844", confirmed_draft: true, confirmed_pdf: true });
    expect(download).not.toHaveBeenCalled();
  });

  it("zamyka porzuconą rezerwację tylko po zgodzie serwera i osobistej deklaracji braku oferty", async () => {
    get.mockResolvedValue({ data: savedRun({ status: "expired", allow_create: false, allow_close_absent: true }) });
    renderPanel({ delivery_lead_id: 27, request_number: "12345", run_id: 3, state: "started" });
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    await screen.findByText("Demo");
    const close = screen.getByRole("button", { name: "Zamknij porzucone zlecenie — brak oferty" });
    expect(close).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Osobiście sprawdziłem Our offers na koncie Marcin/ }));
    await userEvent.click(close);
    expect(post).toHaveBeenCalledExactlyOnceWith("/api/board-tasks/cpro/operator/runs/3/close-absent", { confirmed_absent: true });
    expect(await screen.findByText(/Zamknięto porzucone zlecenie/)).toHaveTextContent("Niczego nie uruchomiono");
  });

  it.each([
    { status: "expired", allow_close_absent: false },
    { status: "received", allow_close_absent: true },
  ])("nie proponuje zwolnienia bez zgody serwera ani dla otrzymanego DRAFT: %j", async (overrides) => {
    get.mockResolvedValue({ data: savedRun(overrides) });
    renderPanel({ delivery_lead_id: 27, request_number: "12345", run_id: 3, state: "started" });
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    await screen.findByText("Demo");
    expect(screen.queryByRole("button", { name: "Zamknij porzucone zlecenie — brak oferty" })).not.toBeInTheDocument();
  });

  it("po otrzymanym potwierdzeniu pokazuje ocenę Sandry bez tworzenia i ponownego potwierdzenia", async () => {
    get.mockResolvedValue({ data: savedRun({ status: "received", offer_id: "8844" }) });
    renderPanel({ delivery_lead_id: 27, request_number: "12345", run_id: 3, state: "received" });
    await userEvent.click(screen.getByRole("button", { name: "Potwierdzony szkic" }));
    await screen.findByText("Demo");
    expect(screen.getByText(/Potwierdzony szkic DRAFT · ID oferty 8844/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Potwierdź zapisany szkic DRAFT i PDF" })).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it.each([
    { stage_id: 2 }, { delivery_lead_id: 14 }, { request_number: "98765" },
    { offer: { ...savedRun().offer, cv_format: "docx" } },
  ])("odmawia snapshotu innej karty/konta/requestu lub DOCX: %j", async (overrides) => {
    get.mockResolvedValue({ data: savedRun(overrides) });
    renderPanel({ delivery_lead_id: 27, request_number: "12345", run_id: 3, state: "started" });
    await userEvent.click(screen.getByRole("button", { name: "Wznów zapisane zlecenie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Zlecenie nie pasuje");
    expect(screen.queryByRole("button", { name: "Pobierz firmowy PDF" })).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("nie pobiera ani nie zatwierdza DOCX podszywającego się pod PDF", async () => {
    download.mockResolvedValue({ blob: new Blob(["docx"], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }), filename: "Demo.docx" });
    renderPanel();
    await start();
    await userEvent.click(screen.getByRole("button", { name: "Pobierz firmowy PDF" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać firmowego PDF");
    expect(downloadBlob).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox", { name: /Otworzyłem PDF/ })).toBeDisabled();
  });

  it("nie ponawia POST po niejednoznacznym błędzie utworzenia", async () => {
    post.mockRejectedValue(new Error("network"));
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj jeden szkic" }));
    const create = screen.getByRole("button", { name: "Potwierdzam konto i request — otwórz zlecenie" });
    await userEvent.click(create);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(create).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Zamknij panel szkicu" }));
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj jeden szkic" }));
    expect(screen.getByRole("button", { name: "Potwierdzam konto i request — otwórz zlecenie" })).toBeDisabled();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("dwa kliknięcia podczas tworzenia wysyłają jedno żądanie", async () => {
    post.mockReturnValue(new Promise(() => {}));
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Przygotuj jeden szkic" }));
    const create = screen.getByRole("button", { name: "Potwierdzam konto i request — otwórz zlecenie" });
    fireEvent.click(create);
    fireEvent.click(create);
    expect(post).toHaveBeenCalledTimes(1);
  });
});
