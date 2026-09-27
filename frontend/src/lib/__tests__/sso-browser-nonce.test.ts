import { beforeEach, describe, expect, it } from "vitest";
import { saveSsoBrowserNonce, takeSsoBrowserNonce } from "@/lib/sso-browser-nonce";

describe("sekret karty logowania Microsoft (R9-N1-4)", () => {
  beforeEach(() => window.sessionStorage.clear());

  it("oddaje zapisany sekret dokładnie raz", () => {
    saveSsoBrowserNonce("sekret-karty");
    expect(takeSsoBrowserNonce()).toBe("sekret-karty");
    expect(takeSsoBrowserNonce()).toBeNull();
  });

  it("brak sekretu z /authorize czyści poprzedni", () => {
    saveSsoBrowserNonce("stary");
    saveSsoBrowserNonce(undefined);
    expect(takeSsoBrowserNonce()).toBeNull();
  });
});
