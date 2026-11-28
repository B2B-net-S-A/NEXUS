import { readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { CaptureResult } from "posthog-js";
import { describeClick, routePattern, safeLabel, scrubEvent } from "../usage-analytics";

describe("routePattern — adres bez id kandydata, klienta i tokenów", () => {
  it("zamienia parametry trasy na ich nazwy", () => {
    expect(routePattern("/candidates/4821", { id: "4821" })).toBe("/candidates/[id]");
    expect(routePattern("/clients/17/contracts/903", { id: "17", contractId: "903" })).toBe(
      "/clients/[id]/contracts/[contractId]",
    );
    expect(routePattern("/kariera/r/senior-java-dev", { slug: "senior-java-dev" })).toBe("/kariera/r/[slug]");
    expect(routePattern("/help/a/b", { rest: ["a", "b"] })).toBe("/help/[...rest]/[...rest]");
  });

  it("parametr z polskimi znakami porównuje po zdekodowaniu", () => {
    expect(routePattern("/talents/%C5%81ukasz", { slug: "Łukasz" })).toBe("/talents/[slug]");
  });

  it("bez parametrów (404, stary link) id, UUID i tokeny i tak znikają", () => {
    expect(routePattern("/candidates/4821")).toBe("/candidates/[id]");
    expect(routePattern("/k/3f2b9c1e-8a4d-4b6f-9e2a-1c5d7e9f0a3b")).toBe("/k/[id]");
    expect(routePattern("/sign/Xy7_kP2qLmN9vR4tWz8sAb")).toBe("/sign/[id]");
    expect(routePattern("/share/a1b2c3d4e5f6a7b8c9d0")).toBe("/share/[id]");
    expect(routePattern("/candidates/Jan.Kowalski%40example.com")).toBe("/candidates/[id]");
  });

  it("query string i hash nie wchodzą do wzorca", () => {
    expect(routePattern("/candidates?q=Kowalski&email=jan%40example.com")).toBe("/candidates");
    expect(routePattern("/jobs#kandydat-4821")).toBe("/jobs");
  });

  it("każdy statyczny człon tras z app/ zostaje sobą", () => {
    const appDir = join(__dirname, "../../app");
    const statics = new Set<string>();
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (!entry.isDirectory() || entry.name === "__tests__") continue;
        if (!/^[[(_@]/.test(entry.name)) statics.add(entry.name);
        walk(join(dir, entry.name));
      }
    };
    walk(appDir);
    expect(statics.size).toBeGreaterThan(50);
    for (const segment of statics) expect(routePattern(`/${segment}`)).toBe(`/${segment}`);
  });
});

describe("safeLabel — nazwa przycisku tylko, gdy to etykieta z interfejsu", () => {
  it.each(["Zapisz", "Dodaj kandydata", "Pobierz CV", "Wyślij do DL", "Generator umów B2B", "Przekaż do searchu"])(
    "przepuszcza %s",
    label => expect(safeLabel(label)).toBe(label),
  );

  it.each([
    ["imię i nazwisko", "Jan Kowalski"],
    ["nazwisko w etykiecie", "Otwórz profil Kowalski"],
    ["firma", "Klient Orlen"],
    ["mail", "jan@example.com"],
    ["licznik", "Kandydaci 12"],
    ["kwota", "Stawka 180 zł"],
    ["data", "Rozmowa 2026-11-28"],
    ["adres", "https://example.com/cv"],
    ["długi tekst", "To jest bardzo długi tekst przycisku, który jest raczej treścią niż etykietą"],
    ["pusty", "   "],
  ])("odrzuca: %s", (_case, label) => expect(safeLabel(label)).toBeNull());
});

describe("describeClick — co kliknięto, bez treści", () => {
  const render = (html: string) => {
    document.body.innerHTML = html;
    return document.body;
  };

  it("data-track wygrywa z tekstem", () => {
    const body = render('<button data-track="candidate.save"><span>Zapisz Jan Kowalski</span></button>');
    expect(describeClick(body.querySelector("span"))).toEqual({
      target: "candidate.save",
      source: "data-track",
      element: "button",
    });
  });

  it("nazwa dostępności z aria-label albo tekstu", () => {
    const body = render('<button aria-label="Zamknij panel">×</button><a href="/jobs">Rekrutacje</a>');
    expect(describeClick(body.querySelector("button"))?.target).toBe("Zamknij panel");
    expect(describeClick(body.querySelector("a"))).toEqual({ target: "Rekrutacje", source: "nazwa", element: "a" });
  });

  it("tekst z wiersza tabeli nie idzie, nawet jeśli wygląda niewinnie", () => {
    const body = render('<table><tr><td><button>Przegląd</button><button aria-label="Usuń">x</button></td></tr></table>');
    const [text, labelled] = body.querySelectorAll("button");
    expect(describeClick(text)).toEqual({ target: null, source: "brak", element: "button" });
    expect(describeClick(labelled)?.target).toBe("Usuń");
  });

  it("kliknięcie poza przyciskiem nic nie daje", () => {
    const body = render("<p>Jan Kowalski, 180 zł</p><input value='tajne' />");
    expect(describeClick(body.querySelector("p"))).toBeNull();
    expect(describeClick(body.querySelector("input"))).toBeNull();
  });
});

describe("scrubEvent — before_send", () => {
  const state = { screen: "/candidates/[id]", active: true, origin: "https://nexus.b2bnetwork.pl" };
  const event = (name: string, properties: Record<string, unknown> = {}): CaptureResult =>
    ({ uuid: "u", event: name, properties }) as CaptureResult;

  it("adres zastępuje wzorzec, a adresy, tytuł, źródło wejścia i obiekty znikają", () => {
    const result = scrubEvent(
      {
        ...event("$pageview", {
          $current_url: "https://nexus.b2bnetwork.pl/candidates/4821?q=Kowalski",
          $pathname: "/candidates/4821",
          $title: "Jan Kowalski — NEXUS",
          $referrer: "https://nexus.b2bnetwork.pl/jobs/77",
          $initial_person_info: { u: "https://nexus.b2bnetwork.pl/candidates/4821" },
          $session_entry_url: "https://nexus.b2bnetwork.pl/candidates/4821",
          utm_source: "mail",
          $browser: "Chrome",
          role: "recruiter",
          distinct_id: "user-7",
          note: "/candidates/4821",
        }),
        $set_once: { $initial_current_url: "https://nexus.b2bnetwork.pl/candidates/4821" },
      },
      state,
    );
    expect(result?.properties).toEqual({
      $browser: "Chrome",
      role: "recruiter",
      distinct_id: "user-7",
      $current_url: "https://nexus.b2bnetwork.pl/candidates/[id]",
      $pathname: "/candidates/[id]",
      $host: "nexus.b2bnetwork.pl",
      screen: "/candidates/[id]",
    });
    expect(result).not.toHaveProperty("$set_once");
    expect(JSON.stringify(result)).not.toMatch(/4821|Kowalski/);
  });

  it("przepuszcza tylko odsłonę i kliknięcie", () => {
    expect(scrubEvent(event("ui_click", { target: "Zapisz" }), state)?.event).toBe("ui_click");
    for (const name of ["$autocapture", "$identify", "$pageleave", "$exception", "$rageclick", "$web_vitals", "$set"]) {
      expect(scrubEvent(event(name), state)).toBeNull();
    }
  });

  it("nic po wylogowaniu, przed pierwszym ekranem i na harnessach", () => {
    expect(scrubEvent(event("$pageview"), { ...state, active: false })).toBeNull();
    expect(scrubEvent(event("$pageview"), { ...state, screen: null })).toBeNull();
    expect(scrubEvent(event("$pageview"), { ...state, screen: "/preview/board" })).toBeNull();
  });
});
