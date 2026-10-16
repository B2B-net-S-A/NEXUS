/**
 * Harness `/preview/cv-to-client` (PR 4 „CV w procesie”, 13.10.2026).
 *
 * Montuje całą stronę i sprawdza to, czego nie pokaże test karty z atrapami:
 * zasiew wystarcza panelowi „Z czego powstało” i liczbie rzeczy do sprawdzenia,
 * a jedyne zapytanie, które próbuje wyjść, to celowo niezasiane QC w stanie
 * „QC nie odpowiada” — i to zatrzymuje interceptor.
 *
 * Edytor CV 3, „Ekran 5” (14.10.2026): panel „Z czego powstało” jest zwinięty
 * do jednego zdania, a miniatura gotowego CV bierze przykładowy PDF harnessu
 * (plik z `public/`), nie API.
 */

import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  // Zwinięty panel: jedno zdanie, „Generuj” bez rozwijania.
  expect(await within(panel).findByTestId("cv-generate-summary")).toHaveTextContent(
    "Z oryginału CV, Championa, screeningu i notatek · Pod rekrutację · polski · Zmień",
  );
  await waitFor(() => expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeEnabled());
  fireEvent.click(within(panel).getByRole("button", { name: "Zmień" }));
  expect(within(panel).getByTestId("ai-source-original")).toHaveTextContent("Anna_Przykładowa_CV.pdf");
  expect(await within(panel).findByRole("switch", { name: "Transkrypty rozmów" })).not.toBeChecked();

  // „Wygeneruj ponownie”: zdanie z wyboru bieżącej wersji (z transkryptami).
  const again = screen.getByRole("region", { name: "„Wygeneruj ponownie” — wybór z ostatniej wersji" });
  expect(await within(again).findByTestId("cv-generate-summary")).toHaveTextContent(
    "Z oryginału CV, Championa, screeningu, notatek i transkryptów · Pod rekrutację · polski",
  );
  expect(again).toHaveTextContent("Nowa wersja zastąpi bieżący szkic");
  // Gotowe CV obok: miniatura pierwszej strony i menu „⋯” zamiast rzędu przycisków.
  expect(within(again).getByRole("button", { name: "Otwórz strony CV — Jan Kowalski" })).toBeInTheDocument();
  expect(within(again).getByRole("button", { name: "Więcej akcji CV" })).toBeInTheDocument();
  expect(within(again).getByRole("button", { name: /Pobierz Word/ })).toBeInTheDocument();

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

  // Po „Zapisz i przekaż dalej” (14.10.2026): postęp CV → QC i następna osoba.
  const forwarded = screen.getByRole("region", { name: "Po przekazaniu — CV się generuje" });
  const progress = await within(forwarded).findByTestId("cv-forward-progress");
  expect(progress).toHaveTextContent("Screening zapisany");
  expect(progress).toHaveTextContent("CV generuje się (ok. 40 s)");
  expect(progress).toHaveTextContent("QC — po CV");
  expect(progress).toHaveTextContent("Dam znać w ikonie „CV”, gdy CV będzie gotowe.");
  fireEvent.click(within(progress).getByRole("button", { name: /Następna w Screeningu: Kamil Przykładowy/ }));
  expect(screen.getByTestId("harness-opened")).toHaveTextContent("Kamil Przykładowy");

  const skipped = screen.getByRole("region", { name: "Po przekazaniu — automat pominął osobę" });
  expect(await within(skipped).findByTestId("cv-forward-progress")).toHaveTextContent(
    "CV nie powstało automatycznie: reguła klienta wymaga zrzutu zgody RODO",
  );

  // Nic nie wyszło z przeglądarki; próba sieci była tylko dla niezasianego QC,
  // a odczyty karty po przekazaniu (co 4 s) odpowiada pamięć harnessu.
  expect(sent).toEqual([]);
  const urls = attempts.mock.calls.map(([config]) => (config as { url?: string }).url ?? "");
  const memory = /^\/api\/(cv-generator\/generated|candidates\/stages\/\d+\/cv\/branded|jobs\/88\/background-events)$/;
  expect(urls.filter((url) => !memory.test(url)).every((url) => url === "/api/pipeline/stages/705/qc")).toBe(true);
});

it("po przekazaniu karta pyta pamięć harnessu, aż automat skończy CV — bez sieci", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    render(<CvToClientPreviewPage />);
    const forwarded = await screen.findByRole("region", { name: "Po przekazaniu — CV się generuje" });
    expect(await within(forwarded).findByTestId("cv-forward-progress")).toHaveTextContent("CV generuje się");
    await act(async () => {
      vi.advanceTimersByTime(12_500);
    });
    const progress = within(forwarded).getByTestId("cv-forward-progress");
    await waitFor(() => expect(progress).toHaveTextContent("CV gotowe"));
    await waitFor(() => expect(progress).toHaveTextContent("QC: 2 do poprawy"));
    expect(sent).toEqual([]);
  } finally {
    vi.useRealTimers();
  }
});

it("„Napisz od nowa” (Edytor CV 3, PR 5): uwaga, nowa wersja z Twoimi poprawkami i „Wróć do poprzedniej” — bez sieci", async () => {
  render(<CvToClientPreviewPage />);
  const card = await screen.findByRole("region", { name: "„Napisz od nowa” — Twoje poprawki zostają" });
  const form = await within(card).findByRole("form", { name: "Napisz od nowa" });
  fireEvent.change(within(form).getByRole("textbox", { name: "Co poprawić?" }), {
    target: { value: "krócej, więcej o Kafce" },
  });
  fireEvent.click(within(form).getByRole("button", { name: /Napisz od nowa/ }));

  const bar = await within(card).findByTestId("cv-rewrite-result", {}, { timeout: 10_000 });
  expect(bar).toHaveTextContent("Nowa wersja CV. „Logistyka Przykład” zostało w Twojej wersji.");
  fireEvent.click(within(bar).getByRole("button", { name: /Wróć do poprzedniej/ }));
  await waitFor(() => expect(within(card).queryByTestId("cv-rewrite-result")).toBeNull());
  expect(screen.getByText("Przywrócono poprzednią wersję CV.")).toBeInTheDocument();
  // Zapisy odpowiedziała pamięć harnessu — nic nie wyszło do sieci.
  expect(sent.filter((config) => (config.method ?? "get").toLowerCase() !== "get")).toEqual([]);
}, 20_000);
