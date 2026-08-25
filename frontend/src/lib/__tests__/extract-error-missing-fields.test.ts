import { describe, it, expect } from "vitest";
import { AxiosError, type AxiosResponse } from "axios";
import { extractErrorMsg } from "@/lib/api";

function axios409(detail: unknown): AxiosError {
  const err = new AxiosError("Request failed with status code 409");
  err.response = {
    status: 409,
    statusText: "Conflict",
    data: { detail },
    headers: {},
    config: {},
  } as unknown as AxiosResponse;
  return err;
}

/**
 * Lifecycle kontraktu zwraca 409 {message: "Missing required fields",
 * missing: [...]}. Do 2026-08-25 `extractErrorMsg` oddawał surowe `message`
 * i GUBIŁ listę pól — użytkownik formularza „Nowy kontrakt" widział goły
 * angielski banner bez wskazania, czego brakuje (zgłoszony bug: Jakub
 * Jedynak / CARDIF). Teraz nazwy pól tłumaczą się na etykiety formularza.
 */
describe("extractErrorMsg — 409 z listą brakujących pól", () => {
  it("tłumaczy missing[] na polskie etykiety pól", () => {
    const msg = extractErrorMsg(
      axios409({
        message: "Missing required fields",
        missing: ["end_date", "rate_candidate", "rate_client", "work_mode"],
      }),
    );
    expect(msg).toBe(
      "Uzupełnij brakujące pola: Data zakończenia, " +
        "Stawka kosztowa (kandydata), Stawka przychodowa (klienta), Tryb pracy",
    );
  });

  it("nieznane pole przechodzi surową nazwą (nie znika z listy)", () => {
    const msg = extractErrorMsg(
      axios409({ message: "Missing required fields", missing: ["nowe_pole"] }),
    );
    expect(msg).toBe("Uzupełnij brakujące pola: nowe_pole");
  });

  it("duplikat kontraktora oddaje polski komunikat backendu wprost", () => {
    const msg = extractErrorMsg(
      axios409({
        code: "duplicate_contractor",
        message:
          "Kontrakt dla tego kontraktora u klienta „CARDIF” już istnieje (e-mail: jakub@example.com).",
        existing_contract_id: 467,
      }),
    );
    expect(msg).toContain("już istnieje");
    expect(msg).toContain("jakub@example.com");
  });

  it("pusta lista missing nie przechwytuje zwykłego message", () => {
    const msg = extractErrorMsg(
      axios409({ message: "Inny konflikt domenowy", missing: [] }),
    );
    expect(msg).toBe("Inny konflikt domenowy");
  });
});
