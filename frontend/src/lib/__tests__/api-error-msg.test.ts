import { describe, expect, it, vi } from "vitest";
import { AxiosError } from "axios";

import { extractErrorMsg } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

/** Minimal AxiosError carrying a response body + status. */
function axiosErrorWith(status: number, data: unknown): AxiosError {
  const err = new AxiosError("Request failed", "ERR_BAD_REQUEST");
  err.response = {
    status,
    statusText: "",
    data,
    headers: {},
    config: { headers: {} },
  } as AxiosError["response"];
  return err;
}

describe("extractErrorMsg — bramka ról (403)", () => {
  it("nie pokazuje użytkownikowi surowej listy ról z require_roles", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const raw =
      "Requires one of roles: ['admin', 'head_of_recruitment', 'delivery_lead', 'tac']";

    const msg = extractErrorMsg(axiosErrorWith(403, { detail: raw }));

    expect(msg).not.toContain("Requires one of roles");
    expect(msg).not.toContain("head_of_recruitment");
    expect(msg).toBe(
      "Nie masz uprawnień do tej operacji — poproś administratora o dostęp.",
    );
    // Surowy detail zostaje w konsoli — diagnostyka bez wycieku do UI.
    expect(spy).toHaveBeenCalledWith("[api] role gate:", raw);
    spy.mockRestore();
  });

  it("nie rusza innych komunikatów 403 (capability guards mają własne treści)", () => {
    const msg = extractErrorMsg(
      axiosErrorWith(403, { detail: "Kandydat objęty NDA — brak dostępu." }),
    );
    expect(msg).toBe("Kandydat objęty NDA — brak dostępu.");
  });

  it("nie tłumi tej samej treści przy innym statusie niż 403", () => {
    const raw = "Requires one of roles: ['admin']";
    expect(extractErrorMsg(axiosErrorWith(400, { detail: raw }))).toBe(raw);
  });

  it("zachowuje actionable komunikat walidacji z body", () => {
    const msg = extractErrorMsg(
      axiosErrorWith(422, {
        detail: [{ loc: ["body", "nip"], msg: "Field required" }],
      }),
    );
    expect(msg).toBe("nip: Field required");
  });
});

/**
 * Od 0410 trasy pytają o uprawnienia z ekranu Osoby i role, a odmowa nazywa
 * brakujące. Starsze bramki (sekcja, poziom akcji) odpowiadają samym kodem —
 * bez tłumaczenia użytkownik widział „Request failed with status code 403”.
 */
