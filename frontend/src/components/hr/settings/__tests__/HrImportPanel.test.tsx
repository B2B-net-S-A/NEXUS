import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { HrImportHistory } from "@/components/hr/settings/HrImportHistory";
import { HrImportPanel } from "@/components/hr/settings/HrImportPanel";
import type { HrImportModuleReport, HrImportUpload } from "@/lib/api/hr-import";

const SHA = "a1b2c3d4e5f6".padEnd(64, "0");

function module(overrides: Partial<HrImportModuleReport>): HrImportModuleReport {
  return {
    module: "profiles",
    label: "Kartoteki i pule urlopowe",
    total: 0,
    counts: { create: 0, update: 0, unchanged: 0, conflict: 0, skip: 0 },
    reasons: {},
    extra: {},
    attention_total: 0,
    error: null,
    applied: null,
    attention: [],
    ...overrides,
  };
}

const DRY: HrImportUpload = {
  id: 12,
  status: "dry_run",
  bundle_sha256: SHA,
  size_bytes: 2048,
  exported_at: "2026-11-13T18:00:00+01:00",
  created_at: "2026-11-13T18:10:00+01:00",
  created_by_name: "Anna Przykładowa",
  expires_at: "2026-11-14T18:10:00+01:00",
  applied_at: null,
  applied_by_name: null,
  applied_modules: [],
  modules: [
    module({
      total: 4,
      counts: { create: 2, update: 1, unchanged: 0, conflict: 0, skip: 1 },
      reasons: { "brak konta w NEXUSIE": 1 },
      attention_total: 1,
      attention: [
        {
          source_id: "profiles:0000-aaaa",
          action: "skip",
          reason: "brak konta w NEXUSIE",
          email: "jan.przykladowy@example.com",
        },
      ],
    }),
    module({
      module: "leave",
      label: "Wnioski urlopowe i dni nieobecności",
      total: 3,
      counts: { create: 3, update: 0, unchanged: 0, conflict: 0, skip: 0 },
    }),
    module({ module: "care", label: "Mapa technologiczna i rozmowy opiekunów" }),
  ],
};

const APPLIED: HrImportUpload = {
  ...DRY,
  status: "applied",
  applied_at: "2026-11-13T18:20:00+01:00",
  applied_by_name: "Anna Przykładowa",
  applied_modules: ["profiles", "leave"],
  modules: DRY.modules.map((m) =>
    m.module === "care"
      ? m
      : { ...m, attention: undefined, applied: { total: m.total, counts: m.counts, written: {} } },
  ),
};

function renderPanel(isAdmin = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <HrImportPanel isAdmin={isAdmin} />
    </QueryClientProvider>,
  );
}

async function checkOnDryRun() {
  const file = new File(['{"format":"compass-bundle"}'], "paczka.json", {
    type: "application/json",
  });
  await userEvent.upload(screen.getByLabelText("Wybierz plik paczki"), file);
  expect(screen.getByText("paczka.json")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Sprawdź na sucho" }));
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
});

describe("HrImportPanel", () => {
  it("checks on dry run, saves only after confirmation and shows the result", async () => {
    post.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("/dry-run") ? DRY : APPLIED }),
    );
    renderPanel();
    await checkOnDryRun();

    const [dryUrl, body, config] = post.mock.calls[0];
    expect(dryUrl).toBe("/api/hr/admin/import/dry-run");
    expect(body).toBeInstanceOf(FormData);
    expect(config.headers["Content-Type"]).toBe("multipart/form-data");

    const row = (await screen.findByText("Kartoteki i pule urlopowe")).closest("tr")!;
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "",
      "Kartoteki i pule urlopowe",
      "2",
      "1",
      "0",
      "0",
      "1",
    ]);
    // Moduł bez zmian nie jest zaznaczony na start.
    expect(
      screen.getByRole("checkbox", { name: "Zapisz: Mapa technologiczna i rozmowy opiekunów" }),
    ).toHaveAttribute("data-state", "unchecked");

    // Lista do wyjaśnienia jest zwinięta.
    const toggle = screen.getByRole("button", { name: /Do wyjaśnienia i konflikty \(1\)/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByText("profiles:0000-aaaa")).toBeInTheDocument();
    expect(screen.getByText("jan.przykladowy@example.com")).toBeInTheDocument();

    // Zapis bez potwierdzenia nie idzie do serwera.
    await userEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Zmieni się 6 pozycji: nowe 5, zmienione 1");
    await userEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(post).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Zapisz" }),
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/hr/admin/import/12/apply",
        { bundle_sha256: SHA, modules: ["profiles", "leave"] },
        expect.objectContaining({ timeout: expect.any(Number) }),
      ),
    );
    expect(await screen.findByText("Wynik zapisu")).toBeInTheDocument();
    expect(showToast).toHaveBeenCalledWith("Paczka zapisana", "success");
    expect(screen.queryByRole("button", { name: "Zapisz" })).not.toBeInTheDocument();
    expect(screen.queryByText("Mapa technologiczna i rozmowy opiekunów")).not.toBeInTheDocument();
  });

  it("does not offer saving to HR without admin and shows server errors", async () => {
    post.mockResolvedValueOnce({ data: DRY });
    renderPanel(false);
    await checkOnDryRun();
    expect(await screen.findByText(/Zapis robi administrator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    post.mockRejectedValueOnce({
      response: { status: 422, data: { detail: "To nie jest paczka eksportu Compassa." } },
    });
    await checkOnDryRun();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "To nie jest paczka eksportu Compassa.",
    );
  });
});

describe("HrImportHistory", () => {
  it("lists batches with status and sums, and a failed read is not an empty list", async () => {
    get.mockResolvedValueOnce({ data: [APPLIED] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = render(
      <QueryClientProvider client={client}>
        <HrImportHistory />
      </QueryClientProvider>,
    );
    const row = (await screen.findByText("Zapisana")).closest("tr")!;
    expect(row).toHaveTextContent("a1b2c3d4e5f6…");
    expect(row).toHaveTextContent("Kartoteki i pule urlopowe, Wnioski urlopowe");
    unmount();

    get.mockRejectedValueOnce({ response: { status: 500, data: { detail: "Błąd" } } });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <HrImportHistory />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByText("Nie było jeszcze żadnego importu.")).not.toBeInTheDocument();
  });
});
