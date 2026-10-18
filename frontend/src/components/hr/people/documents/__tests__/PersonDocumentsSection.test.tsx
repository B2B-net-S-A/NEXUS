/**
 * Kartoteka → „Dokumenty” (e-teczka, E4). Sekcja chowa się przy 403/404
 * (przełożony, zespół) i gdy jest wyłączona; awaria to blok błędu, nie pusta
 * lista. Kadry wgrywają: domyślny krąg idzie za rodzajem, oświadczenie
 * studenta bez „ważny do” nie wychodzi do serwera, a wynik zasilenia kartoteki
 * wraca zdaniem. Usunięcie wymaga powodu. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, patch: mocks.patch, put: mocks.put },
}));

// Lista wyboru Radix w jsdom: brak API przechwytywania wskaźnika.
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}
if (!Element.prototype.scrollIntoView) {
  Object.assign(Element.prototype, { scrollIntoView: () => undefined });
}

import { CELINA, emptyView, hrView, personView } from "@/app/preview/hr-documents/fixtures";
import { ToastProvider } from "@/components/Toast";
import { documentKeys, type PersonDocuments } from "@/lib/api/hr-documents";

import { PersonDocumentsSection } from "../PersonDocumentsSection";

vi.setConfig({ testTimeout: 20_000 });

function wrap(node: React.ReactNode, data?: PersonDocuments) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  if (data) client.setQueryData(documentKeys.person(CELINA.id), data);
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

const section = (enabled = true) => (
  <PersonDocumentsSection userId={CELINA.id} name={CELINA.name} enabled={enabled} />
);

afterEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

describe("PersonDocumentsSection", () => {
  it("wyłączona sekcja nie pyta serwera", () => {
    wrap(section(false));
    expect(mocks.get).not.toHaveBeenCalled();
    expect(screen.queryByText("Dokumenty")).toBeNull();
  });

  it("404 z serwera (przełożony) chowa sekcję", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 404 } }));
    wrap(section());
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Wczytywanie…")).toBeNull());
    expect(screen.queryByText("Dokumenty")).toBeNull();
  });

  it("awaria serwera to błąd z ponowieniem, nie pusta e-teczka", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 500 } }));
    wrap(section());
    expect(await screen.findByText("Nie udało się wczytać dokumentów.")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma jeszcze dokumentów/)).toBeNull();
  });

  it("osoba widzi swoje dokumenty bez przycisków zmian", () => {
    wrap(section(), personView());
    expect(screen.getByText("Umowa zlecenia z 01.03.2026")).toBeInTheDocument();
    expect(screen.getByText("bezterminowo")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Wgraj dokument/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Zmień:/ })).toBeNull();
  });

  it("Kadry: umowy z generatora nie da się usunąć ręcznie", () => {
    wrap(section(), hrView());
    expect(screen.getByRole("button", { name: "Usuń: Oświadczenie studenta" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usuń: Umowa zlecenia z 01.03.2026" })).toBeNull();
    expect(screen.getByRole("button", { name: "Zmień: Umowa zlecenia z 01.03.2026" })).toBeInTheDocument();
  });

  it("wgranie: krąg za rodzajem, oświadczenie studenta wymaga daty, wynik kartoteki zdaniem", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({
      data: {
        document: { ...personView().documents[0], id: 9999 },
        profile_sync: { status: "updated", until: "2027-06-30" },
      },
    });
    wrap(section(), emptyView());
    await user.click(screen.getByRole("button", { name: /Wgraj dokument/ }));
    const dialog = await screen.findByRole("dialog");

    const file = new File(["%PDF-1.4"], "oswiadczenie.pdf", { type: "application/pdf" });
    await user.upload(within(dialog).getByLabelText(/Plik dokumentu/, { selector: "input" }), file);
    await user.click(within(dialog).getByRole("combobox", { name: "Rodzaj" }));
    await user.click(await screen.findByRole("option", { name: "oświadczenie" }));
    await user.type(within(dialog).getByLabelText("Tytuł"), "Oświadczenie studenta");
    await user.click(within(dialog).getByRole("checkbox", { name: /statusie ucznia/ }));
    await user.click(within(dialog).getByRole("button", { name: "Wgraj dokument" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("ważny do");
    expect(mocks.post).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText("Ważny do"), "2027-06-30");
    await user.click(within(dialog).getByRole("button", { name: "Wgraj dokument" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, form] = mocks.post.mock.calls[0] as [string, FormData];
    expect(url).toBe(`/api/hr/documents/people/${CELINA.id}`);
    expect(form.get("kind")).toBe("statement");
    expect(form.get("purpose")).toBe("student_status");
    expect(form.get("valid_until")).toBe("2027-06-30");
    // Oświadczenie: osoba i Płace, bez recepcji (domyślny krąg rodzaju).
    expect(form.get("visible_to_person")).toBe("true");
    expect(form.get("visible_to_payroll")).toBe("true");
    expect(form.get("visible_to_equipment")).toBe("false");
    expect(await screen.findByText(/Płace dostaną przypomnienie 30 dni wcześniej/)).toBeInTheDocument();
  });

  it("usunięcie pomyłki wymaga powodu", async () => {
    const user = userEvent.setup();
    mocks.post.mockResolvedValue({ data: { id: 7003, deleted: true } });
    wrap(section(), hrView());
    await user.click(screen.getByRole("button", { name: "Usuń: Oświadczenie studenta" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Usuń dokument" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("dlaczego");
    expect(mocks.post).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText("Powód"), "Wgrany do złej osoby");
    await user.click(within(dialog).getByRole("button", { name: "Usuń dokument" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/documents/7003/remove", {
        note: "Wgrany do złej osoby",
      }),
    );
  });
});
