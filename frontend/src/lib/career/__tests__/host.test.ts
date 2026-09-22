import { describe, expect, it } from "vitest";

import {
  careerBase,
  careerHosts,
  careerHref,
  careerMetadataBase,
  careerVisibleUrl,
  isCareerHost,
  normalizeHost,
  requestDisplayHost,
  requestHost,
  requestOrigin,
  resolveCareerRoute,
} from "@/lib/career/host";

describe("hosty kariery", () => {
  it("normalizuje nagłówek hosta: pierwszy wpis, małe litery, bez portu", () => {
    expect(normalizeHost("Kariera.Dynaminds.pl:443")).toBe("kariera.dynaminds.pl");
    expect(normalizeHost("kariera.dynaminds.pl, proxy.local")).toBe("kariera.dynaminds.pl");
    expect(normalizeHost("[::1]:3000")).toBe("[::1]");
    expect(normalizeHost(null)).toBe("");
  });

  it("czyta listę z env (także z protokołem i ukośnikiem)", () => {
    expect(careerHosts("https://kariera.dynaminds.pl/, kariera.example.test")).toEqual([
      "kariera.dynaminds.pl",
      "kariera.example.test",
    ]);
    expect(careerHosts("")).toEqual([]);
    expect(careerHosts(undefined)).toEqual([]);
  });

  it("pusty host nigdy nie jest hostem kariery", () => {
    expect(isCareerHost("", [""])).toBe(false);
    expect(isCareerHost("nexus.dynaminds.pl", ["kariera.dynaminds.pl"])).toBe(false);
    expect(isCareerHost("KARIERA.dynaminds.pl:8443", ["kariera.dynaminds.pl"])).toBe(true);
  });

  it("x-forwarded-host ma pierwszeństwo przed host", () => {
    const h = new Headers({ host: "frontend:3000", "x-forwarded-host": "kariera.dynaminds.pl" });
    expect(requestHost(h)).toBe("kariera.dynaminds.pl");
    expect(requestHost(new Headers({ host: "nexus.dynaminds.pl" }))).toBe("nexus.dynaminds.pl");
  });
});

describe("resolveCareerRoute", () => {
  it.each([
    ["/", { kind: "rewrite", path: "/kariera" }],
    ["/rodo", { kind: "rewrite", path: "/kariera/rodo" }],
    ["/r/java-dev-ab12", { kind: "rewrite", path: "/kariera/r/java-dev-ab12" }],
    ["/marta-n", { kind: "rewrite", path: "/kariera/p/marta-n" }],
    ["/kariera/p/marta-n/opengraph-image", { kind: "pass" }],
    ["/r/-zly-", { kind: "not-found" }],
    ["/-marta", { kind: "not-found" }],
    ["/m", { kind: "not-found" }],
    [`/${"a".repeat(41)}`, { kind: "not-found" }],
    ["/candidates/1", { kind: "not-found" }],
    ["/r/%2e%2e", { kind: "not-found" }],
  ])("%s", (path, expected) => {
    expect(resolveCareerRoute(path)).toEqual(expected);
  });
});

describe("careerHref", () => {
  it("na hoście kariery linkuje adresami widocznymi", () => {
    const base = careerBase(true);
    expect(careerHref(base, { to: "job", slug: "java-ab12" })).toBe("/r/java-ab12");
    expect(careerHref(base, { to: "recruiter", slug: "marta-n" })).toBe("/marta-n");
    expect(careerHref(base, { to: "rodo" })).toBe("/rodo");
    expect(careerHref(base, { to: "home" })).toBe("/");
  });

  it("w NEXUSIE (dev, podgląd) linkuje trasami /kariera/*", () => {
    const base = careerBase(false);
    expect(careerHref(base, { to: "job", slug: "java-ab12" })).toBe("/kariera/r/java-ab12");
    expect(careerHref(base, { to: "recruiter", slug: "marta-n" })).toBe("/kariera/p/marta-n");
    expect(careerHref(base, { to: "rodo" })).toBe("/kariera/rodo");
    expect(careerHref(base, { to: "home" })).toBe("/kariera");
  });
});

describe("adresy z nagłówków żądania (metadataBase, stopka, grafika OG)", () => {
  const h = (values: Record<string, string>) => ({
    get: (name: string) => values[name.toLowerCase()] ?? null,
  });

  it("pochodzenie z x-forwarded-proto/x-forwarded-host ma pierwszeństwo przed host", () => {
    const headers = h({
      host: "localhost:3000",
      "x-forwarded-host": "kariera.dynaminds.pl",
      "x-forwarded-proto": "https",
    });
    expect(requestOrigin(headers)).toBe("https://kariera.dynaminds.pl");
    expect(careerMetadataBase(headers)?.href).toBe("https://kariera.dynaminds.pl/");
  });

  it("bez x-forwarded-proto: https dla domeny, http dla localhost", () => {
    expect(requestOrigin(h({ host: "nexus.dynaminds.pl" }))).toBe("https://nexus.dynaminds.pl");
    expect(requestOrigin(h({ host: "localhost:3000" }))).toBe("http://localhost:3000");
  });

  it("brak hosta = brak metadataBase (nie zgadujemy domeny)", () => {
    expect(requestOrigin(h({}))).toBeNull();
    expect(careerMetadataBase(h({}))).toBeUndefined();
  });

  it("host widoczny zachowuje port dev, ale nie domyślny", () => {
    expect(requestDisplayHost(h({ host: "localhost:3000" }))).toBe("localhost:3000");
    expect(requestDisplayHost(h({ "x-forwarded-host": "Kariera.Dynaminds.pl:443" }))).toBe(
      "kariera.dynaminds.pl",
    );
  });

  it("adres widoczny: bez prefiksu na hoście kariery, z /kariera/p i /kariera/r na hoście aplikacji", () => {
    expect(careerVisibleUrl("kariera.dynaminds.pl", "", { to: "recruiter", slug: "marta-n" })).toBe(
      "kariera.dynaminds.pl/marta-n",
    );
    expect(careerVisibleUrl("kariera.dynaminds.pl", "", { to: "job", slug: "java-ab12" })).toBe(
      "kariera.dynaminds.pl/r/java-ab12",
    );
    expect(
      careerVisibleUrl("nexus.dynaminds.pl", "/kariera", { to: "recruiter", slug: "marta-n" }),
    ).toBe("nexus.dynaminds.pl/kariera/p/marta-n");
    expect(careerVisibleUrl("nexus.dynaminds.pl", "/kariera", { to: "job", slug: "java-ab12" })).toBe(
      "nexus.dynaminds.pl/kariera/r/java-ab12",
    );
    expect(careerVisibleUrl("nexus.dynaminds.pl", "/kariera", { to: "home" })).toBe(
      "nexus.dynaminds.pl",
    );
  });
});