describe("extractErrorMsg — odmowy dostępu (403)", () => {
  const AXIOS_ENGLISH = "Request failed";

  it("pokazuje zdanie serwera z nazwą brakującego uprawnienia", () => {
    const message =
      "Brakuje Ci uprawnienia „Kontrakty i zamówienia: tworzenie i edycja”. Poproś administratora o dostęp.";
    const error = axiosErrorWith(403, {
      detail: {
        code: "permission_denied",
        permission: "contracts_orders_edit",
        label: "Kontrakty i zamówienia: tworzenie i edycja",
        permissions: ["contracts_orders_edit"],
        message,
      },
    });
    expect(extractErrorMsg(error)).toBe(message);
    expect(apiErrorMessage(error, "Nie udało się zapisać")).toBe(message);
  });

  it("finance_fields_forbidden: pokazuje nowe `message` z nazwą uprawnienia", () => {
    const message =
      "Brakuje Ci uprawnienia „Stawki i kwoty: zmiana”. Poproś administratora o dostęp.";
    expect(
      extractErrorMsg(
        axiosErrorWith(403, {
          detail: { code: "finance_fields_forbidden", fields: ["rate_client"], message },
        }),
      ),
    ).toBe(message);
  });

  it("finance_fields_forbidden bez `message` (starsza odpowiedź) dostaje zdanie po polsku, bez nazw ról", () => {
    const msg = extractErrorMsg(
      axiosErrorWith(403, {
        detail: { code: "finance_fields_forbidden", fields: ["rate_client"] },
      }),
    );
    expect(msg).toBe(
      "Nie masz uprawnienia do stawek i kwot — zapisz pozostałe pola bez nich. Poproś administratora o dostęp.",
    );
    expect(msg).not.toMatch(/admin(?!istrator)|Finanse|Delivery Lead/);
  });

  it.each([
    [
      "zapis przy samym podglądzie",
      { section: "delivery", required: "write", granted: "read" },
      "W części „Klienci, kontrakty i zamówienia” masz tylko podgląd — ta operacja wymaga uprawnienia do zmian. Poproś administratora o dostęp.",
    ],
    [
      "brak sekcji",
      { section: "finance", required: "read", granted: "none" },
      "Nie masz dostępu do części „Finanse”. Poproś administratora o dostęp.",
    ],
    [
      "zapis bez żadnego dostępu",
      { section: "pipeline", required: "write", granted: "none" },
      "Nie masz dostępu do części „Rekrutacje”. Poproś administratora o dostęp.",
    ],
    [
      "kilka sekcji do wyboru",
      { required: "read", any_section: ["sourcing", "pipeline"] },
      "Nie masz dostępu do tej części NEXUSA. Poproś administratora o dostęp.",
    ],
    [
      "nieznana sekcja",
      { section: "nowa_sekcja", required: "read", granted: "none" },
      "Nie masz dostępu do tej części NEXUSA. Poproś administratora o dostęp.",
    ],
  ])("section_access_denied — %s", (_label, extra, expected) => {
    const error = axiosErrorWith(403, {
      detail: { code: "section_access_denied", ...extra },
    });
    expect(extractErrorMsg(error)).toBe(expected);
    // Także wołający z własnym fallbackiem dostają zdanie o dostępie.
    expect(apiErrorMessage(error, "Nie udało się zapisać")).toBe(expected);
  });

  it("section_access_denied z `message` serwera (zapis w Delivery) pokazuje zdanie serwera", () => {
    // Bramka sekcji Delivery dokłada własne zdanie — wygrywa z lokalnym.
    const message =
      "Do tej operacji potrzebujesz uprawnienia do zmian w klientach, kontraktach albo zamówieniach. Poproś administratora o dostęp.";
    const error = axiosErrorWith(403, {
      detail: {
        code: "section_access_denied",
        section: "delivery",
        required: "write",
        granted: "read",
        message,
      },
    });
    expect(extractErrorMsg(error)).toBe(message);
    expect(apiErrorMessage(error, "Nie udało się zapisać")).toBe(message);
  });

  it.each([
    [
      "generator umów B2B",
      { action: "b2b_contract_generator", required: "generate", granted: "view" },
      "Twój poziom dostępu do Generatora umów B2B nie pozwala na tę operację. Poproś administratora o dostęp.",
    ],
    [
      "uprawnienie z ekranu Osoby i role",
      { action: "b2b_signature_confirmation", required: "manage" },
      "Brakuje Ci uprawnienia „Umowy B2B: oznaczanie jako podpisane”. Poproś administratora o dostęp.",
    ],
    [
      "nieznana akcja",
      { action: "cos_nowego", required: "manage" },
      "Nie masz uprawnienia do tej operacji. Poproś administratora o dostęp.",
    ],
  ])("action_access_denied — %s", (_label, extra, expected) => {
    expect(
      extractErrorMsg(
        axiosErrorWith(403, { detail: { code: "action_access_denied", ...extra } }),
      ),
    ).toBe(expected);
  });

  it("żadna z tych odmów nie kończy się angielskim komunikatem axiosa", () => {
    for (const code of [
      "section_access_denied",
      "action_access_denied",
      "finance_fields_forbidden",
    ]) {
      expect(extractErrorMsg(axiosErrorWith(403, { detail: { code } }))).not.toContain(
        AXIOS_ENGLISH,
      );
    }
  });

  it("nieznany kod bez `message` zostaje przy dotychczasowym zachowaniu", () => {
    const error = axiosErrorWith(409, { detail: { code: "cos_innego", ids: [1] } });
    expect(apiErrorMessage(error, "Nie zapisano")).toBe("Nie zapisano");
  });
});

describe("extractErrorMsg — strukturalny konflikt domenowy", () => {
  it("wyciąga detail.message z odpowiedzi zawierającej identyfikatory rekordów", () => {
    const msg = extractErrorMsg(
      axiosErrorWith(409, {
        detail: {
          message: "Istnieje więcej niż jeden pasujący kontrakt.",
          contract_ids: [91, 92],
        },
      }),
    );

    expect(msg).toBe("Istnieje więcej niż jeden pasujący kontrakt.");
  });
});

/**
 * Regresja: zgłoszenie Wiktorii Denki — „Pokazuje ten błąd - Request failed
 * with status code 429".
 *
 * slowapi odpowiada ciałem {"error": "Rate limit exceeded: N per 1 minute"} —
 * BEZ klucza `detail`, więc wołający spadali na surowe `error.message` axiosa
 * i użytkownik dostawał techniczny angielski string zamiast informacji, co
 * właściwie ma zrobić.
 */
describe("extractErrorMsg — limit zapytań (429)", () => {
  it("zamienia 429 na zrozumiałą instrukcję zamiast surowego komunikatu axiosa", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    const msg = extractErrorMsg(
      axiosErrorWith(429, { error: "Rate limit exceeded: 10 per 1 minute" }),
    );

    expect(msg).not.toContain("Request failed with status code");
    expect(msg).not.toContain("Rate limit exceeded");
    expect(msg).toBe(
      "Zbyt wiele prób w krótkim czasie — odczekaj minutę i spróbuj ponownie.",
    );
    spy.mockRestore();
  });

  it("działa też gdy 429 przyjdzie bez ciała (np. z warstwy proxy)", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const msg = extractErrorMsg(axiosErrorWith(429, ""));
    expect(msg).toContain("Zbyt wiele prób");
    spy.mockRestore();
  });
});
