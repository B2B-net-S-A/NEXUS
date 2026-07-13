import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CloudTalkSettingsCard from "../CloudTalkSettingsCard";

const useQueryMock = vi.fn();

vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: unknown) => useQueryMock(options),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn() },
  cloudtalkApi: {
    listAgents: vi.fn(),
    syncAgents: vi.fn(),
    assignAgent: vi.fn(),
    unassignAgent: vi.fn(),
  },
}));

type QueryOptions = { queryKey?: string[] };

describe("CloudTalkSettingsCard readiness handling", () => {
  beforeEach(() => {
    useQueryMock.mockReset();
  });

  it("fails closed when the shared readiness endpoint is unavailable", () => {
    useQueryMock.mockImplementation((options: QueryOptions) => {
      if (options.queryKey?.[0] === "cloudtalk-health") {
        return { data: undefined, isLoading: false, isError: true };
      }
      return { data: [], isFetching: false };
    });

    render(<CloudTalkSettingsCard />);

    expect(screen.getByText("Status niedostępny")).toBeInTheDocument();
    expect(
      screen.getByText(/Integracja pozostaje zablokowana/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Integracja CloudTalk jest wyłączona/),
    ).not.toBeInTheDocument();
  });

  it("shows the disabled state only after a valid readiness response", () => {
    useQueryMock.mockImplementation((options: QueryOptions) => {
      if (options.queryKey?.[0] === "cloudtalk-health") {
        return {
          data: {
            checks: {
              cloudtalk: { status: "healthy", state: "unconfigured" },
            },
          },
          isLoading: false,
          isError: false,
        };
      }
      return { data: [], isFetching: false };
    });

    render(<CloudTalkSettingsCard />);

    expect(screen.getByText("Wyłączony")).toBeInTheDocument();
    expect(
      screen.getByText(/Integracja CloudTalk jest wyłączona/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Status niedostępny")).not.toBeInTheDocument();
  });
});
