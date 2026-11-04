/**
 * Panel „Pytania klienta z rozmów” w profilu Championa: domyślnie pytania tej
 * rekrutacji, cała lista klienta i archiwum w drugiej zakładce. Pytanie dopisuje
 * się do SZKICU (pytania screeningowe / historyczne pytania klienta), pytanie
 * już obecne jest oznaczone, a awaria nie wygląda jak pusta pula.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => mocks.get(...a) },
}));

import {
  ChampionClientQuestionsPanel,
  normalizeQuestion,
} from "@/components/ChampionClientQuestionsPanel";

const POOL = [
  { id: 1, text: "Jak skalujesz Kafkę?", created_at: null },
  { id: 2, text: "Transakcje w Spring — propagacja", created_at: null },
  { id: 3, text: "Doświadczenie z bankowością", created_at: null },
];

function renderPanel(props: Partial<React.ComponentProps<typeof ChampionClientQuestionsPanel>> = {}) {
  const onAddScreening = vi.fn();
  const onAddHistorical = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ChampionClientQuestionsPanel
        jobId={22}
        screeningQuestions={["  jak SKALUJESZ   kafkę? "]}
        historicalQuestions={"- Transakcje w spring — propagacja\n"}
        canEdit
        onAddScreening={onAddScreening}
        onAddHistorical={onAddHistorical}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onAddScreening, onAddHistorical };
}

describe("ChampionClientQuestionsPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pyta o pulę po rekrutacji i dopisuje pytanie do szkicu", async () => {
    mocks.get.mockResolvedValue({ data: POOL });
    const { onAddScreening, onAddHistorical } = renderPanel();

    const row = await screen.findByTestId("champion-client-question-3");
    expect(screen.getByRole("tab", { name: /Z tej rekrutacji/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Z tej rekrutacji/ })).toHaveTextContent("3");
    expect(mocks.get).toHaveBeenCalledWith("/api/interview-cycle/client-questions", {
      params: { job_id: 22, limit: 200 },
    });
    expect(mocks.get).not.toHaveBeenCalledWith(
      "/api/interview-cycle/client-questions",
      expect.objectContaining({ params: expect.objectContaining({ scope: "client" }) }),
    );

    fireEvent.click(within(row).getByRole("button", { name: "Dodaj do pytań screeningowych" }));
    expect(onAddScreening).toHaveBeenCalledWith("Doświadczenie z bankowością");
    fireEvent.click(within(row).getByRole("button", { name: "Dodaj do historycznych pytań" }));
    expect(onAddHistorical).toHaveBeenCalledWith("Doświadczenie z bankowością");
  });

  it("pytanie już obecne (bez wielkości liter) jest oznaczone „już w profilu”", async () => {
    mocks.get.mockResolvedValue({ data: POOL });
    renderPanel();

    const inScreening = await screen.findByTestId("champion-client-question-1");
    expect(inScreening).toHaveTextContent("już w profilu");
    expect(
      within(inScreening).queryByRole("button", { name: "Dodaj do pytań screeningowych" }),
    ).not.toBeInTheDocument();
    expect(
      within(inScreening).getByRole("button", { name: "Dodaj do historycznych pytań" }),
    ).toBeInTheDocument();

    const inHistorical = screen.getByTestId("champion-client-question-2");
    expect(inHistorical).toHaveTextContent("już w profilu");
    expect(
      within(inHistorical).queryByRole("button", { name: "Dodaj do historycznych pytań" }),
    ).not.toBeInTheDocument();

    expect(screen.getByTestId("champion-client-question-3")).not.toHaveTextContent("już w profilu");
  });

  it("bez prawa edycji lista jest tylko do odczytu", async () => {
    mocks.get.mockResolvedValue({ data: POOL });
    renderPanel({ canEdit: false });
    await screen.findByTestId("champion-client-question-3");
    expect(screen.queryByRole("button", { name: /Dodaj do/ })).not.toBeInTheDocument();
  });

  it("pusta pula mówi, skąd przyjdą pytania", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    renderPanel();
    expect(await screen.findByText(/Jeszcze nic/)).toBeInTheDocument();
    expect(screen.getByText(/Wszystkie pytania klienta”/)).toBeInTheDocument();
  });

  it("awaria odczytu to komunikat z „Ponów”, nie pusta pula", async () => {
    mocks.get.mockRejectedValue(new Error("Network Error"));
    renderPanel();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Nie udało się wczytać pytań klienta/);
    expect(screen.queryByText(/Jeszcze nic/)).not.toBeInTheDocument();
    mocks.get.mockResolvedValue({ data: POOL });
    fireEvent.click(within(alert).getByRole("button", { name: "Ponów" }));
    expect(await screen.findByTestId("champion-client-question-1")).toBeInTheDocument();
  });

  it("archiwum rozmów pobiera się dopiero po rozwinięciu i pokazuje, co pasuje", async () => {
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({
        data:
          url === "/api/interview-cycle/client-questions/archive"
            ? [{ id: 40, text: "Jak działa garbage collector w Javie?", matched: ["java"] }]
            : POOL,
      }),
    );
    const { onAddScreening } = renderPanel();
    await screen.findByTestId("champion-client-question-3");
    // Pod rekrutacją archiwum nie stoi: jest w zakładce z całą listą klienta.
    expect(screen.queryByRole("button", { name: /Z archiwum rozmów/ })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Wszystkie pytania klienta" }));
    expect(mocks.get).not.toHaveBeenCalledWith(
      "/api/interview-cycle/client-questions/archive",
      expect.anything(),
    );

    fireEvent.click(screen.getByRole("button", { name: /Z archiwum rozmów/ }));
    const row = await screen.findByTestId("champion-archive-question-40");
    expect(mocks.get).toHaveBeenCalledWith("/api/interview-cycle/client-questions/archive", {
      params: { job_id: 22, limit: 20 },
    });
    expect(row).toHaveTextContent("pasuje: java");
    fireEvent.click(within(row).getByRole("button", { name: "Dodaj do pytań screeningowych" }));
    expect(onAddScreening).toHaveBeenCalledWith("Jak działa garbage collector w Javie?");
  });

  it("puste archiwum mówi to wprost", async () => {
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: url === "/api/interview-cycle/client-questions/archive" ? [] : POOL,
      }),
    );
    renderPanel();
    await screen.findByTestId("champion-client-question-3");
    fireEvent.click(screen.getByRole("tab", { name: "Wszystkie pytania klienta" }));
    fireEvent.click(screen.getByRole("button", { name: /Z archiwum rozmów/ }));
    expect(await screen.findByText(/Brak pytań z archiwum/)).toBeInTheDocument();
  });

  it("„Wszystkie pytania klienta” grupuje po rekrutacji, a szukanie zawęża listę", async () => {
    mocks.get.mockImplementation((_url: string, config?: { params?: { scope?: string } }) =>
      Promise.resolve({
        data:
          config?.params?.scope === "client"
            ? [
                { id: 7, text: "Jak prowadzisz retro?", created_at: null, jobs: [{ id: 22, title: "Project Manager" }] },
                { id: 8, text: "Transakcje w Spring", created_at: null, jobs: [{ id: 30, title: "Java Developer" }] },
                { id: 9, text: "Opowiedz o sobie", created_at: null, jobs: [{ id: 22, title: "Project Manager" }, { id: 30, title: "Java Developer" }] },
                { id: 10, text: "Pytanie po poprawce debriefu", created_at: null, jobs: [] },
              ]
            : [],
      }),
    );
    const { onAddScreening } = renderPanel();
    fireEvent.click(await screen.findByRole("tab", { name: "Wszystkie pytania klienta" }));

    const pm = await screen.findByTestId("all-client-questions-group-22");
    expect(mocks.get).toHaveBeenCalledWith("/api/interview-cycle/client-questions", {
      params: { job_id: 22, scope: "client", limit: 500 },
    });
    expect(within(pm).getByRole("link", { name: "Project Manager" })).toHaveAttribute("href", "/jobs/22");
    expect(pm).toHaveTextContent("ta rekrutacja");
    expect(pm).toHaveTextContent("(2)");
    expect(pm).not.toHaveTextContent("Transakcje w Spring");

    const java = screen.getByTestId("all-client-questions-group-30");
    expect(java).toHaveTextContent("Transakcje w Spring");
    expect(java).toHaveTextContent("Opowiedz o sobie");
    expect(java).not.toHaveTextContent("ta rekrutacja");
    expect(screen.getByTestId("all-client-questions-group-none")).toHaveTextContent("Bez wskazanej rekrutacji");

    fireEvent.click(within(java).getAllByRole("button", { name: "Dodaj do pytań screeningowych" })[0]);
    expect(onAddScreening).toHaveBeenCalledWith("Transakcje w Spring");

    const search = screen.getByRole("searchbox", { name: /Szukaj w pytaniach/ });
    fireEvent.change(search, { target: { value: "spring" } });
    expect(screen.queryByTestId("all-client-questions-group-22")).toBeNull();
    expect(screen.getByTestId("all-client-questions-group-30")).toHaveTextContent("Transakcje w Spring");
    expect(screen.getByTestId("all-client-questions-group-30")).not.toHaveTextContent("Opowiedz o sobie");

    fireEvent.change(search, { target: { value: "project manager" } });
    expect(screen.getByTestId("all-client-questions-group-22")).toBeInTheDocument();
    expect(screen.queryByTestId("all-client-questions-group-30")).toBeNull();

    fireEvent.change(search, { target: { value: "nie ma takiego" } });
    expect(screen.getByText("Nic nie pasuje do tego wyszukiwania.")).toBeInTheDocument();
  });

  it("awaria pełnej listy to komunikat z „Ponów”, nie pustka", async () => {
    mocks.get.mockImplementation((_url: string, config?: { params?: { scope?: string } }) =>
      config?.params?.scope === "client"
        ? Promise.reject(new Error("Network Error"))
        : Promise.resolve({ data: [] }),
    );
    renderPanel();
    fireEvent.click(await screen.findByRole("tab", { name: "Wszystkie pytania klienta" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Nie udało się wczytać pytań klienta/);
    expect(screen.queryByText(/nie ma zapisanych pytań/)).toBeNull();
  });

  it("normalizacja pomija punktor, białe znaki i wielkość liter", () => {
    expect(normalizeQuestion("• Jak   TESTUJESZ? ")).toBe("jak testujesz?");
  });
});
