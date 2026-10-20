import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toast = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import { ABOUT_MAX, RecruiterAbout } from "../RecruiterAbout";

function renderAbout(about: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RecruiterAbout slug="marta-n" about={about} />
    </QueryClientProvider>,
  );
  return screen.getByRole("textbox", { name: "O mnie" });
}

const saveButton = () => screen.getByRole("button", { name: "Zapisz „O mnie”" });

beforeEach(() => {
  apiMock.put.mockReset();
  toast.showSuccess.mockReset();
});

describe("RecruiterAbout", () => {
  it("zapisuje tekst razem z obecnym adresem", async () => {
    apiMock.put.mockResolvedValue({ data: {} });
    const field = renderAbout();
    expect(saveButton()).toBeDisabled();
    fireEvent.change(field, { target: { value: "  Rekrutuję w IT.  " } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(toast.showSuccess).toHaveBeenCalledWith("Zapisano „O mnie”."));
    expect(apiMock.put).toHaveBeenCalledWith("/api/me/career-link", {
      slug: "marta-n",
      about: "Rekrutuję w IT.",
    });
  });

  it("pokazuje znaleziska z odmowy serwera, a nie ogólny błąd", async () => {
    apiMock.put.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: {
            code: "CAREER_ABOUT_FINDINGS",
            message: "„O mnie” zawiera treści, których nie publikujemy",
            findings: [
              {
                code: "person_name",
                message:
                  "Wykryto nazwisko osoby: „Marta Kowalska” — na stronie podajemy wyłącznie imię rekrutera.",
                excerpt: "Marta Kowalska",
              },
            ],
          },
        },
      },
    });
    const field = renderAbout();
    fireEvent.change(field, { target: { value: "Jestem Marta Kowalska." } });
    fireEvent.click(saveButton());
    expect(await screen.findByText(/Wykryto nazwisko osoby/)).toBeInTheDocument();
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(toast.showSuccess).not.toHaveBeenCalled();
  });

  it("za długi tekst blokuje zapis i licznik to mówi", () => {
    const field = renderAbout("Rekrutuję w IT.");
    fireEvent.change(field, { target: { value: "a".repeat(ABOUT_MAX + 1) } });
    expect(screen.getByText(`${ABOUT_MAX + 1}/${ABOUT_MAX} znaków`)).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });
});
