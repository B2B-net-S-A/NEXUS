/**
 * „Szukaj w CV” nad CV firmowym (23.10.2026, prośba Igora z przeglądu DL):
 * pasek jak przy oryginale, licznik trafień, słowa wymagania z zewnątrz.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const renderDocxSafely = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn() }) }));
vi.mock("@/lib/docx-preview-safe", () => ({
  renderDocxSafely: (...a: unknown[]) => renderDocxSafely(...a),
}));
vi.mock("@/lib/cv-docx-preview", () => ({ alignB2bLetterheadPreview: () => undefined }));
vi.mock("@/lib/docx-fit", () => ({ observeDocxFit: () => undefined }));
vi.mock("@/components/v2/cv-generator/ConsentAttachButton", () => ({ ConsentAttachButton: () => null }));

import type { DocumentSearchRequest } from "@/components/v2/files/FilePreviewModal";

import { StageCvPreview } from "../StageCvPreview";

const CV_HTML =
  "<section class='docx'><p>Selenium, C#, Gherkin — testy E2E.</p><p>Kafka i RabbitMQ w kolejkach.</p><p>Selenium Grid.</p></section>";

function mount(props: { searchable?: boolean; searchRequest?: DocumentSearchRequest | null } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const loadStageCvFile = vi.fn().mockResolvedValue({ blob: new Blob(["docx"]), filename: "CV.docx" });
  const ui = (extra: typeof props) => (
    <QueryClientProvider client={queryClient}>
      <StageCvPreview candidateId={1} jobId={2} cvStageId={3} loadStageCvFile={loadStageCvFile} {...extra} />
    </QueryClientProvider>
  );
  const view = render(ui(props));
  return { rerender: (extra: typeof props) => view.rerender(ui(extra)) };
}

beforeEach(() => {
  renderDocxSafely.mockReset();
  renderDocxSafely.mockImplementation(async (_blob: Blob, host: HTMLElement) => {
    host.innerHTML = CV_HTML;
  });
});

describe("StageCvPreview — Szukaj w CV", () => {
  it("bez `searchable` nie ma paska (edytor CV, inne podglądy)", async () => {
    mount();
    await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("searchbox", { name: "Szukaj w CV" })).toBeNull();
  });

  it("wpisane słowo podświetla trafienia w CV firmowym i liczy je", async () => {
    const user = userEvent.setup();
    mount({ searchable: true });
    const field = await screen.findByRole("searchbox", { name: "Szukaj w CV" });

    await user.type(field, "selenium");
    expect(await screen.findByText("1 z 2")).toBeInTheDocument();
    expect(document.querySelectorAll("mark[data-doc-search-hit]")).toHaveLength(2);

    await user.keyboard("{Enter}");
    expect(screen.getByText("2 z 2")).toBeInTheDocument();
  });

  it("brak trafień mówi „Brak wyników”", async () => {
    const user = userEvent.setup();
    mount({ searchable: true });
    await user.type(await screen.findByRole("searchbox", { name: "Szukaj w CV" }), "Kubernetes");
    expect(await screen.findByText("Brak wyników")).toBeInTheDocument();
  });

  it("klik w wymaganie: pole pokazuje nazwę, lupa szuka słów z serwera", async () => {
    const view = mount({ searchable: true });
    await screen.findByRole("searchbox", { name: "Szukaj w CV" });

    act(() => {
      view.rerender({
        searchable: true,
        searchRequest: { text: "Kolejki (Kafka lub RabbitMQ)", nonce: 1, terms: ["Kafka", "RabbitMQ"] },
      });
    });

    expect(screen.getByRole("searchbox", { name: "Szukaj w CV" })).toHaveValue("Kolejki (Kafka lub RabbitMQ)");
    expect(await screen.findByText("1 z 2")).toBeInTheDocument();
    expect(screen.getByTestId("document-search-terms")).toHaveTextContent("Szukam:KafkaRabbitMQ");
  });
});
