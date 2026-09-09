import { afterEach, beforeEach, expect, it } from "vitest";
import { api } from "@/lib/api";
import { requirementVerificationsApi } from "@/lib/requirement-verifications-api";

let previous: typeof api.defaults.adapter;
let captured: Array<{ method?: string; url: string; body: unknown }>;
beforeEach(() => {
  captured = [];
  previous = api.defaults.adapter;
  api.defaults.adapter = async config => {
    captured.push({ method: config.method,
      url: new URL(config.url!, config.baseURL).pathname,
      body: config.data ? JSON.parse(config.data) : null });
    return { data: {}, status: 200, statusText: "OK", headers: {}, config };
  };
});
afterEach(() => { api.defaults.adapter = previous; });

it("reads evidence through the registered API route with the real HTTP client", async () => {
  await requirementVerificationsApi.read(565252, 7709);
  expect(captured).toEqual([{ method: "get", url: "/api/candidate-search/jobs/565252/candidates/7709/verifications", body: null }]);
});
it("writes to the same API route and preserves source-version guards", async () => {
  const body = { requirement_index: 0, requirements_fingerprint: "criteria-version",
    candidate_version: "candidate-version", status: "unknown" as const,
    evidence: "No verified evidence", usage_context: "Review pending", verified_at: "2026-09-09T10:00:00Z" };
  await requirementVerificationsApi.save(565252, 7709, body);
  expect(captured).toEqual([{ method: "post", url: "/api/candidate-search/jobs/565252/candidates/7709/verifications", body }]);
});
