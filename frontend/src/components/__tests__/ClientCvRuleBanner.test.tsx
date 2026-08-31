import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  ClientCvRuleBanner,
  type ClientCvRule,
} from "@/components/v2/cv-generator/ClientCvRuleBanner";

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));

/**
 * Trzy stany banera są celowo rozróżnione i łatwo je zlać w jeden.
 *
 * Najkosztowniejsza pomyłka to potraktowanie „klient bez ZATWIERDZONYCH reguł"
 * jak „reguły działają": niewłączona reguła jest inaczej niewidoczna —
 * generacja „działa", a plik dostaje nazwę, której klient nie akceptuje,
 * i wychodzi to dopiero u odbiorcy CV.
 */

const ACTIVE: ClientCvRule = {
  client_id: 1,
  client_name: "Nordea Bank Abp",
  filename_pattern: "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
  spaces_to_underscores: false,
  cv_language: "en",
  requires_en_copy: false,
  requires_rodo_consent_block: false,
  notes: null,
  seed_key: null,
  confirmed_at: "2026-08-31T10:00:00Z",
  confirmed_by_name: "Artur",
  is_active: true,
  client_policy: "nazwa pliku, język EN",
  filename_preview: "B2B_Analityk_Jan Kowalski.docx",
};

describe("ClientCvRuleBanner", () => {
  it("nie renderuje nic, gdy klient nie jest wybrany", () => {
    const { container } = render(
      <ClientCvRuleBanner
        clientId={null}
        rule={undefined}
        isLoading={false}
        isError={false}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("ostrzega, gdy klient nie ma ZATWIERDZONYCH reguł", () => {
    render(
      <ClientCvRuleBanner
        clientId={3}
        rule={{ ...ACTIVE, is_active: false, client_policy: "" }}
        isLoading={false}
        isError={false}
      />,
    );
    expect(
      screen.getByText(/nie ma jeszcze zatwierdzonych reguł/i),
    ).toBeInTheDocument();
    // Niezatwierdzona reguła NIE MOŻE twierdzić, że cokolwiek zastosowano.
    expect(screen.queryByText(/Zastosowano reguły klienta/i)).toBeNull();
  });

  it("pokazuje zastosowane reguły i podgląd nazwy pliku", () => {
    render(
      <ClientCvRuleBanner
        clientId={1}
        rule={ACTIVE}
        isLoading={false}
        isError={false}
      />,
    );
    expect(screen.getByText(/Zastosowano reguły klienta/i)).toBeInTheDocument();
    expect(
      screen.getByText("B2B_Analityk_Jan Kowalski.docx"),
    ).toBeInTheDocument();
  });

  it("awaria odczytu wygląda inaczej niż brak reguł", () => {
    render(
      <ClientCvRuleBanner
        clientId={1}
        rule={undefined}
        isLoading={false}
        isError
      />,
    );
    expect(
      screen.getByText(/Nie udało się sprawdzić reguł CV/i),
    ).toBeInTheDocument();
    // Cisza po błędzie czytałaby się jak fakt („ten klient nie ma reguł").
    expect(screen.queryByText(/nie ma jeszcze zatwierdzonych reguł/i)).toBeNull();
  });

  it("przypomina o wersji EN i o zgodzie RODO, gdy klient ich wymaga", () => {
    render(
      <ClientCvRuleBanner
        clientId={2}
        rule={{
          ...ACTIVE,
          cv_language: null,
          requires_en_copy: true,
          requires_rodo_consent_block: true,
        }}
        isLoading={false}
        isError={false}
      />,
    );
    expect(screen.getByText(/oraz/i)).toBeInTheDocument();
    expect(screen.getByText(/zrzut ekranu maila/i)).toBeInTheDocument();
  });
});
