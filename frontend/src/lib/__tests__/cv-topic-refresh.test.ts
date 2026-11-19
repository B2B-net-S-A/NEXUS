import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CV_TOPIC_QUERY_KEY } from "@/lib/api/boardTasks";
import {
  CV_TOPIC_REFRESH_WINDOW_MS,
  refreshCvTopicFromRealtime,
} from "@/lib/cv-topic-refresh";

function setup() {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  return { client, invalidate };
}

describe("refreshCvTopicFromRealtime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      configurable: true,
    });
  });

  it("pojedyncza ramka odświeża od razu, jak dawniej", () => {
    const { client, invalidate } = setup();
    refreshCvTopicFromRealtime(client);
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: CV_TOPIC_QUERY_KEY,
      refetchType: "active",
    });
    vi.advanceTimersByTime(CV_TOPIC_REFRESH_WINDOW_MS * 3);
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it("seria ramek w oknie daje jedno odświeżenie na jego końcu", () => {
    const { client, invalidate } = setup();
    for (let i = 0; i < 16; i += 1) {
      refreshCvTopicFromRealtime(client);
      vi.advanceTimersByTime(100);
    }
    // 16 ramek w 1,6 s: pierwsza od razu, reszta czeka na koniec okna.
    expect(invalidate).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(CV_TOPIC_REFRESH_WINDOW_MS);
    expect(invalidate).toHaveBeenCalledTimes(2);
    // Po odświeżeniu z końca okna bez nowych ramek nic więcej nie idzie.
    vi.advanceTimersByTime(CV_TOPIC_REFRESH_WINDOW_MS * 3);
    expect(invalidate).toHaveBeenCalledTimes(2);
  });

  it("ramka tuż po odświeżeniu z końca okna czeka na kolejne okno", () => {
    const { client, invalidate } = setup();
    refreshCvTopicFromRealtime(client);
    refreshCvTopicFromRealtime(client);
    vi.advanceTimersByTime(CV_TOPIC_REFRESH_WINDOW_MS);
    expect(invalidate).toHaveBeenCalledTimes(2);
    refreshCvTopicFromRealtime(client);
    expect(invalidate).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(CV_TOPIC_REFRESH_WINDOW_MS);
    expect(invalidate).toHaveBeenCalledTimes(3);
  });

  it("ukryta karta tylko oznacza ikonę jako nieaktualną", () => {
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      configurable: true,
    });
    const { client, invalidate } = setup();
    refreshCvTopicFromRealtime(client);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: CV_TOPIC_QUERY_KEY,
      refetchType: "none",
    });
  });

  it("osobne klienty zapytań (karty, testy) mają osobne okna", () => {
    const a = setup();
    const b = setup();
    refreshCvTopicFromRealtime(a.client);
    refreshCvTopicFromRealtime(b.client);
    expect(a.invalidate).toHaveBeenCalledTimes(1);
    expect(b.invalidate).toHaveBeenCalledTimes(1);
  });
});
