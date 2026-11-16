import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

import { DocumentsTab, formatCapital } from "@/components/rada/DocumentsTab";
import { ToastProvider } from "@/components/Toast";
import { useAuthStore } from "@/store/auth";

const documents = {
  categories: [
    { key: "resolution_general", total: 1, without_file: 1 },
    { key: "statute", total: 0, without_file: 0 },
  ],
  items: [
    {
      id: 7,
      category: "resolution_general",
      organ: "general",
      number: null,
      title: "Uchwała WZA — zatwierdzenie sprawozdania finansowego za 2099",
      subject: null,
      doc_date: null,
      source: "krs",
      krs_entry_no: 51,
      krs_entry_date: "2099-04-22",
      has_file: false,
      file_name: null,
      file_size: null,
      extraction_status: "none",
      extraction: {},
      updated_at: null,
    },
  ],
};

function respond({ failDocuments = false } = {}) {
  get.mockImplementation((url?: string) => {
    if (String(url ?? "").endsWith("/krs")) return Promise.resolve({ data: { snapshot: null } });
    if (failDocuments && String(url ?? "").includes("/documents")) return Promise.reject(Object.assign(new Error("500"), { response: { status: 500 } }));
    return Promise.resolve({ data: documents });
  });
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <DocumentsTab />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function signIn(role: string) {
  useAuthStore.setState({ user: { id: 5, role, roles: [role] }, realUser: null, hydrated: true } as never);
}

beforeEach(() => get.mockReset());
afterEach(() => useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never));

describe("Rada → Dokumenty", () => {
  it("Rada widzi rejestr z wierszem z KRS, ale bez przycisków zapisu", async () => {
    respond();
    signIn("board");
    renderTab();
    expect(await screen.findByText(/zatwierdzenie sprawozdania finansowego za 2099/)).toBeInTheDocument();
    expect(screen.getByText("wpis 51")).toBeInTheDocument();
    expect(screen.getByText("brak skanu")).toBeInTheDocument();
    expect(screen.getByLabelText("1 bez skanu")).toBeInTheDocument();
    expect(screen.getByText("22.04.2099 (KRS)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj dokument/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dołącz skan" })).toBeNull();
    expect(screen.getByText(/Odpisu KRS jeszcze nie pobrano/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pobierz teraz/ })).toBeNull();
  });

  it("admin dołącza skan, ale wiersza z KRS nie usuwa", async () => {
    respond();
    signIn("admin");
    renderTab();
    await screen.findByText(/zatwierdzenie sprawozdania finansowego za 2099/);
    expect(screen.getByRole("button", { name: /Dodaj dokument/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dołącz skan" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usuń" })).toBeNull();
    expect(screen.getByRole("button", { name: /Pobierz teraz/ })).toBeInTheDocument();
  });

  it("awaria listy to komunikat błędu, nie pusty rejestr", async () => {
    respond({ failDocuments: true });
    signIn("board");
    renderTab();
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Zarząd nie dodał jeszcze/)).toBeNull();
  });

  it("kapitał z KRS w polskim zapisie", () => {
    const plain = (v: string) => v.replace(/\s/g, " ");
    expect(plain(formatCapital("1360000,00 PLN"))).toBe("1 360 000,00 zł");
    expect(plain(formatCapital("50000,00 EUR"))).toBe("50 000,00 EUR");
    expect(formatCapital(null)).toBe("—");
  });
});
