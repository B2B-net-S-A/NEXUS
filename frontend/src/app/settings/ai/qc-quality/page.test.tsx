import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * „Jakość QC” (D6, 13.10.2026): trafność sprawdzeń QC CV i ich stan. Test
 * pilnuje liczb z serwera, podświetlenia niskiej trafności, tego, że blokady
 * nie mają wyboru stanu (serwer i tak odmawia), i że awaria nie wygląda jak
 * pusta tabela.
 */

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: mocks.get, patch: mocks.patch },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

import QcQualityPage from "./page";
import type { QcQualityReport } from "@/lib/api/qcQuality";
import { formatDate } from "@/lib/utils";

const REPORT: QcQualityReport = {
  window_days: 30,
  auto_min_shown: 30,
  auto_info_below: 0.7,
  alert_blocking_below: 0.9,
  checks: [
    {
      key: "no_unsupported",
      label: "CV nie twierdzi niczego spoza oryginału",
      blocking: true,
      shown: 40,
      dismissed_wrong: 6,
      precision: 0.85,
      reasons: { other_name: 5, in_cv: 1, not_needed: 0 },
      state: "active",
      auto: null,
      manual: null,
    },
    {
      key: "must_bolded",
      label: "Must-have są pogrubione",
      blocking: false,
      shown: 50,
      dismissed_wrong: 20,
      precision: 0.6,
      reasons: { in_cv: 20 },
      state: "info",
      auto: "info",
      manual: null,
    },
    {
      key: "spelling",
      label: "Pisownia technologii",
      blocking: false,
      shown: 0,
      dismissed_wrong: 0,
      precision: null,
      reasons: {},
      state: "off",
      auto: null,
      manual: "off",
    },
  ],
  recent: [
    {
      id: 7,
      check_key: "no_unsupported",
      check_label: "CV nie twierdzi niczego spoza oryginału",
      label: "Docker",
      reason: "other_name",
      reason_label: "Jest w źródłach pod inną nazwą",
      note: "W oryginale jako Podman",
      by_name: "Marta Przykładowa",
      at: "2026-10-13T08:30:00Z",
      restored: true,
      job_id: 31,
      candidate_id: 21,
    },
  ],
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <QcQualityPage />
    </QueryClientProvider>,
  );
}

const row = (label: string) => screen.getByRole("rowheader", { name: new RegExp(label) }).closest("tr")!;

describe("Ustawienia → Jakość QC", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ data: REPORT });
  });

  it("mówi regułę jednym zdaniem i pokazuje liczby z serwera", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Jakość QC" })).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/settings/ai/qc-quality");
    expect(screen.getByText(/w ostatnich 30 dniach/)).toHaveTextContent(
      "Uwaga z trafnością poniżej 70% przy co najmniej 30 pokazanych sama staje się informacją",
    );
    expect(screen.getByText(/w ostatnich 30 dniach/)).toHaveTextContent("blokady nigdy nie przechodzą same — poniżej 90%");

    const blocking = row("CV nie twierdzi niczego spoza oryginału");
    expect(blocking).toHaveTextContent("Blokada");
    expect(blocking).toHaveTextContent("40");
    expect(blocking).toHaveTextContent("Jest w źródłach pod inną nazwą: 5");
    expect(blocking).toHaveTextContent("Jest w CV — QC tego nie znalazło: 1");
    // Powód z zerem nie zaśmieca wiersza.
    expect(blocking).not.toHaveTextContent("Nie dotyczy tej rekrutacji");
    // Blokada poniżej 90% — wyróżniona; nie ma wyboru stanu.
    expect(within(blocking).getByText("85%").className).toMatch(/destructive/);
    expect(within(blocking).queryByRole("combobox")).toBeNull();
    expect(blocking).toHaveTextContent("Zawsze aktywna");

    const muted = row("Must-have są pogrubione");
    expect(muted).toHaveTextContent("Uwaga");
    expect(within(muted).getByText("60%").className).toMatch(/warning/);
    expect(within(muted).getByRole("combobox", { name: "Stan: Must-have są pogrubione" })).toHaveValue("auto");
    expect(muted).toHaveTextContent("Automat (informacja)");
    expect(muted).toHaveTextContent("Teraz: informacja (automat)");

    const off = row("Pisownia technologii");
    expect(within(off).getByText("—")).toBeInTheDocument();
    expect(within(off).getByRole("combobox")).toHaveValue("off");
  });

  it("zmiana stanu uwagi woła PATCH; „Automat” wysyła `null`", async () => {
    mocks.patch.mockResolvedValue({ data: REPORT });
    renderPage();
    await screen.findByRole("heading", { name: "Jakość QC" });
    await userEvent.selectOptions(
      within(row("Must-have są pogrubione")).getByRole("combobox"),
      "active",
    );
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/settings/ai/qc-quality/must_bolded", { state: "active" }),
    );
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalledWith("Zapisano stan: Must-have są pogrubione."));
    await userEvent.selectOptions(within(row("Pisownia technologii")).getByRole("combobox"), "auto");
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/settings/ai/qc-quality/spelling", { state: null }),
    );
  });

  it("odmowa zapisu — słowa serwera w komunikacie", async () => {
    mocks.patch.mockRejectedValue({ response: { status: 422, data: { detail: "Blokad nie da się wyciszyć." } } });
    renderPage();
    await screen.findByRole("heading", { name: "Jakość QC" });
    await userEvent.selectOptions(within(row("Must-have są pogrubione")).getByRole("combobox"), "off");
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Blokad nie da się wyciszyć."));
  });

  it("ostatnie pominięcia: co, dlaczego, kto, kiedy i link do osoby w rekrutacji", async () => {
    renderPage();
    const link = await screen.findByRole("link", { name: /Otwórz kandydata w rekrutacji/ });
    expect(link).toHaveAttribute("href", "/jobs/31?candidate=21");
    const item = link.closest("li")!;
    expect(item).toHaveTextContent("Docker");
    expect(item).toHaveTextContent("Jest w źródłach pod inną nazwą — „W oryginale jako Podman”");
    expect(item).toHaveTextContent(`Marta Przykładowa, ${formatDate("2026-10-13T08:30:00Z")}`);
    expect(item).toHaveTextContent("przywrócone");
  });

  it("bez pominięć mówi to wprost — dopiero po udanym odczycie", async () => {
    mocks.get.mockResolvedValue({ data: { ...REPORT, recent: [] } });
    renderPage();
    expect(await screen.findByText("Nikt jeszcze nie oznaczył uwagi QC jako nieprawdy.")).toBeInTheDocument();
  });

  it("403 to brak uprawnień, nie pusty raport", async () => {
    mocks.get.mockRejectedValue({ response: { status: 403, data: { detail: "Forbidden" } } });
    renderPage();
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("Nikt jeszcze nie oznaczył uwagi QC jako nieprawdy.")).toBeNull();
  });

  it("awaria odczytu — komunikat i „Ponów”, nie pusta tabela", async () => {
    mocks.get.mockRejectedValueOnce({ response: { status: 500 } }).mockResolvedValueOnce({ data: REPORT });
    renderPage();
    expect(await screen.findByText("Nie udało się policzyć trafności QC.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
