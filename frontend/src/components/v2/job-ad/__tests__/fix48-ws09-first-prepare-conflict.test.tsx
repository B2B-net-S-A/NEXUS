/**
 * Audyt 13.10.2026: dwie osoby otwierają okno rekrutacji bez ogłoszenia.
 * Druga klika „Przygotuj ogłoszenie”, gdy pierwsza już je przygotowała —
 * jej okno wysyła pustą wersję, a serwer odpowiada 409 `job_ad_changed`.
 * Okno ma wtedy pokazać komunikat serwera i wczytać ogłoszenie pierwszej
 * osoby, zamiast zostać na ekranie „nie ma jeszcze ogłoszenia”.
 */

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import type { JobAdState } from "@/lib/api/jobAd";

import { JobAdWindow, type JobAdWindowApi } from "../JobAdWindow";
import { adState, CONTENT, EMPTY_STATE } from "./job-ad-fixtures";

const MESSAGE = "Ktoś w międzyczasie przygotował to ogłoszenie. Wczytałem je.";

describe("JobAdWindow — pierwsze przygotowanie, gdy ogłoszenie już powstało", () => {
  it("po 409 pokazuje komunikat i wczytuje ogłoszenie innej osoby", async () => {
    const other: JobAdState = adState({
      content: { ...CONTENT, about: "Ogłoszenie przygotowane przez inną osobę." },
    });
    let loads = 0;
    const api: JobAdWindowApi = {
      get: vi.fn(async () => (++loads === 1 ? EMPTY_STATE : other)),
      generate: vi.fn(async () => {
        throw {
          response: {
            status: 409,
            data: { detail: { code: "job_ad_changed", message: MESSAGE } },
          },
        };
      }),
      save: vi.fn(),
      markPublished: vi.fn(),
      markRemoved: vi.fn(),
    };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobAdWindow jobId={7} jobTitle="Java Developer" open onClose={vi.fn()} api={api} />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Przygotuj ogłoszenie" }));

    // Okno nie znało wersji — wysyła pustą; serwer odpowiada 409.
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith(7, "pl", null));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(toast.showError).toHaveBeenCalledWith(MESSAGE);
    expect(await screen.findByRole("region", { name: "O projekcie" })).toHaveTextContent(
      "Ogłoszenie przygotowane przez inną osobę.",
    );
    expect(
      screen.queryByRole("heading", { name: "Ta rekrutacja nie ma jeszcze ogłoszenia" }),
    ).not.toBeInTheDocument();
  });
});
