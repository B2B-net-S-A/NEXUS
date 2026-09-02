/**
 * Pole zrzutu zgody RODO w generatorze CV (wymóg PKO BP).
 *
 * Trzy zachowania, których nie widać po samym renderze, a każde z nich cicho
 * kosztuje rekrutera CV do wyrzucenia:
 *
 * 1. Wgranie musi zwrócić rodzicowi KLUCZ z magazynu, nie plik — to on jedzie
 *    do generacji. Komponent, który zamontuje się i wygląda dobrze, ale nie
 *    zawoła `onChange`, daje przycisk „Generuj" bez zrzutu.
 * 2. Odrzucenie przez serwer (za duży plik, zły format) musi być WIDOCZNE
 *    i musi wyczyścić klucz. Cichy błąd znaczy „wgrałem", gdy nic nie wgrano.
 * 3. Za duży plik odsiewamy PRZED wysyłką — 8 MB przez sieć po to, żeby
 *    dostać 422, to strata czasu rekrutera na wolnym łączu.
 */
import * as React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { post: (...a: unknown[]) => mocks.post(...a) },
}));

vi.mock("@/lib/cv-generator", () => ({
  extractErrorDetail: async (e: unknown) =>
    (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
    "Błąd",
}));

import { ConsentScreenshotField } from "../ConsentScreenshotField";

function pngFile(name = "zgoda.png", size = 1024): File {
  const file = new File([new Uint8Array(size)], name, { type: "image/png" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("ConsentScreenshotField", () => {
  beforeEach(() => {
    mocks.post.mockReset();
  });

  it("po wgraniu oddaje rodzicowi klucz z magazynu, nie plik", async () => {
    mocks.post.mockResolvedValue({
      data: { storage_key: "zgody/abc.png", filename: "zgoda.png" },
    });
    const onChange = vi.fn();
    render(
      <ConsentScreenshotField value={null} onChange={onChange} required={false} />,
    );

    await userEvent.upload(
      screen.getByLabelText(/zrzut zgody/i),
      pngFile(),
    );

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith("zgody/abc.png", "zgoda.png"),
    );
  });

  it("odrzucenie przez serwer jest widoczne i czyści klucz", async () => {
    mocks.post.mockRejectedValue({
      response: { data: { detail: "Dozwolone formaty zrzutu: PNG, JPEG, WEBP." } },
    });
    const onChange = vi.fn();
    render(
      <ConsentScreenshotField value={null} onChange={onChange} required />,
    );

    await userEvent.upload(screen.getByLabelText(/zrzut zgody/i), pngFile());

    expect(
      await screen.findByText(/Dozwolone formaty zrzutu/i),
    ).toBeInTheDocument();
    // Klucz wyczyszczony — inaczej rodzic uznałby, że zrzut jest wgrany.
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(null, null));
  });

  it("za duży plik odpada lokalnie, bez wysyłki", async () => {
    const onChange = vi.fn();
    render(
      <ConsentScreenshotField value={null} onChange={onChange} required={false} />,
    );

    await userEvent.upload(
      screen.getByLabelText(/zrzut zgody/i),
      pngFile("wielki.png", 9 * 1024 * 1024),
    );

    expect(await screen.findByText(/za duży/i)).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("wymóg klienta jest widoczny w treści pola", () => {
    const { rerender } = render(
      <ConsentScreenshotField value={null} onChange={vi.fn()} required={false} />,
    );
    expect(screen.getByText(/Opcjonalnie/i)).toBeInTheDocument();

    rerender(
      <ConsentScreenshotField value={null} onChange={vi.fn()} required />,
    );
    expect(screen.getByText(/Ten klient wymaga/i)).toBeInTheDocument();
  });

  it("wgrany zrzut pokazuje nazwę pliku i daje go usunąć", async () => {
    const onChange = vi.fn();
    render(
      <ConsentScreenshotField
        value="zgody/abc.png"
        onChange={onChange}
        required
      />,
    );
    expect(screen.getByTestId("consent-screenshot-attached")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /usuń zrzut/i }));
    expect(onChange).toHaveBeenCalledWith(null, null);
  });
});
