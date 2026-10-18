/**
 * `/preview/hr-documents` (e-teczka, etap 5, E4): prawdziwe komponenty na
 * danych fikcyjnych, ZERO prób żądania — także po otwarciu okna wgrania.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-documents",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrDocumentsPreviewPage from "../hr-documents/page";

vi.setConfig({ testTimeout: 20_000 });

/** Każda PRÓBA żądania, także odrzucona przez interceptor harnessu. */
const attempts = vi.spyOn(Axios.prototype, "request");
const attempted = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

afterEach(() => {
  attempts.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/hr-documents", () => {
  it("Kadry: dokumenty, protokół jako odnośnik, ślad pomyłki i okno wgrania", async () => {
    window.history.replaceState({}, "", "/preview/hr-documents");
    render(<HrDocumentsPreviewPage />);
    expect(await screen.findByText("Umowa zlecenia z 01.03.2026")).toBeInTheDocument();
    expect(screen.getByText("Protokół wydania sprzętu PZO/2026/10/004")).toBeInTheDocument();
    expect(screen.getByText("usunięty")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Wgraj dokument/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Kto widzi")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("osoba: swoje dokumenty bez przycisków zmian", async () => {
    window.history.replaceState({}, "", "/preview/hr-documents?state=person");
    render(<HrDocumentsPreviewPage />);
    expect(await screen.findByText("Oświadczenie studenta")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Wgraj dokument/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Usuń:/ })).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("Płace: bez protokołów sprzętu", async () => {
    window.history.replaceState({}, "", "/preview/hr-documents?state=payroll");
    render(<HrDocumentsPreviewPage />);
    expect(await screen.findByText("Umowa zlecenia z 01.03.2026")).toBeInTheDocument();
    expect(screen.queryByText(/PZO\/2026/)).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("Kadry: lista po terminie przechowywania i okresy", async () => {
    window.history.replaceState({}, "", "/preview/hr-documents?state=retention");
    render(<HrDocumentsPreviewPage />);
    expect(await screen.findByText("Dokumenty po terminie przechowywania")).toBeInTheDocument();
    expect(screen.getByText("Borys Wzorcowy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Usuń zaznaczone \(0\)/ })).toBeDisabled();
    expect(attempted()).toEqual([]);
  });
});
