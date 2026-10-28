/**
 * „Popraw protokół” i „Anuluj protokół” (decyzja Artura 28.10.2026): okno
 * wysyła tylko zmienione pola, ostrzega o wysłanym linku, po zapisie tworzy
 * nowy link; anulowanie wymaga powodu, błąd serwera idzie jako komunikat.
 * Dane fikcyjne — repo jest publiczne.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    patch: (...a: unknown[]) => patch(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { parseAmount } from "@/components/equipment/ProtocolCorrectionDialog";
import { ProtocolDialog } from "@/components/equipment/ProtocolDialog";
import { ProtocolsTab } from "@/components/equipment/ProtocolsTab";
import type { EquipmentProtocol } from "@/lib/api/equipment";

function protocol(overrides: Partial<EquipmentProtocol> = {}): EquipmentProtocol {
  return {
    id: 13,
    kind: "wydanie",
    number: "PZO/2026/10/013",
    protocol_date: "2026-10-27",
    holder: { kind: "user", id: 7, name: "Anna Przykładowa", email: "anna@example.com" },
    issuer_name: "Recepcja Testowa",
    total_value: "2639.00",
    status: "oczekuje",
    signature_method: "link",
    signed_at: null,
    signer_name: null,
    has_signed_file: false,
    confirmed_at: null,
    template_version: "std-1",
    created_at: "2026-10-27T09:00:00+00:00",
    link: {
      expires_at: "2026-11-10T09:00:00+00:00",
      used_at: null,
      created_at: "2026-10-27T09:00:00+00:00",
    },
    lines: [
      {
        position: 1,
        item_id: 1,
        category: "laptop",
        name: "Laptop Model Testowy (L-001) zasilacz",
        base_name: "Laptop Model Testowy (L-001)",
        accessories: "zasilacz",
        identifier: "TEST001",
        quantity: 1,
        unit_value: "2589.00",
        condition: null,
        notes: null,
      },
      {
        position: 2,
        item_id: 2,
        category: "karta_sim",
        name: "Karta SIM +48 500 000 001",
        base_name: "Karta SIM +48 500 000 001",
        accessories: "",
        identifier: "ICCID: TEST",
        quantity: 1,
        unit_value: null,
        condition: null,
        notes: null,
      },
    ],
    ...overrides,
  };
}

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  showToast.mockReset();
});

describe("parseAmount", () => {
  it("czyta polski zapis kwoty, puste = bez wartości, śmieci = błąd", () => {
    expect(parseAmount("2 589,50")).toBe("2589.50");
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("12,345")).toBeUndefined();
    expect(parseAmount("abc")).toBeUndefined();
  });
});

describe("Popraw protokół", () => {
  it("wysyła tylko zmienione pola i po zapisie tworzy nowy link", async () => {
    get.mockResolvedValue({ data: protocol() });
    patch.mockResolvedValue({ data: { ...protocol(), link: null, link_revoked: true } });
    post.mockResolvedValue({
      data: { url: "https://nexus.example/protocol/nowy-token", expires_at: "x", holder_email: null },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client()}>
        <ProtocolDialog protocolId={13} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "Popraw" }));
    const dialog = await screen.findByRole("dialog", { name: "Popraw protokół PZO/2026/10/013" });
    expect(dialog).toHaveTextContent("przestanie działać po zapisie");
    expect(dialog).toHaveTextContent("Tylko zapis w tym protokole. Nazwa konta się nie zmienia.");
    expect(dialog).toHaveTextContent("Pozycji nie dodaje się ani nie usuwa");
    // D6: karta SIM bez pola wartości.
    expect(within(dialog).queryByLabelText("Wartość, pozycja 2")).toBeNull();

    const name = within(dialog).getByLabelText("Imię i nazwisko w protokole");
    await user.clear(name);
    await user.type(name, "Anna Przykładowa-Nowak");
    const value = within(dialog).getByLabelText("Wartość, pozycja 1");
    await user.clear(value);
    await user.type(value, "1999,50");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz poprawki" }));

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch).toHaveBeenCalledWith("/api/equipment/protocols/13", {
      holder_name: "Anna Przykładowa-Nowak",
      lines: [{ position: 1, unit_value: "1999.50" }],
    });
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/equipment/protocols/13/link"));
    expect(await screen.findByLabelText("Link do podpisu")).toHaveValue(
      "https://nexus.example/protocol/nowy-token",
    );
    expect(showToast).toHaveBeenCalledWith("Poprawki zapisane", "success");
  });

  it("zła kwota zostaje w oknie z komunikatem, bez zapisu", async () => {
    get.mockResolvedValue({ data: protocol() });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client()}>
        <ProtocolDialog protocolId={13} onClose={vi.fn()} startCorrecting />
      </QueryClientProvider>,
    );
    const dialog = await screen.findByRole("dialog", { name: "Popraw protokół PZO/2026/10/013" });
    const value = within(dialog).getByLabelText("Wartość, pozycja 1");
    await user.clear(value);
    await user.type(value, "dużo");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz poprawki" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Pozycja 1: wpisz kwotę");
    expect(patch).not.toHaveBeenCalled();
  });

  it("podpisany protokół nie ma „Popraw”, ma „Anuluj protokół…”", async () => {
    get.mockResolvedValue({
      data: protocol({ status: "podpisany", signed_at: "2026-10-27T10:00:00+00:00" }),
    });
    render(
      <QueryClientProvider client={client()}>
        <ProtocolDialog protocolId={13} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: "Anuluj protokół…" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Popraw" })).toBeNull();
  });
});

describe("Anuluj protokół", () => {
  it("z okna poprawki: pyta o powód i wysyła go", async () => {
    get.mockResolvedValue({ data: protocol() });
    post.mockResolvedValue({ data: protocol({ status: "anulowany" }) });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client()}>
        <ProtocolDialog protocolId={13} onClose={vi.fn()} startCorrecting />
      </QueryClientProvider>,
    );
    const dialog = await screen.findByRole("dialog", { name: "Popraw protokół PZO/2026/10/013" });
    await user.click(within(dialog).getByRole("button", { name: "Anuluj protokół…" }));

    const ask = await screen.findByRole("dialog", { name: "Anulować protokół PZO/2026/10/013?" });
    expect(ask).toHaveTextContent("Sprzęt z protokołu wróci na stan");
    const confirm = within(ask).getByRole("button", { name: "Anuluj protokół" });
    expect(confirm).toBeDisabled();
    await user.type(within(ask).getByLabelText("Powód anulowania"), "  Ćwiczenie recepcji ");
    await user.click(confirm);

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/equipment/protocols/13/cancel", {
        reason: "Ćwiczenie recepcji",
      }),
    );
    expect(showToast).toHaveBeenCalledWith("Protokół PZO/2026/10/013 anulowany", "success");
  });

  it("z ⋯ wiersza listy: błąd serwera idzie jako komunikat", async () => {
    get.mockResolvedValue({ data: { items: [protocol({ status: "podpisany" })] } });
    post.mockRejectedValue(
      Object.assign(new Error("409"), {
        isAxiosError: true,
        response: { status: 409, data: { detail: "Protokół jest już potwierdzony — anulowanie niemożliwe." } },
      }),
    );
    const onCorrect = vi.fn();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client()}>
        <ProtocolsTab onOpenProtocol={vi.fn()} onCorrectProtocol={onCorrect} />
      </QueryClientProvider>,
    );
    await user.click(
      await screen.findByRole("button", { name: "Więcej akcji: PZO/2026/10/013" }),
    );
    // Podpisanego się nie poprawia.
    expect(screen.queryByRole("menuitem", { name: "Popraw…" })).toBeNull();
    await user.click(screen.getByRole("menuitem", { name: "Anuluj protokół…" }));
    const ask = await screen.findByRole("dialog", { name: "Anulować protokół PZO/2026/10/013?" });
    await user.type(within(ask).getByLabelText("Powód anulowania"), "Pomyłka");
    await user.click(within(ask).getByRole("button", { name: "Anuluj protokół" }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "Protokół jest już potwierdzony — anulowanie niemożliwe.",
        "error",
      ),
    );
  });

  it("⋯ wiersza „Popraw…” tylko przed podpisem", async () => {
    get.mockResolvedValue({ data: { items: [protocol()] } });
    const onCorrect = vi.fn();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client()}>
        <ProtocolsTab onOpenProtocol={vi.fn()} onCorrectProtocol={onCorrect} />
      </QueryClientProvider>,
    );
    await user.click(
      await screen.findByRole("button", { name: "Więcej akcji: PZO/2026/10/013" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Popraw…" }));
    expect(onCorrect).toHaveBeenCalledWith(13);
  });
});
