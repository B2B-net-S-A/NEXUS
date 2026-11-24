import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), templateGet: vi.fn(), templateList: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  pipelineTemplatesApi: {
    get: (...a: unknown[]) => mocks.templateGet(...a),
    list: (...a: unknown[]) => mocks.templateList(...a),
  },
}));

import {
  useJobPipelineTemplate,
  type UseJobPipelineTemplateOptions,
} from "@/hooks/useJobPipelineTemplate";

const TEMPLATE = {
  data: {
    name: "IT",
    rejection_reasons: [{ id: 1, name: "Stawka", category: "rejected" }],
    stages: [],
  },
};

function setup(seed?: (client: QueryClient) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed?.(client);
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useJobPipelineTemplate(7), { wrapper });
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.templateGet.mockReset().mockResolvedValue(TEMPLATE);
  mocks.templateList.mockReset().mockResolvedValue({ data: [] });
});

// 27.10.2026: Tablica pytała `GET /api/jobs/{id}` sama, obok zapytania strony.
describe("useJobPipelineTemplate — rekrutacja z klucza strony", () => {
  it("świeża rekrutacja strony (`[\"job\", \"7\"]`) — bez drugiego GET", async () => {
    const hook = setup((client) =>
      client.setQueryData(["job", "7"], { pipeline_template_id: 3, can_write_client_rate: true }),
    );
    await waitFor(() => expect(hook.result.current.templateName).toBe("IT"));
    expect(mocks.templateGet).toHaveBeenCalledWith(3);
    expect(hook.result.current.canWriteClientRate).toBe(true);
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("bez strony w pamięci pyta raz i zostawia odpowiedź pod kluczem strony", async () => {
    mocks.get.mockResolvedValue({ data: { pipeline_template_id: 3 } });
    const hook = setup();
    await waitFor(() => expect(hook.result.current.rejectionReasons).toHaveLength(1));
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.get).toHaveBeenCalledWith("/api/jobs/7");
  });
});

type HookProps = { jobId: number; options?: UseJobPipelineTemplateOptions };

function setupWith(initialProps: HookProps) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(({ jobId, options }: HookProps) => useJobPipelineTemplate(jobId, options), {
    wrapper,
    initialProps,
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const flush = () => act(async () => {
  await new Promise((r) => setTimeout(r, 0));
});

describe("useJobPipelineTemplate — podana rekrutacja, szablon i powody zapasowe", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
  });

  it("`enabled: false` nic nie pobiera i zwraca puste fakty", async () => {
    const hook = setupWith({ jobId: 7, options: { enabled: false } });
    await flush();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.templateGet).not.toHaveBeenCalled();
    expect(mocks.templateList).not.toHaveBeenCalled();
    expect(hook.result.current).toEqual({
      rejectionReasons: [],
      stagesWithScorecard: new Set(),
      templateName: null,
      budgetHourly: null,
      canWriteClientRate: false,
    });
  });

  it("`job: null` (strona jeszcze ładuje) czeka i nie robi własnego GET", async () => {
    const hook = setupWith({ jobId: 7, options: { job: null } });
    await flush();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.templateGet).not.toHaveBeenCalled();

    hook.rerender({ jobId: 7, options: { job: { pipeline_template_id: 3 } } });
    await waitFor(() => expect(hook.result.current.templateName).toBe("IT"));
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("podana rekrutacja: budżet z tekstu, prawo zapisu stawki, etapy ze scorecardem", async () => {
    mocks.templateGet.mockResolvedValue({
      data: {
        name: "Szablon IT",
        rejection_reasons: [
          { id: 1, name: "rate", label: "Za wysoka stawka", category: "rejected" },
          { id: 2, name: "other_offer", label: "  ", category: "withdrawn" },
        ],
        stages: [
          { id: 10, scorecard_schema: { questions: [{ key: "komunikacja" }] } },
          { id: 11, scorecard_schema: { questions: [] } },
          { id: 12, scorecard_schema: null },
          { id: 13, scorecard_schema: { questions: "nie-lista" } },
          { id: 14 },
        ],
      },
    });
    const hook = setupWith({
      jobId: 7,
      options: {
        job: { pipeline_template_id: 3, effective_budget_hourly: "155", can_write_client_rate: true },
      },
    });

    await waitFor(() => expect(hook.result.current.rejectionReasons).toHaveLength(2));
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.templateList).not.toHaveBeenCalled();
    expect(hook.result.current.budgetHourly).toBe(155);
    expect(hook.result.current.canWriteClientRate).toBe(true);
    expect(hook.result.current.templateName).toBe("Szablon IT");
    expect([...hook.result.current.stagesWithScorecard]).toEqual([10]);
    expect(hook.result.current.rejectionReasons).toEqual([
      { id: 1, label: "Za wysoka stawka", name: "rate", applies_to: ["rejected"] },
      { id: 2, label: "other_offer", name: "other_offer", applies_to: ["withdrawn"] },
    ]);
  });

  it("nowa referencja tej samej rekrutacji nie pobiera szablonu drugi raz", async () => {
    const hook = setupWith({ jobId: 7, options: { job: { pipeline_template_id: 3 } } });
    await waitFor(() => expect(hook.result.current.templateName).toBe("IT"));
    hook.rerender({ jobId: 7, options: { job: { pipeline_template_id: 3 } } });
    await flush();
    expect(mocks.templateGet).toHaveBeenCalledTimes(1);
  });

  it("nazwa szablonu z samych spacji albo nie-tekst to `null`, budżet ≤ 0 to `null`", async () => {
    mocks.templateGet.mockResolvedValue({
      data: { name: "   ", rejection_reasons: [{ id: 1, name: "Stawka", category: "rejected" }] },
    });
    const hook = setupWith({
      jobId: 7,
      options: { job: { pipeline_template_id: 3, effective_budget_hourly: 0, rate_budget_hourly: -5 } },
    });
    await waitFor(() => expect(hook.result.current.rejectionReasons).toHaveLength(1));
    expect(hook.result.current.templateName).toBeNull();
    expect(hook.result.current.budgetHourly).toBeNull();
    expect(hook.result.current.canWriteClientRate).toBe(false);
    expect(hook.result.current.stagesWithScorecard.size).toBe(0);
  });

  it("rekrutacja bez szablonu (import z Traffit) bierze powody z szablonu domyślnego", async () => {
    mocks.templateList.mockResolvedValue({
      data: [
        { id: 4, is_default: false },
        { id: 5, is_default: true },
      ],
    });
    mocks.templateGet.mockResolvedValue({
      data: {
        name: "Domyślny",
        rejection_reasons: [{ id: 9, name: "Brak kontaktu", category: "withdrawn" }],
      },
    });
    const hook = setupWith({ jobId: 7, options: { job: { pipeline_template_id: null } } });

    await waitFor(() => expect(hook.result.current.rejectionReasons).toHaveLength(1));
    expect(mocks.templateGet).toHaveBeenCalledTimes(1);
    expect(mocks.templateGet).toHaveBeenCalledWith(5);
    expect(hook.result.current.rejectionReasons[0]).toMatchObject({
      id: 9,
      applies_to: ["withdrawn"],
    });
    // Nazwa nagłówka zostaje pusta: szablon domyślny nie jest szablonem tej rekrutacji.
    expect(hook.result.current.templateName).toBeNull();
  });

  it("szablon bez powodów też sięga po domyślny; bez domyślnego lista zostaje pusta", async () => {
    mocks.templateGet.mockResolvedValue({ data: { name: "Pusty", rejection_reasons: null } });
    mocks.templateList.mockResolvedValue({ data: [{ id: 4, is_default: false }] });
    const hook = setupWith({ jobId: 7, options: { job: { pipeline_template_id: 3 } } });

    await waitFor(() => expect(mocks.templateList).toHaveBeenCalledTimes(1));
    await flush();
    expect(mocks.templateGet).toHaveBeenCalledTimes(1);
    expect(hook.result.current.templateName).toBe("Pusty");
    expect(hook.result.current.rejectionReasons).toEqual([]);
  });

  it("awaria listy szablonów: zapis w konsoli, pusta lista powodów, reszta faktów zostaje", async () => {
    mocks.templateList.mockRejectedValue(new Error("500"));
    const hook = setupWith({
      jobId: 7,
      options: { job: { pipeline_template_id: null, rate_budget_hourly: 120 } },
    });

    await waitFor(() =>
      expect(consoleError).toHaveBeenCalledWith(
        "Default rejection-reasons fallback failed",
        expect.any(Error),
      ),
    );
    expect(hook.result.current.rejectionReasons).toEqual([]);
    expect(hook.result.current.budgetHourly).toBe(120);
  });

  it("awaria szablonu rekrutacji trafia do konsoli i nie wysypuje hooka", async () => {
    mocks.templateGet.mockRejectedValue(new Error("404"));
    const hook = setupWith({ jobId: 7, options: { job: { pipeline_template_id: 3 } } });

    await waitFor(() =>
      expect(consoleError).toHaveBeenCalledWith("Pipeline template load failed", expect.any(Error)),
    );
    expect(mocks.templateList).not.toHaveBeenCalled();
    expect(hook.result.current.rejectionReasons).toEqual([]);
    expect(hook.result.current.templateName).toBeNull();
  });

  it("awaria `GET /api/jobs/{id}` trafia do konsoli, fakty zostają puste", async () => {
    mocks.get.mockRejectedValue(new Error("offline"));
    const hook = setupWith({ jobId: 7 });

    await waitFor(() =>
      expect(consoleError).toHaveBeenCalledWith("Pipeline template load failed", expect.any(Error)),
    );
    expect(mocks.templateGet).not.toHaveBeenCalled();
    expect(hook.result.current.budgetHourly).toBeNull();
  });

  it("odmontowanie w trakcie `GET` rekrutacji: szablonu już nie pobiera", async () => {
    const job = deferred<{ data: unknown }>();
    mocks.get.mockReturnValue(job.promise);
    const hook = setupWith({ jobId: 7 });
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));

    hook.unmount();
    job.resolve({ data: { pipeline_template_id: 3 } });
    await flush();
    expect(mocks.templateGet).not.toHaveBeenCalled();
  });

  it("odmontowanie w trakcie pobierania szablonu: bez sięgania po domyślny", async () => {
    const template = deferred<typeof TEMPLATE>();
    mocks.templateGet.mockReturnValue(template.promise);
    const hook = setupWith({ jobId: 7, options: { job: { pipeline_template_id: 3 } } });
    await waitFor(() => expect(mocks.templateGet).toHaveBeenCalledTimes(1));

    hook.unmount();
    template.resolve({ data: { name: "IT", rejection_reasons: [], stages: [] } });
    await flush();
    expect(mocks.templateList).not.toHaveBeenCalled();
  });
});
