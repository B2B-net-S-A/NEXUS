/**
 * Umowa zlecenia w Generatorze (26.10.2026): błędy pól przed wysłaniem,
 * ładunek do `/mandate/render` i pobranie DOCX z zapisem w rejestrze.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  renderMandateDocx: vi.fn(),
  renderMandateHtml: vi.fn(),
  downloadBlob: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {},
  b2bGeneratorApi: {
    renderMandateDocx: (...a: unknown[]) => mocks.renderMandateDocx(...a),
    renderMandateHtml: (...a: unknown[]) => mocks.renderMandateHtml(...a),
  },
}));

vi.mock("@/lib/cv-generator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/cv-generator")>();
  return { ...actual, downloadBlob: (...a: unknown[]) => mocks.downloadBlob(...a) };
});

import { ToastProvider } from "@/components/Toast";
import { MandateAgreementForm } from "@/components/v2/b2b-generator/MandateAgreementForm";

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MandateAgreementForm />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("MandateAgreementForm", () => {
  beforeEach(() => {
    mocks.renderMandateDocx.mockReset();
    mocks.renderMandateHtml.mockReset();
    mocks.downloadBlob.mockReset();
  });

  it("bez wymaganych pól nie wysyła i pokazuje, czego brakuje", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByRole("button", { name: /Pobierz DOCX/ }));
    expect(mocks.renderMandateDocx).not.toHaveBeenCalled();
    expect(screen.getByText("Wpisz imię i nazwisko.")).toBeInTheDocument();
    expect(screen.getByText("Podaj koniec zlecenia.")).toBeInTheDocument();
    expect(screen.getByText("Podaj stawkę brutto za godzinę.")).toBeInTheDocument();
    expect(
      screen.getByText("Wpisz co najmniej jedną czynność z § 1."),
    ).toBeInTheDocument();
  });

  it("wysyła ładunek zlecenia i pobiera plik z nazwą z serwera", async () => {
    mocks.renderMandateDocx.mockResolvedValue({
      data: new Blob(["docx"]),
      headers: {
        "content-disposition":
          'attachment; filename="Umowa zlecenia 27-10-2026 Testowa Anna.docx"',
      },
    });
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText("Imię i nazwisko *"), "Anna Testowa");
    await user.click(screen.getByRole("radio", { name: "Kobieta" }));
    expect(screen.getByLabelText("W narzędniku (z kim)")).toHaveValue("Anną Testową");
    const to = screen.getByLabelText("Zlecenie do *");
    await user.clear(to);
    await user.type(to, "2027-01-31");
    await user.type(screen.getByLabelText("Stawka brutto, zł/h *"), "45,50");
    await user.type(screen.getByLabelText("Czynność a"), "administracja platformą");
    await user.click(screen.getByRole("button", { name: /Dodaj czynność/ }));
    // Kursor przechodzi do nowego pola — pisanie trafia do czynności b).
    expect(screen.getByLabelText("Czynność b")).toHaveFocus();
    await user.keyboard("wsparcie wdrożeń");
    await user.click(
      screen.getByLabelText("Z umową powierzenia danych (DPA, Załącznik nr 2)"),
    );
    await user.click(screen.getByRole("button", { name: /Pobierz DOCX/ }));

    await waitFor(() => expect(mocks.renderMandateDocx).toHaveBeenCalledTimes(1));
    expect(mocks.renderMandateDocx.mock.calls[0][0]).toMatchObject({
      partner_name: "Anna Testowa",
      partner_instrumental: "Anną Testową",
      gender: "f",
      period_to: "2027-01-31",
      gross_hourly_rate: 45.5,
      tasks: ["administracja platformą", "wsparcie wdrożeń"],
      with_dpa: false,
      dpa_purpose: null,
      pesel: null,
      candidate_id: null,
      job_id: null,
    });
    await waitFor(() =>
      expect(mocks.downloadBlob).toHaveBeenCalledWith(
        expect.any(Blob),
        "Umowa zlecenia 27-10-2026 Testowa Anna.docx",
      ),
    );
    // Data zawarcia = dziś (Warszawa); etykieta jak wiersz rejestru.
    expect(
      await screen.findByText(/Zlecenie z dnia \d{2}\.\d{2}\.\d{4} pobrana/),
    ).toBeInTheDocument();
  });
});
