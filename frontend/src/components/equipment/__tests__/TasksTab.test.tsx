/**
 * „Do zrobienia” po makiecie 19.10.2026: „Przypomnij” przy zwrocie po terminie
 * (dzwonek dla konta, wiadomość z poczty recepcji dla osoby bez konta, błąd
 * serwera jako komunikat), awaria listy nie wygląda jak pusta lista.
 * Dane fikcyjne — repo jest publiczne.
 */
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

import { TasksTab } from "@/components/equipment/TasksTab";
import type { EquipmentSummary, EquipmentTask } from "@/lib/api/equipment";
import { warsawToday } from "@/lib/warsaw-date";

function shift(days: number): string {
  const date = new Date(`${warsawToday()}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function task(overrides: Partial<EquipmentTask>): EquipmentTask {
  return {
    id: 1,
    kind: "zwrot",
    status: "otwarte",
    title: "Odbierz sprzęt: Jan Testowy",
    due_on: shift(-3),
    overdue_days: 3,
    holder: { kind: "contract", id: 11, name: "Jan Testowy" },
    protocol: null,
    details: { client_name: "Klient Fikcyjny", reason: "koniec_wspolpracy", items: 1 },
    ...overrides,
  };
}

const SUMMARY: EquipmentSummary = {
  free_by_category: {
    laptop: 3,
    telefon: 2,
    monitor: 0,
    karta_sim: 1,
    karta_dostepu: 1,
    akcesorium: 4,
    inne: 0,
  },
  by_status: { na_stanie: 11, wydany: 4, serwis: 0, wycofany: 0, zgubiony: 0 },
  protocols_waiting: 0,
  import_unresolved: 0,
};

function serve(tasks: EquipmentTask[] | Error) {
  get.mockImplementation((url: string) => {
    if (url.endsWith("/tasks")) {
      return tasks instanceof Error ? Promise.reject(tasks) : Promise.resolve({ data: { items: tasks } });
    }
    if (url.endsWith("/summary")) return Promise.resolve({ data: SUMMARY });
    return Promise.reject(new Error(`nieoczekiwane ${url}`));
  });
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TasksTab onIssue={vi.fn()} onReturn={vi.fn()} onOpenProtocol={vi.fn()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
});

describe("TasksTab — „Przypomnij” przy zwrocie po terminie", () => {
  it("osoba bez konta: trasa oddaje adres, recepcja otwiera gotową wiadomość", async () => {
    const user = userEvent.setup();
    serve([task({})]);
    post.mockResolvedValue({
      data: { channel: "mail", email: "jan.testowy@example.com", reminded_on: warsawToday() },
    });
    renderTab();

    const overdue = await screen.findByRole("group", { name: "Po terminie" });
    await user.click(within(overdue).getByRole("button", { name: "Przypomnij" }));

    expect(post).toHaveBeenCalledWith("/api/equipment/tasks/1/remind");
    const dialog = await screen.findByRole("dialog", { name: "Przypomnij: Jan Testowy" });
    const mail = within(dialog).getByRole("link", { name: "Otwórz w poczcie" });
    expect(mail.getAttribute("href")).toMatch(/^mailto:jan.testowy%40example.com\?subject=Zwrot%20sprz/);
    expect(showToast).not.toHaveBeenCalled();
  });

  it("konto NEXUSA: dzwonek i mail wychodzą z serwera, recepcja widzi potwierdzenie", async () => {
    const user = userEvent.setup();
    serve([task({ holder: { kind: "user", id: 7, name: "Anna Przykładowa" } })]);
    post.mockResolvedValue({
      data: { channel: "powiadomienie", email: null, reminded_on: warsawToday() },
    });
    renderTab();

    await user.click(await screen.findByRole("button", { name: "Przypomnij" }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "Przypomnienie wysłane: Anna Przykładowa (dzwonek i mail)",
        "success",
      ),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("konto NEXUSA, ale dzwonek nie wyszedł: okno poczty bez „nie ma konta” (audyt 22.10, F23)", async () => {
    const user = userEvent.setup();
    serve([task({ holder: { kind: "user", id: 7, name: "Anna Przykładowa" } })]);
    post.mockResolvedValue({
      data: { channel: "mail", email: "anna@example.com", reminded_on: warsawToday() },
    });
    renderTab();

    await user.click(await screen.findByRole("button", { name: "Przypomnij" }));
    const dialog = await screen.findByRole("dialog", { name: "Przypomnij: Anna Przykładowa" });
    expect(dialog).not.toHaveTextContent("nie ma konta");
    expect(dialog).toHaveTextContent("Dzwonek w NEXUSIE nie wyszedł");
    expect(showToast).not.toHaveBeenCalled();
  });

  it("odmowa serwera (np. brak adresu) to komunikat, nie cisza", async () => {
    const user = userEvent.setup();
    serve([task({})]);
    post.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 409,
        data: { detail: "Ta osoba nie ma adresu e-mail w NEXUSIE — przypomnij telefonicznie." },
      },
    });
    renderTab();

    await user.click(await screen.findByRole("button", { name: "Przypomnij" }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "Ta osoba nie ma adresu e-mail w NEXUSIE — przypomnij telefonicznie.",
        "error",
      ),
    );
  });

  it("zwrot w terminie nie ma „Przypomnij” na wierzchu (jest w ⋯), przypomniane widać w wierszu", async () => {
    serve([
      task({
        id: 2,
        due_on: shift(10),
        overdue_days: 0,
        details: { reason: "odejscie", last_day: shift(10), items: 2, reminded_on: warsawToday() },
      }),
    ]);
    renderTab();

    const later = await screen.findByRole("group", { name: "Później" });
    expect(within(later).queryByRole("button", { name: "Przypomnij" })).toBeNull();
    expect(within(later).getByRole("button", { name: "Przyjmij zwrot" })).toBeInTheDocument();
    expect(within(later).getByText(/przypomniano \d{2}\.\d{2}/)).toBeInTheDocument();
  });

  it("awaria listy zadań to komunikat z ponowieniem, nie „Nic do zrobienia”", async () => {
    serve(new Error("500"));
    renderTab();

    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByText(/Nic do zrobienia/)).toBeNull();
  });
});

describe("TasksTab — zadanie podpisu", () => {
  it("tytuł niesie osobę, numer protokołu · klient · „wysłany” idą do drugiej linii", async () => {
    serve([
      task({
        id: 3,
        kind: "podpis",
        // Zapisany tytuł sprzed 20.10 ma numer — przy 1280 px ucinał nazwisko.
        title: "Podpis protokołu PZO/2026/10/001: Jan Testowy",
        due_on: shift(2),
        overdue_days: 0,
        protocol: {
          id: 41,
          number: "PZO/2026/10/001",
          status: "oczekuje",
          categories: ["laptop"],
          client_name: "Klient Fikcyjny",
          link_sent_on: "2026-10-19",
        },
        details: {},
      }),
    ]);
    renderTab();

    const later = await screen.findByRole("group", { name: "Później" });
    expect(within(later).getByText("Podpis protokołu: Jan Testowy")).toBeInTheDocument();
    expect(within(later).queryByText(/Podpis protokołu PZO/)).toBeNull();
    expect(
      within(later).getByText("PZO/2026/10/001 · Klient Fikcyjny · wysłany 19.10"),
    ).toBeInTheDocument();
    expect(within(later).getByRole("button", { name: "Wyślij link ponownie" })).toBeInTheDocument();
  });
});
