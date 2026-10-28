import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProtocolSignForm, visibleBlocks, type PublicProtocol } from "../ProtocolSignForm";

const protocol: PublicProtocol = {
  number: "PZO/2026/10/014",
  kind: "wydanie",
  protocol_date: "2026-10-28",
  holder_name: "Anna Przykładowa",
  issuer_name: "Zofia Testowa",
  expires_at: "2026-11-11T10:00:00+00:00",
  total: "2 589,00",
  lines: [{ position: 1, name: "Laptop Dell", identifier: "TEST0001", value: "2589,00" }],
  document: [
    { type: "paragraph", text: "PROTOKÓŁ" },
    { type: "paragraph", text: "" },
    {
      type: "table",
      rows: [
        ["Lp.", "Nazwa sprzętu"],
        ["1", "Laptop Dell"],
      ],
    },
    { type: "paragraph", text: "                  Strona przekazująca\t\t\t    Strona przyjmująca" },
    { type: "paragraph", text: "(podpis)            \t        (podpis)" },
  ],
};

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("strona podpisu protokołu", () => {
  it("pokazuje treść bez linii podpisów do druku", () => {
    const blocks = visibleBlocks(protocol.document);
    expect(blocks.map((b) => b.text ?? "tabela")).toEqual(["PROTOKÓŁ", "tabela"]);
  });

  it("pomija też tabelkę podpisów ze wzoru standardowego", () => {
    const blocks = visibleBlocks([
      ...protocol.document,
      {
        type: "table",
        rows: [
          ["Strona przekazująca", "Strona przyjmująca"],
          ["Zofia Testowa", "Anna Przykładowa"],
          ["....", "...."],
          ["(podpis)\n", "(podpis)\n"],
        ],
      },
    ]);
    expect(blocks.map((b) => b.text ?? b.rows?.[0]?.[0])).toEqual(["PROTOKÓŁ", "Lp."]);
  });

  it("wysyła imię i nazwisko dopiero po zaznaczeniu zgody", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ status: "podpisany" }) });
    render(<ProtocolSignForm token="tok" protocol={protocol} />);

    const submit = screen.getByRole("button", { name: "Potwierdzam odbiór" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Imię i nazwisko"), "Anna Przykładowa");
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(submit);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("odbiór potwierdzony"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/public\/equipment-protocols\/tok\/sign$/);
    expect(JSON.parse(init.body)).toEqual({ signer_name: "Anna Przykładowa", accepted: true });
  });

  it("odmowa serwera pokazuje zdanie z odpowiedzi, a formularz zostaje", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Link nieprawidłowy lub wygasły." }),
    });
    render(<ProtocolSignForm token="tok" protocol={protocol} />);
    await userEvent.type(screen.getByLabelText("Imię i nazwisko"), "Anna Przykładowa");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Potwierdzam odbiór" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Link nieprawidłowy lub wygasły.");
    expect(screen.getByLabelText("Imię i nazwisko")).toHaveValue("Anna Przykładowa");
  });
});
