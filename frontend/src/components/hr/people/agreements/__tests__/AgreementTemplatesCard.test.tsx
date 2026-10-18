/**
 * Ustawienia → Kadry → „Wzory umów” (E5): wersje wzorów, wycofanie po
 * potwierdzeniu, przełącznik modułu tylko dla administratora, wyłączony moduł
 * mówi zdaniem zamiast błędu, plik spoza .docx nie wychodzi do serwera.
 * Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, patch: mocks.patch, put: mocks.put },
}));

import { SETTINGS, TEMPLATES } from "@/app/preview/hr-agreements/fixtures";
import { ToastProvider } from "@/components/Toast";
import { agreementKeys } from "@/lib/api/hr-agreements";

import { AgreementTemplatesCard, templateFileProblem } from "../AgreementTemplatesCard";

vi.setConfig({ testTimeout: 20_000 });

function wrap(isAdmin: boolean, seed = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  if (seed) {
    client.setQueryData(agreementKeys.templates(false), TEMPLATES);
    client.setQueryData(agreementKeys.settings, SETTINGS);
  }
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AgreementTemplatesCard isAdmin={isAdmin} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

describe("AgreementTemplatesCard", () => {
  it("wersja i liczba umów przy wzorze, przełącznik tylko u admina", () => {
    wrap(false);
    const row = screen.getByText("Zlecenie — recepcja").closest("tr") as HTMLElement;
    expect(within(row).getByText("wersja 3")).toBeTruthy();
    expect(within(row).getByText(/umowy: 7/)).toBeTruthy();
    expect(screen.getByText("wycofany")).toBeTruthy();
    expect(screen.queryByRole("switch", { name: "Umowy z ludźmi włączone" })).toBeNull();
    expect(screen.getByText(/Moduł włącza administrator/)).toBeTruthy();
  });

  it("admin przełącza moduł", async () => {
    const user = userEvent.setup();
    mocks.put.mockResolvedValue({ data: { enabled: false, autenti_configured: true } });
    wrap(true);
    await user.click(screen.getByRole("switch", { name: "Umowy z ludźmi włączone" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/hr/agreements/settings", { enabled: false }),
    );
  });

  it("wycofanie wzoru dopiero po potwierdzeniu", async () => {
    const user = userEvent.setup();
    mocks.patch.mockResolvedValue({ data: {} });
    wrap(false);
    const row = screen.getByText("B2B biura").closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Wycofaj" }));
    expect(mocks.patch).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Wycofaj" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/hr/agreements/templates/32", { is_active: false }),
    );
  });

  it("wyłączony moduł (404) mówi zdaniem, nie błędem", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 404 } }));
    wrap(false, false);
    expect(await screen.findByText(/Moduł umów jest wyłączony/)).toBeTruthy();
  });

  it("plik spoza .docx i za duży nie wychodzi do serwera", () => {
    const max = 2 * 1024 * 1024;
    expect(templateFileProblem(null, max)).toContain("Wybierz plik");
    expect(templateFileProblem(new File(["x"], "wzor.pdf"), max)).toContain(".docx");
    expect(templateFileProblem(new File([""], "wzor.docx"), max)).toContain("pusty");
    expect(templateFileProblem(new File(["x"], "wzor.docx"), max)).toBeNull();
  });
});
