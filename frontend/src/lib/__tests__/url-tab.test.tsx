import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { resolveUrlTab, urlWithTab, useUrlTab } from "@/lib/url-tab";

const TABS = ["pipeline", "champion", "chat", "ai-matching"] as const;
type Tab = (typeof TABS)[number];
const ALIASES: Record<string, Tab> = {
  "champion-profile": "champion",
  similar: "ai-matching",
  notes: "pipeline",
};

describe("resolveUrlTab", () => {
  it("rozpoznaje dozwoloną zakładkę i alias ze starych powiadomień", () => {
    expect(resolveUrlTab("chat", TABS, ALIASES)).toBe("chat");
    expect(resolveUrlTab("champion-profile", TABS, ALIASES)).toBe("champion");
    expect(resolveUrlTab("notes", TABS, ALIASES)).toBe("pipeline");
  });

  it("nieznana wartość to brak celu, nie zakładka domyślna", () => {
    expect(resolveUrlTab("nie-ma", TABS, ALIASES)).toBeNull();
    expect(resolveUrlTab(null, TABS, ALIASES)).toBeNull();
    expect(resolveUrlTab("", TABS, ALIASES)).toBeNull();
  });
});

describe("urlWithTab", () => {
  it("zakładka domyślna zdejmuje parametr, inne go ustawiają — reszta adresu zostaje", () => {
    expect(
      urlWithTab("https://x.test/jobs/5?tab=chat&candidate=9", "pipeline", "pipeline"),
    ).toBe("/jobs/5?candidate=9");
    expect(urlWithTab("https://x.test/jobs/5?candidate=9", "champion", "pipeline")).toBe(
      "/jobs/5?candidate=9&tab=champion",
    );
  });
});

describe("useUrlTab", () => {
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("idzie za zmianą WARTOŚCI parametru (miękka nawigacja) i zapisuje wybór w adresie", () => {
    window.history.replaceState(null, "", "/jobs/5");
    const { result, rerender } = renderHook(
      ({ requested }: { requested: string | null }) =>
        useUrlTab<Tab>({ requested, validTabs: TABS, defaultTab: "pipeline", aliases: ALIASES }),
      { initialProps: { requested: null as string | null } },
    );
    expect(result.current[0]).toBe("pipeline");

    rerender({ requested: "champion-profile" });
    expect(result.current[0]).toBe("champion");

    act(() => result.current[1]("chat"));
    expect(result.current[0]).toBe("chat");
    expect(window.location.search).toBe("?tab=chat");

    // Ten sam parametr przy kolejnym renderze nie cofa ręcznego wyboru.
    rerender({ requested: "champion-profile" });
    expect(result.current[0]).toBe("chat");
  });
});
