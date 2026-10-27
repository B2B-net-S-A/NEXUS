import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), templateGet: vi.fn(), templateList: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  pipelineTemplatesApi: {
    get: (...a: unknown[]) => mocks.templateGet(...a),
    list: (...a: unknown[]) => mocks.templateList(...a),
  },
}));

import { useJobPipelineTemplate } from "@/hooks/useJobPipelineTemplate";

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
