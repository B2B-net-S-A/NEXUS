/**
 * „Dokumenty do startu” w panelu osoby (0649): klient bez listy nie widzi nic,
 * konto bez dostępu też, a awaria mówi o sobie. Przyciski idą za uprawnieniami
 * z serwera: rekruter dodaje, Delivery Lead sprawdza i widzi PESEL.
 */
import * as React from "react";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { startDocsApi, usePairAction } from "@/lib/api/start-documents";

import { StartDocsCard } from "../StartDocsCard";
import { StartDocsTasksSection, StartDocsTopbarBlock } from "../StartDocsTasks";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {},
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    put: (...args: unknown[]) => put(...args),
    delete: vi.fn(),
    patch: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const item = (fields: Record<string, unknown>) => ({
  id: 1,
  name: "NDA",
  note: null,
  kind: "file",
  required: true,
  offset_days: -2,
  link_url: null,
  fill_from_agreement: false,
  template_name: null,
  state: "missing",
  file_name: null,
  has_value: false,
  delivered_at: null,
  delivered_by_name: null,
  checked_at: null,
  checked_by_name: null,
  reason: null,
  reason_by_name: null,
  ...fields,
});

const pair = (fields: Record<string, unknown> = {}) => ({
  candidate_id: 5,
  job_id: 7,
  client_id: 11,
  client_name: "Nordea",
  start_date: "2026-11-09",
  deadline: "2026-11-05",
  tone: "today",
  working: false,
  done: 1,
  total: 3,
  recruiter_name: "Rekruter Test",
  delivery_lead_name: "DL Test",
  agreement_number: "1556/2026",
  list_sent_at: null,
  items: [
    item({ id: 1, name: "Umowa", kind: "agreement", state: "delivered" }),
    item({ id: 2, name: "NDA", template_name: "nda.docx" }),
    item({ id: 3, name: "PESEL", kind: "pesel" }),
    item({ id: 4, name: "Certyfikaty", required: false }),
  ],
  permissions: { can_work: true, can_review: false, can_download: true, can_view_pesel: false },
  ...fields,
});

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StartDocsCard candidateId={5} jobId={7} />
    </QueryClientProvider>,
  );
}

function renderTasks(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  put.mockReset();
});

describe("StartDocsCard", () => {
  it("klient bez listy: karty nie ma", async () => {
    get.mockResolvedValue({ data: null });
    const { container } = renderCard();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector("section")).toBeNull());
  });

  it("konto bez dostępu: karty nie ma, bez czerwonego błędu", async () => {
    get.mockRejectedValue({ response: { status: 403 } });
    const { container } = renderCard();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector('[role="alert"]')).toBeNull());
    expect(container.querySelector("section")).toBeNull();
  });

  it("awaria serwera nie udaje braku dokumentów", async () => {
    get.mockRejectedValue({ response: { status: 500 } });
    renderCard();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się sprawdzić");
  });

  it("rekruter widzi postęp, termin i dodawanie, bez sprawdzania", async () => {
    get.mockResolvedValue({ data: pair() });
    renderCard();
    expect(await screen.findByText("1 z 3")).toBeInTheDocument();
    expect(screen.getByText(/Start 09\.11, termin dziś/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz wzór/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wpisz PESEL/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sprawdzone" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Przypomnij rekruterowi/ })).toBeNull();
    expect(screen.getByText(/Certyfikaty \(opcjonalnie\)/)).toBeInTheDocument();
  });

  it("Delivery Lead sprawdza plik i odsłania PESEL dopiero na klik", async () => {
    const data = pair({
      done: 3,
      permissions: { can_work: true, can_review: true, can_download: true, can_view_pesel: true },
      items: [
        item({ id: 2, name: "NDA", state: "delivered", file_name: "nda.pdf" }),
        item({ id: 3, name: "PESEL", kind: "pesel", state: "delivered", has_value: true }),
      ],
    });
    get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("/pesel") ? { pesel: "44051401458" } : data }),
    );
    renderCard();
    expect(await screen.findByRole("button", { name: "Sprawdzone" })).toBeInTheDocument();
    expect(screen.queryByTestId("start-docs-pesel")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Pokaż/ }));
    expect(await screen.findByTestId("start-docs-pesel")).toHaveTextContent("44051401458");
  });

  it("zwrócony dokument pokazuje powód", async () => {
    get.mockResolvedValue({
      data: pair({
        items: [
          item({ id: 2, name: "NDA", state: "returned", reason: "brak podpisu", reason_by_name: "DL Test" }),
        ],
      }),
    });
    renderCard();
    expect(await screen.findByText(/Zwrócone: brak podpisu \(DL Test\)/)).toBeInTheDocument();
  });

  it("komplet nie przypomina i nie proponuje maila", async () => {
    get.mockResolvedValue({
      data: pair({
        done: 1,
        total: 1,
        items: [item({ id: 1, name: "Umowa", kind: "agreement", state: "delivered" })],
      }),
    });
    renderCard();
    expect(await screen.findByText(/Komplet\./)).toBeInTheDocument();
    expect(screen.queryByTestId("start-docs-send-list")).toBeNull();
  });

  it("bez połączonej skrzynki mail daje się tylko skopiować", async () => {
    get.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.endsWith("/list-mail")
          ? {
              to: "a@x.pl",
              subject: "Dokumenty przed startem w Nordea",
              text: "Dzień dobry,",
              attachments: ["nda.docx"],
              mailbox_connected: false,
              list_sent_at: null,
            }
          : pair(),
      }),
    );
    renderCard();
    fireEvent.click(await screen.findByTestId("start-docs-send-list"));
    expect(await screen.findByText(/nie jest połączona z NEXUSEM/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Skopiuj treść" })).toBeInTheDocument();
  });
});

