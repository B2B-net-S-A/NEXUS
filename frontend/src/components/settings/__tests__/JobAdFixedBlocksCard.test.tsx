import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import type { FixedBlocks } from "@/lib/api/jobAd";

import JobAdFixedBlocksCard from "../JobAdFixedBlocksCard";

const BLOCKS: FixedBlocks = {
  title_suffix: "kmx",
  pl: {
    offer: ["prywatna opieka medyczna"],
    process: ["Rozmowa z rekruterem", "Rozmowa techniczna"],
    about: "Firma Przykładowa łączy specjalistów z projektami.",
  },
  en: { offer: ["private medical care"], process: ["Interview"], about: "We connect people." },
  pracuj_caretaker: { name: "", email: "ogloszenia@example.com" },
};

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobAdFixedBlocksCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.get.mockResolvedValue({ data: BLOCKS });
  apiMock.put.mockImplementation(async (_url: string, body: FixedBlocks) => ({ data: body }));
});

describe("JobAdFixedBlocksCard", () => {
  it("pokazuje zapisane bloki i podgląd z dopiskiem do tytułu", async () => {
    renderCard();
    expect(await screen.findByLabelText("Co oferujemy — w każdym ogłoszeniu")).toHaveValue(
      "prywatna opieka medyczna",
    );
    expect(screen.getByText("Starszy Programista Java (k/m/x)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
    expect(apiMock.get).toHaveBeenCalledWith("/api/job-ads/fixed-blocks");
  });

  it("zapisuje punkty jako listę — jedna pozycja w wierszu, bez pustych", async () => {
    renderCard();
    fireEvent.change(await screen.findByLabelText("Co oferujemy — w każdym ogłoszeniu"), {
      target: { value: "prywatna opieka medyczna\n\n  karta sportowa  \n" },
    });
    fireEvent.click(screen.getByRole("radio", { name: "bez dopisku" }));
    expect(screen.getByText("Starszy Programista Java")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
    expect(apiMock.put).toHaveBeenCalledWith("/api/job-ads/fixed-blocks", {
      ...BLOCKS,
      title_suffix: "none",
      pl: { ...BLOCKS.pl, offer: ["prywatna opieka medyczna", "karta sportowa"] },
    });
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith("Stałe części ogłoszenia zapisane."),
    );
  });

  it("opiekun Pracuj.pl zapisuje się razem z blokami, imię w jednej linii", async () => {
    renderCard();
    const email = await screen.findByLabelText("Adres e-mail");
    expect(email).toHaveValue("ogloszenia@example.com");
    fireEvent.change(screen.getByLabelText("Imię (do powitania)"), {
      target: { value: "  Nicola  " },
    });
    fireEvent.change(email, { target: { value: " opiekun@example.com " } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
    expect(apiMock.put).toHaveBeenCalledWith("/api/job-ads/fixed-blocks", {
      ...BLOCKS,
      pracuj_caretaker: { name: "Nicola", email: "opiekun@example.com" },
    });
  });

  it("serwer bez opiekuna (przed wdrożeniem) — pole ma skrzynkę ogłoszeń Pracuj.pl", async () => {
    const { pracuj_caretaker: _unused, ...older } = BLOCKS;
    apiMock.get.mockResolvedValue({ data: older });
    renderCard();
    expect(await screen.findByLabelText("Adres e-mail")).toHaveValue("ogloszenia@pracuj.pl");
  });

  it("bloki po angielsku edytuje się osobno", async () => {
    renderCard();
    await screen.findByLabelText("Jak wygląda proces");
    fireEvent.click(screen.getByRole("radio", { name: "Ogłoszenia po angielsku" }));
    expect(screen.getByLabelText("Jak wygląda proces")).toHaveValue("Interview");
    expect(screen.getByText("Senior Java Developer (f/m/x)")).toBeInTheDocument();
  });

  it("odmowa serwera (np. kwota w bloku) pokazuje jego komunikat i nie udaje zapisu", async () => {
    apiMock.put.mockRejectedValue({
      response: { status: 422, data: { detail: "Kwota w treści: „premia 500 zł”." } },
    });
    renderCard();
    fireEvent.change(await screen.findByLabelText("Co oferujemy — w każdym ogłoszeniu"), {
      target: { value: "premia 500 zł" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith("Kwota w treści: „premia 500 zł”."),
    );
    expect(toast.showSuccess).not.toHaveBeenCalled();
  });

  it("awaria wczytania nie pokazuje pustego formularza", async () => {
    apiMock.get.mockRejectedValue(new Error("500"));
    renderCard();
    expect(
      await screen.findByText("Nie udało się wczytać stałych części ogłoszenia"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz" })).not.toBeInTheDocument();
  });
});
