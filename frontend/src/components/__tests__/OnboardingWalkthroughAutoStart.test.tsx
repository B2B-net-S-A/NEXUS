import * as React from "react";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  OPEN_ONBOARDING_EVENT,
  requestOnboardingOpen,
  useOnboarding,
} from "@/components/OnboardingWalkthrough";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

function Harness() {
  const { shouldShow } = useOnboarding();
  return <div>{shouldShow ? "przewodnik-otwarty" : "przewodnik-zamkniety"}</div>;
}

describe("useOnboarding", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it("does not start by itself for a user who never finished it", async () => {
    vi.useFakeTimers();
    render(<Harness />);
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("przewodnik-zamkniety")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("opens when the settings action dispatches the event", () => {
    render(<Harness />);
    expect(OPEN_ONBOARDING_EVENT).toBe("nexus:open-onboarding");
    act(() => requestOnboardingOpen());
    expect(screen.getByText("przewodnik-otwarty")).toBeInTheDocument();
  });
});
