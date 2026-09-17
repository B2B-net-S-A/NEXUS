import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ default: { get } }));

import { useClientCvRule } from "@/components/v2/cv-generator/ClientCvRuleBanner";

const SLIM_URL = "/api/cv-generator/clients/5/rule-for-generation";
const FULL_URL = "/api/clients/5/cv-rule";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/**
 * Generator czyta regułę za bramką GENERACJI. Pełny odczyt za grafem klienta
 * dawał rekruterowi bez rekrutacji u klienta 403, a serwer i tak stosował
 * regułę — formularz nie wiedział o języku, zrzucie zgody ani numerze projektu.
 */
describe("useClientCvRule", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("reads the generator projection first", async () => {
    get.mockResolvedValueOnce({ data: { client_id: 5, is_active: true, cv_language: "en" } });
    const { result } = renderHook(() => useClientCvRule(5), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.cv_language).toBe("en");
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith(SLIM_URL);
  });

  it("falls back to the full rule when the role cannot generate (403)", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === SLIM_URL) throw { response: { status: 403, data: { detail: "Brak dostępu" } } };
      if (url === FULL_URL) return { data: { client_id: 5, is_active: true, cv_language: "pl" } };
      throw new Error(`unexpected ${url}`);
    });
    const { result } = renderHook(() => useClientCvRule(5), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.cv_language).toBe("pl");
  });

  it("does not hide a real failure behind the fallback", async () => {
    get.mockRejectedValueOnce({ response: { status: 500, data: {} } });
    const { result } = renderHook(() => useClientCvRule(5), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(get).toHaveBeenCalledTimes(1);
  });
});
