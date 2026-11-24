import { afterEach, describe, expect, it, vi } from "vitest";

import {
  instrumentalPl,
  PREVIEW_STYLE,
  printHtml,
} from "@/lib/b2b-agreement-preview";

describe("instrumentalPl — narzędnik imienia i nazwiska", () => {
  it("puste, same spacje i undefined dają pusty napis", () => {
    expect(instrumentalPl("", "m")).toBe("");
    expect(instrumentalPl("   ", "k")).toBe("");
    expect(instrumentalPl(undefined as unknown as string, "m")).toBe("");
  });

  it("kobieta: -ska/-cka/-dzka i -a → -ą, spółgłoska nieodmienna", () => {
    expect(instrumentalPl("Anna Przykładowska", "k")).toBe("Anną Przykładowską");
    expect(instrumentalPl("ewa testowicka", "k")).toBe("Ewą Testowicką");
    expect(instrumentalPl("Ola Próbodzka", "k")).toBe("Olą Próbodzką");
    expect(instrumentalPl("Anna Przykładowa", "k")).toBe("Anną Przykładową");
    expect(instrumentalPl("Agnes Testlik", "k")).toBe("Agnes Testlik");
  });

  it("mężczyzna: -ski/-cki/-dzki → -im, -y → -ym", () => {
    expect(instrumentalPl("Jan Testowski", "m")).toBe("Janem Testowskim");
    expect(instrumentalPl("Jan Próbecki", "m")).toBe("Janem Próbeckim");
    expect(instrumentalPl("Jan Wzorodzki", "m")).toBe("Janem Wzorodzkim");
    expect(instrumentalPl("Jan Testowy", "m")).toBe("Janem Testowym");
  });

  it("mężczyzna: -ek → -kiem, -eł → -łem, -k/-g → +iem, -a → -ą", () => {
    expect(instrumentalPl("Jan Próbek", "m")).toBe("Janem Próbkiem");
    expect(instrumentalPl("Jan Wzorzeł", "m")).toBe("Janem Wzorzłem");
    expect(instrumentalPl("Jan Testak", "m")).toBe("Janem Testakiem");
    expect(instrumentalPl("Jan Testog", "m")).toBe("Janem Testogiem");
    expect(instrumentalPl("Kuba Testowa", "m")).toBe("Kubą Testową");
  });

  it("mężczyzna: -o/-i/-e/-u zostają bez zmian, reszta +em", () => {
    expect(instrumentalPl("Jan Testko", "m")).toBe("Janem Testko");
    expect(instrumentalPl("Jan Testini", "m")).toBe("Janem Testini");
    expect(instrumentalPl("Jan Testinie", "m")).toBe("Janem Testinie");
    expect(instrumentalPl("Jan Testiu", "m")).toBe("Janem Testiu");
    expect(instrumentalPl("JAN TESTOWICZ", "m")).toBe("Janem Testowiczem");
  });

  it("wielokrotne spacje między słowami nie dają pustych tokenów", () => {
    expect(instrumentalPl("  Jan    Testowy  ", "m")).toBe("Janem Testowym");
  });
});

describe("printHtml — wydruk podglądu", () => {
  afterEach(() => vi.restoreAllMocks());

  it("zablokowany popup (window.open = null) nie rzuca", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    expect(() => printHtml("<p>x</p>", "Umowa")).not.toThrow();
  });

  it("pisze dokument z tytułem i treścią, potem zamyka strumień", () => {
    const write = vi.fn();
    const close = vi.fn();
    vi.spyOn(window, "open").mockReturnValue({
      document: { write, close },
    } as unknown as Window);
    printHtml("<h1>Umowa B2B</h1>", "Umowa — Jan Testowy");
    expect(write).toHaveBeenCalledTimes(1);
    const html = write.mock.calls[0][0] as string;
    expect(html).toContain("<title>Umowa — Jan Testowy</title>");
    expect(html).toContain("<body><h1>Umowa B2B</h1></body>");
    expect(html).toContain("window.print()");
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("styl podglądu chroni nagłówki przed zostaniem na końcu strony", () => {
    expect(PREVIEW_STYLE).toContain("break-after:avoid");
  });
});
