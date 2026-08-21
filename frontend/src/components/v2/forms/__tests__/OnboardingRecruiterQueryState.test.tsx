/**
 * Onboarding rekrutera: nieudane pobranie listy rekrutacji NIE może zamienić się
 * w trwałe `profile_completed=true` z pustym wyborem.
 *
 * To pierwszy ekran nowej osoby. Gałąź pusta wisiała na `!isLoading`, więc każda
 * awaria (500, deterministyczne 403 dla hybrydy HoR+DL, timeout) renderowała
 * „Nie ma jeszcze rekrutacji w systemie. Możesz pominąć ten krok" — twierdzenie
 * o firmie z ~53 tys. kandydatów i dziesiątkami żywych rekrutacji. Jedyną
 * aktywną kontrolką był „Zakończ onboarding", a backend ustawia
 * `profile_completed` bezwarunkowo i bez ścieżki powrotnej w UI.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ token: "t", setAuth: vi.fn(), user: null }),
}));

vi.mock("@/lib/onboarding-storage", () => ({
  markOnboardingCompleted: vi.fn(),
}));

import { OnboardingRecruiterV2 } from "@/components/v2/forms/OnboardingRecruiterV2";

const EMPTY_TEXT = /Nie ma jeszcze rekrutacji w systemie/;
const FINISH_BUTTON = /Zakończ onboarding/;

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderForm() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <OnboardingRecruiterV2 />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
});

describe("OnboardingRecruiterV2", () => {
  it("403 renderuje brak uprawnień i BLOKUJE zakończenie onboardingu", async () => {
    mocks.get.mockRejectedValue(httpError(403));

    renderForm();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
    // Zapis jest nieodwracalny — nie wolno go dopuścić na nieznanej liście.
    expect(screen.getByRole("button", { name: FINISH_BUTTON })).toBeDisabled();
  });

  it("500 renderuje awarię, nie „nie ma rekrutacji”", async () => {
    mocks.get.mockRejectedValue(httpError(500));

    renderForm();

    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: FINISH_BUTTON })).toBeDisabled();
  });

  it("sukces z zerem rekrutacji nadal pozwala pominąć krok", async () => {
    mocks.get.mockResolvedValue({ data: { items: [], total: 0 } });

    renderForm();

    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: FINISH_BUTTON }),
    ).not.toBeDisabled();
  });
});
