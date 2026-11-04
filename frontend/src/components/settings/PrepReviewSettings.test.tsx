import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { configProblems, previewScore, type PrepReviewConfig } from "@/lib/api/prepReviewConfig";

import { PrepReviewSettings } from "./PrepReviewSettings";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));

vi.mock("@/lib/api", () => ({ default: { get: mocks.get, put: mocks.put } }));

function config(): PrepReviewConfig {
  return {
    prep1: {
      weights: { topics: 25, must_answers: 40, client_questions: 20, talk_share: 15 },
      topics: [
        { label: "Klient i projekt", required: true },
        { label: "Stawka i dostępność", required: true },
      ],
    },
    prep2: {
      weights: { prep1_followup: 40, topics: 25, client_questions: 20, talk_share: 15 },
      topics: [{ label: "Punkty z notatki na Prep 2", required: true }],
    },
    answer_scale: {
      strong: { description: "Konkretny projekt", points: 100 },
      general: { description: "Bez przykładu", points: 50 },
      weak: { description: "Nie umie odpowiedzieć", points: 0 },
      missing: { description: "Nie padło", points: 0 },
    },
    max_client_questions: 20,
    good_threshold: 80,
    weak_threshold: 50,
    min_minutes_enabled: true,
    min_minutes: 10,
    talk_share_enabled: true,
    talk_share_target: 45,
    required_topic_caps_ok: true,
    weak_must_caps_ok: true,
    followup: {
      weak_answers: true,
      general_answers: true,
      missing_required_topics: true,
      unpracticed_client_questions: true,
      max_items: 5,
    },
    ai_hints: "",
  };
}

function state(canEdit: boolean) {
  return {
    config: config(),
    version: null,
    defaults: config(),
    can_edit: canEdit,
    history: [],
  };
}

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PrepReviewSettings />
    </QueryClientProvider>,
  );
}

describe("configProblems", () => {
  it("odrzuca wagi, które nie dają 100%, i rosnące punkty skali", () => {
    const c = config();
    c.prep1.weights.topics = 30;
    c.answer_scale.general.points = 100;
    c.answer_scale.strong.points = 90;
    expect(configProblems(c)).toEqual([
      "Prep 1: wagi kryteriów muszą dawać razem 100%.",
      "Punkty skali nie mogą rosnąć: mocna ≥ ogólna ≥ słaba ≥ nie było.",
    ]);
  });

  it("odrzuca pusty i powtórzony temat", () => {
    const c = config();
    c.prep2.topics.push({ label: "punkty z notatki na prep 2", required: false });
    c.prep1.topics.push({ label: " ", required: true });
    expect(configProblems(c)).toEqual([
      "Prep 1: każdy temat prowadzącego musi mieć nazwę.",
      "Prep 2: ten sam temat prowadzącego jest dwa razy.",
    ]);
  });
});

describe("previewScore", () => {
  it("liczy średnią ważoną i poziom z progów", () => {
    const weights = { a: 50, b: 50 };
    expect(previewScore(weights, { a: 100, b: 60 }, config())).toEqual({ total: 80, level: "good" });
    expect(previewScore(weights, { a: 40, b: 40 }, config())).toEqual({ total: 40, level: "weak" });
  });
});

describe("PrepReviewSettings", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.put.mockReset();
  });

  it("HoR publikuje zmianę z powodem", async () => {
    mocks.get.mockResolvedValue({ data: state(true) });
    mocks.put.mockImplementation(async (_url: string, body: { config: PrepReviewConfig }) => ({
      data: { ...state(true), config: body.config, version: 7, saved: true },
    }));
    renderSettings();

    const publish = await screen.findByRole("button", { name: "Opublikuj" });
    expect(publish).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Najwięcej pytań klienta"), { target: { value: "6" } });
    fireEvent.change(screen.getByLabelText("Powód zmiany (do historii)"), {
      target: { value: "za dużo punktów" },
    });
    fireEvent.click(publish);

    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    const [, body] = mocks.put.mock.calls[0];
    expect(body.config.max_client_questions).toBe(6);
    expect(body.reason).toBe("za dużo punktów");
    expect(await screen.findByText(/Opublikowano wersję 7/)).toBeInTheDocument();
  });

  it("blokuje publikację, gdy wagi nie dają 100%", async () => {
    mocks.get.mockResolvedValue({ data: state(true) });
    renderSettings();

    const slider = await screen.findByRole("slider", { name: /Tematy prowadzącego/ });
    fireEvent.change(slider, { target: { value: "30" } });

    expect(screen.getByText("Suma wag: 105% — musi być 100%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Opublikuj" })).toBeDisabled();
  });

  it("rekruter widzi ustawienia bez edycji", async () => {
    mocks.get.mockResolvedValue({ data: state(false) });
    renderSettings();

    expect(await screen.findByText(/Zmienia ją Head of Recruitment/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Opublikuj" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Najwięcej pytań klienta")).toBeDisabled();
  });

  it("awaria odczytu nie wygląda jak puste ustawienia", async () => {
    mocks.get.mockRejectedValue({ response: { status: 500, data: { detail: "boom" } } });
    renderSettings();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Suma wag")).not.toBeInTheDocument();
  });
});
