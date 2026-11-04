/**
 * Ustawienia → Kadry → „Dokumenty po terminie przechowywania” (E4). Nic nie
 * znika bez zaznaczenia i potwierdzenia; anulowane potwierdzenie nie wysyła
 * niczego. Okresy: tylko zmienione, pełne lata 1–50. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: mocks.put } }));

import { retentionDue, retentionEmpty } from "@/app/preview/hr-documents/fixtures";
import { ToastProvider } from "@/components/Toast";
import { documentKeys, type RetentionDue } from "@/lib/api/hr-documents";

import { DocumentsRetentionCard, retentionChanges } from "../DocumentsRetentionCard";

vi.setConfig({ testTimeout: 20_000 });

function wrap(data?: RetentionDue) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  if (data) client.setQueryData(documentKeys.retention, data);
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <DocumentsRetentionCard />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

describe("DocumentsRetentionCard", () => {
  it("pusta lista mówi, że nic nie czeka", () => {
    wrap(retentionEmpty());
    expect(screen.getByText("Nic nie czeka na usunięcie.")).toBeInTheDocument();
  });

  it("awaria to błąd, nie „nic nie czeka”", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 500 } }));
    wrap();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Wczytywanie…")).toBeNull());
    expect(screen.queryByText("Nic nie czeka na usunięcie.")).toBeNull();
  });

  it("usuwa dopiero po zaznaczeniu i potwierdzeniu; anulowanie nic nie wysyła", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: { deleted: [6101], skipped: [] } });
    wrap(retentionDue());
    const remove = screen.getByRole("button", { name: /Usuń zaznaczone/ });
    expect(remove).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: "Zaznacz: Notatka z rozmowy końcowej" }));
    await user.click(screen.getByRole("button", { name: "Usuń zaznaczone (1)" }));
    let dialog = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    await user.click(within(dialog).getByRole("button", { name: /Anuluj/ }));
    expect(mocks.post).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Usuń zaznaczone (1)" }));
    dialog = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    await user.click(within(dialog).getByRole("button", { name: "Usuń" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/documents/retention/delete", {
        document_ids: [6101],
        confirm: true,
      }),
    );
  });

  it("okresy: wysyła tylko zmienione, odrzuca spoza 10–50 lat", () => {
    const { retention } = retentionDue();
    expect(retentionChanges(retention, { other: "5", contract: "12" })).toEqual({
      years: { contract: 12 },
      error: null,
    });
    expect(retentionChanges(retention, { other: "0" }).error).toMatch(/od 10 do 50/);
    // Co najmniej 10 lat (decyzja Artura 19.10.2026).
    expect(retentionChanges(retention, { contract: "9" }).error).toMatch(/od 10 do 50/);
    expect(retentionChanges(retention, { other: "10" })).toEqual({ years: { other: 10 }, error: null });
    expect(retentionChanges(retention, { other: "2,5" }).error).toMatch(/pełne lata/);
  });
});
