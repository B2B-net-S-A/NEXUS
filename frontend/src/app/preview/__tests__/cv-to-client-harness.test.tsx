/**
 * Harness `/preview/cv-to-client` (PR 4 „CV w procesie”, 13.10.2026).
 *
 * Montuje całą stronę i sprawdza to, czego nie pokaże test karty z atrapami:
 * zasiew wystarcza panelowi „Z czego powstało” i liczbie rzeczy do sprawdzenia,
 * a jedyne zapytanie, które próbuje wyjść, to celowo niezasiane QC w stanie
 * „QC nie odpowiada” — i to zatrzymuje interceptor.
 */

import { configure, render, screen, waitFor, within } from "@testing-library/react";
import { Axios, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import CvToClientPreviewPage from "../cv-to-client/page";

configure({ asyncUtilTimeout: 5000 });

const sent: InternalAxiosRequestConfig[] = [];
const attempts = vi.spyOn(Axios.prototype, "request");

beforeAll(() => {
  const adapter: AxiosAdapter = async (config) => {
    sent.push(config);
    return { data: {}, status: 200, statusText: "OK", headers: {}, config } as AxiosResponse;
  };
  api.defaults.adapter = adapter;
});

afterEach(() => {
  sent.length = 0;
  attempts.mockClear();
});

it("pokazuje panel „Z czego powstało” i jedną liczbę rzeczy do sprawdzenia bez sieci", async () => {
  render(<CvToClientPreviewPage />);

  const fresh = await screen.findByRole("region", { name: "Brak CV — „Generuj CV” w karcie" });
  const panel = await within(fresh).findByTestId("cv-generate-panel");
  expect(within(panel).getByTestId("ai-source-original")).toHaveTextContent("Anna_Przykładowa_CV.pdf");
  expect(await within(panel).findByRole("switch", { name: "Transkrypty rozmów" })).not.toBeChecked();
  await waitFor(() => expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeEnabled());

  // „Wygeneruj ponownie”: przełączniki z wyboru bieżącej wersji.
  const again = screen.getByRole("region", { name: "„Wygeneruj ponownie” — wybór z ostatniej wersji" });
  expect(await within(again).findByRole("switch", { name: "Transkrypty rozmów" })).toBeChecked();
  expect(again).toHaveTextContent("Nowa wersja zastąpi bieżący szkic");

  // 1 blokada + 1 uwaga QC + 1 uwaga generatora + 1 kontrola AI (dubel o Kafce i wyciszona — nie).
  const counter = screen.getByRole("region", { name: "Jedna liczba rzeczy do sprawdzenia" });
  expect(await within(counter).findByTestId("cv-checks-count")).toHaveTextContent(
    "4 rzeczy do sprawdzenia przed wysłaniem",
  );
  expect(within(counter).getByRole("button", { name: /Sprawdź i popraw/ })).toBeInTheDocument();

  const clean = screen.getByRole("region", { name: "Gotowe, nic do sprawdzenia" });
  expect(await within(clean).findByTestId("cv-checks-count")).toHaveTextContent("Nic do sprawdzenia przed wysłaniem");

  const down = screen.getByRole("region", { name: "QC nie odpowiada" });
  expect(await within(down).findByText(/Nie udało się policzyć rzeczy do sprawdzenia/)).toBeInTheDocument();

  // Nic nie wyszło z przeglądarki; próba była tylko dla niezasianego QC.
  expect(sent).toEqual([]);
  const urls = attempts.mock.calls.map(([config]) => (config as { url?: string }).url);
  expect(urls.every((url) => url === "/api/pipeline/stages/705/qc")).toBe(true);
});