const mineRow = {
  candidate_id: 5,
  job_id: 7,
  candidate_name: "Anna Testowa",
  job_title: "Analityk",
  client_name: "Nordea",
  agreement_number: "1556/2026",
  start_date: "2026-11-02",
  deadline: "2026-10-29",
  tone: "late",
  working: true,
  done: 1,
  total: 3,
  missing: ["NDA", "KRK"],
  to_check: [],
  recruiter_name: "Rekruter Test",
};

describe("Wysyłka plików", () => {
  it("plik idzie jako multipart: bez tego axios wysyła JSON i serwer odmawia", async () => {
    put.mockResolvedValue({ data: pair() });
    const file = new File(["%PDF-1.4"], "nda.pdf", { type: "application/pdf" });
    await startDocsApi.uploadFile(5, 7, 2, file);
    const [url, body, config] = put.mock.calls[0];
    expect(url).toBe("/api/start-documents/pair/5/7/items/2/file");
    expect(body).toBeInstanceOf(FormData);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
  });
});

describe("Odświeżanie po zmianie", () => {
  it("zmiana stanu odświeża plakietkę na Tablicy i listę w pasku", async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => usePairAction(5, 7), { wrapper });
    await act(() => result.current.mutateAsync(async () => pair() as never));
    const keys = spy.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toContainEqual(["kanban", "7"]);
    expect(keys).toContainEqual(["kanban", 7]);
    expect(keys).toContainEqual(["start-docs", "mine"]);
  });
});

describe("Pulpit i pasek", () => {
  it("Delivery Lead widzi rekrutera, stan pracy i przypomnienie", async () => {
    get.mockResolvedValue({ data: { role: "delivery_lead", items: [mineRow] } });
    renderTasks(<StartDocsTasksSection />);
    expect(await screen.findByText("Już pracuje")).toBeInTheDocument();
    expect(screen.getByText(/Brakuje: NDA, KRK/)).toHaveTextContent("rekruter: Rekruter Test");
    expect(screen.getByRole("button", { name: /Przypomnij rekruterowi/ })).toBeInTheDocument();
  });

  it("rekruter dostaje przejście do uzupełnienia, bez przypominania", async () => {
    get.mockResolvedValue({ data: { role: "recruiter", items: [mineRow] } });
    renderTasks(<StartDocsTasksSection />);
    expect(await screen.findByRole("link", { name: /Uzupełnij/ })).toHaveAttribute(
      "href",
      "/jobs/7?candidate=5",
    );
    expect(screen.queryByRole("button", { name: /Przypomnij rekruterowi/ })).toBeNull();
  });

  it("nic do zrobienia: sekcji i bloku nie ma", async () => {
    get.mockResolvedValue({ data: { role: "recruiter", items: [] } });
    const { container } = renderTasks(
      <>
        <StartDocsTasksSection />
        <StartDocsTopbarBlock />
      </>,
    );
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="start-docs-tasks"]')).toBeNull();
    expect(container.querySelector('[data-testid="start-docs-topbar"]')).toBeNull();
  });
});
