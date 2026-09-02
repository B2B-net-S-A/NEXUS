import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  ClientCvRuleBanner,
  type ClientCvRule,
} from "@/components/v2/cv-generator/ClientCvRuleBanner";
import { makeCvRule } from "@/test/fixtures/cv-rule";

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

const ACTIVE: ClientCvRule = makeCvRule({
  seed_key: null,
  filename_preview: "B2B_Analityk_Jan Kowalski.docx",
});

describe("ClientCvRuleBanner", () => {
  it("pokazuje notatkę Delivery Leada tylko przy regule, która obowiązuje", () => {
    const { rerender } = render(
      <ClientCvRuleBanner
        clientId={1}
        rule={{ ...ACTIVE, notes: "CV bez zdjęcia. Maks. 3 rekomendacje." }}
        isLoading={false}
        isError={false}
      />,
    );
    expect(
      screen.getByText("Standardy klienta (notatka Delivery Leada)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("CV bez zdjęcia. Maks. 3 rekomendacje."),
    ).toBeInTheDocument();

    // Reguła niezatwierdzona nie obowiązuje — jej notatka też nie.
    rerender(
      <ClientCvRuleBanner
        clientId={1}
        rule={{
          ...ACTIVE,
          notes: "CV bez zdjęcia. Maks. 3 rekomendacje.",
          is_active: false,
          client_policy: "",
        }}
        isLoading={false}
        isError={false}
      />,
    );
    expect(
      screen.queryByText("CV bez zdjęcia. Maks. 3 rekomendacje."),
    ).not.toBeInTheDocument();
  });

  it("pokazuje instrukcje dla generatora, którymi model kształtował dokument", () => {
    render(
      <ClientCvRuleBanner
        clientId={1}
        rule={{
          ...ACTIVE,
          generator_instructions: "Bez sekcji zainteresowań. Opisy do 2 zdań.",
          client_policy: "nazwa pliku, język EN, instrukcje dla generatora",
        }}
        isLoading={false}
        isError={false}
      />,
    );
    expect(
      screen.getByText("Instrukcje dla generatora AI (zastosowane do treści)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Bez sekcji zainteresowań. Opisy do 2 zdań."),
    ).toBeInTheDocument();
  });

  it("mówi rekruterowi o zablokowanym trybie i automatycznej drugiej wersji", () => {
    render(
      <ClientCvRuleBanner
        clientId={1}
        rule={{
          ...ACTIVE,
          content_mode: "basic",
          content_mode_locked: true,
          requires_en_copy: true,
          auto_second_language: true,
        }}
        isLoading={false}
        isError={false}
      />,
    );
    expect(screen.getByText(/Tryb obróbki treści: Przepisanie/)).toBeInTheDocument();
    expect(
      screen.getByText(/druga wersja wygeneruje się automatycznie/),
    ).toBeInTheDocument();
  });

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
