import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { CaptureResult } from "posthog-js";
import { appRouteSegments } from "../../../next.config";
import { describeClick, routePattern, scrubEvent } from "../usage-analytics";

// Ta sama lista, którą `next.config.ts` wstrzykuje do builda.
const STATICS = new Set(appRouteSegments(join(__dirname, "../../app")));
const pattern = (path: string, params = {}) => routePattern(path, params, STATICS);

describe("routePattern — adres bez id kandydata, klienta i tokenów", () => {
  it("zamienia parametry trasy na ich nazwy", () => {
    expect(pattern("/candidates/4821", { id: "4821" })).toBe("/candidates/[id]");
    expect(pattern("/clients/17/contracts/903", { id: "17", contractId: "903" })).toBe(
      "/clients/[id]/contracts/[contractId]",
    );
    expect(pattern("/kariera/r/senior-java-dev", { slug: "senior-java-dev" })).toBe("/kariera/r/[slug]");
    expect(pattern("/help/a/b", { rest: ["a", "b"] })).toBe("/help/[...rest]/[...rest]");
  });

  it("parametr z polskimi znakami porównuje po zdekodowaniu", () => {
    expect(pattern("/talents/%C5%81ukasz", { slug: "Łukasz" })).toBe("/talents/[slug]");
  });

  it("bez parametrów (404, stary link) id, UUID i tokeny i tak znikają", () => {
    expect(pattern("/candidates/4821")).toBe("/candidates/[id]");
    expect(pattern("/k/3f2b9c1e-8a4d-4b6f-9e2a-1c5d7e9f0a3b")).toBe("/k/[id]");
    expect(pattern("/sign/Xy7_kP2qLmN9vR4tWz8sAb")).toBe("/sign/[id]");
    expect(pattern("/share/a1b2c3d4e5f6a7b8c9d0")).toBe("/share/[id]");
    expect(pattern("/candidates/Jan.Kowalski%40example.com")).toBe("/candidates/[id]");
  });

  it("query string i hash nie wchodzą do wzorca", () => {
    expect(pattern("/candidates?q=Kowalski&email=jan%40example.com")).toBe("/candidates");
    expect(pattern("/jobs#kandydat-4821")).toBe("/jobs");
  });

  it("każdy statyczny człon tras z app/ zostaje sobą", () => {
    expect(STATICS.size).toBeGreaterThan(50);
    expect(STATICS).toContain("candidates");
    expect(STATICS).not.toContain("[id]");
    for (const segment of STATICS) expect(pattern(`/${segment}`)).toBe(`/${segment}`);
  });

  it("slug z małych liter bez parametru (404, wpisany ręcznie) nie przechodzi", () => {
    // Przegląd bezpieczeństwa 28.11.2026: wcześniej decydował wygląd członu.
    expect(pattern("/candidates/jan-kowalski")).toBe("/candidates/[id]");
    expect(pattern("/clients/nordea/contracts")).toBe("/clients/[id]/contracts");
  });

  it("bez listy z buildu wszystko spoza parametrów to [id]", () => {
    expect(routePattern("/candidates/4821", { id: "4821" }, new Set())).toBe("/[id]/[id]");
  });
});

describe("describeClick — co kliknięto, bez treści", () => {
  const render = (html: string) => {
    document.body.innerHTML = html;
    return document.body;
  };
  const click = (element: Element | null) => describeClick(element, STATICS);

  it("data-track wygrywa z tekstem", () => {
    const body = render('<button data-track="candidate.save"><span>Zapisz Jan Kowalski</span></button>');
    expect(click(body.querySelector("span"))).toEqual({
      target: "candidate.save",
      source: "data-track",
      element: "button",
    });
  });

  it("link wewnętrzny to wzorzec celu, nie tekst", () => {
    const body = render('<div><a href="/clients/12">Nordea</a><a href="/jobs?q=Kowalski">Rekrutacje</a></div>');
    const [client, jobs] = body.querySelectorAll("a");
    expect(click(client)).toEqual({ target: "/clients/[id]", source: "link", element: "a" });
    expect(click(jobs)).toEqual({ target: "/jobs", source: "link", element: "a" });
  });

  it.each([
    ["jedno słowo z wielkiej litery", '<button>Nordea</button>'],
    ["imię w aria-label", '<button aria-label="Kowalski">x</button>'],
    ["imię w title", '<button title="Anna">A</button>'],
    ["link na zewnątrz", '<a href="https://example.com/profil/jan">Profil</a>'],
    ["link mailto", '<a href="mailto:jan@example.com">jan@example.com</a>'],
  ])("bez nazwy: %s", (_case, html) => {
    const body = render(html);
    const result = click(body.firstElementChild);
    expect(result?.target).toBeNull();
    expect(result?.source).toBe("brak");
    expect(JSON.stringify(result)).not.toMatch(/Nordea|Kowalski|Anna|jan/);
  });

  it("zły data-track nie przechodzi jako nazwa", () => {
    const body = render('<button data-track="Jan Kowalski">x</button>');
    expect(click(body.querySelector("button"))).toEqual({ target: null, source: "brak", element: "button" });
  });

  it("kliknięcie poza przyciskiem nic nie daje", () => {
    const body = render("<p>Jan Kowalski, 180 zł</p><input value='tajne' />");
    expect(click(body.querySelector("p"))).toBeNull();
    expect(click(body.querySelector("input"))).toBeNull();
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
    expect(scrubEvent(event("ui_click", { target: "cv.download" }), state)?.event).toBe("ui_click");
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
