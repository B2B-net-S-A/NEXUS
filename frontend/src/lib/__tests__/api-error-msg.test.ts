import { describe, expect, it, vi } from "vitest";
import { AxiosError } from "axios";

import { extractErrorMsg } from "@/lib/api";

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
