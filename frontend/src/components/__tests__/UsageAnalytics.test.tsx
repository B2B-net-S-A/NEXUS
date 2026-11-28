import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// Fikcyjny klucz w formacie projektu PostHog — nie istnieje.
const KEY = `phc_${"A1b2C3d4".repeat(5)}`;
const API = "https://api.nexus.b2bnetwork.pl";

const posthog = {
  init: vi.fn(),
  capture: vi.fn(),
  register: vi.fn(),
  reset: vi.fn(),
  identify: vi.fn(),
};
let pathname = "/candidates/4821";

function live(body: Record<string, unknown>): Response {
  return new Response(JSON.stringify({ status: "alive", ...body }), {
    status: 200,
    headers: { "x-request-id": crypto.randomUUID() },
  });
}

async function mount(options: { body: Record<string, unknown>; impersonating?: boolean }) {
  const fetchMock = vi.fn().mockResolvedValue(live(options.body));
  vi.stubGlobal("fetch", fetchMock);
  const { useAuthStore } = await import("@/store/auth");
  const user = { id: 7, role: "recruiter", email: "x@example.invalid", name: "Testowy" };
  useAuthStore.setState({
    user: user as never,
    realUser: options.impersonating ? ({ ...user, id: 1, role: "admin" } as never) : null,
    hydrated: true,
  });
  const { UsageAnalytics } = await import("../UsageAnalytics");
  await act(async () => {
    render(<UsageAnalytics />);
  });
  // Sonda i dynamiczny import `posthog-js` kończą się w kolejnych mikrozadaniach.
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  return fetchMock;
}

beforeEach(() => {
  vi.resetModules();
  Object.values(posthog).forEach(fn => fn.mockReset());
  vi.doMock("posthog-js", () => ({ default: posthog }));
  vi.doMock("next/navigation", () => ({
    usePathname: () => pathname,
    useParams: () => ({ id: "4821" }),
  }));
  vi.stubEnv("NEXT_PUBLIC_API_URL", API);
  vi.stubEnv("NEXUS_ROUTE_SEGMENTS", "candidates,jobs,preview,board");
  pathname = "/candidates/4821";
});

afterEach(async () => {
  const analytics = await import("@/lib/usage-analytics");
  analytics.resetUsageAnalyticsForTests();
  vi.doUnmock("posthog-js");
  vi.doUnmock("next/navigation");
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  document.body.innerHTML = "";
});

it("bez flagi API nie ładuje PostHog i nie wysyła nic poza sondą", async () => {
  const fetchMock = await mount({ body: { usageCounter: false, usageAnalytics: null } });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe(`${API}/api/health/live`);
  expect(posthog.init).not.toHaveBeenCalled();
});

it("starsze API bez pola i zły format klucza też nic nie włączają", async () => {
  await mount({ body: {} });
  expect(posthog.init).not.toHaveBeenCalled();
  vi.resetModules();
  vi.doMock("posthog-js", () => ({ default: posthog }));
  await mount({ body: { usageAnalytics: `phx_${"A1b2C3d4".repeat(5)}` } });
  expect(posthog.init).not.toHaveBeenCalled();
});

it("z kluczem: region UE, bez autocapture i nagrań, osoba jako id i rola", async () => {
  await mount({ body: { usageAnalytics: KEY } });
  expect(posthog.init).toHaveBeenCalledTimes(1);
  const [key, options] = posthog.init.mock.calls[0];
  expect(key).toBe(KEY);
  expect(options).toMatchObject({
    api_host: "https://eu.i.posthog.com",
    persistence: "memory",
    bootstrap: { distinctID: "user-7", isIdentifiedID: true },
    autocapture: false,
    capture_pageview: false,
    disable_session_recording: true,
    disable_external_dependency_loading: true,
    advanced_disable_flags: true,
    mask_all_text: true,
    mask_all_element_attributes: true,
    session_recording: { maskAllInputs: true, maskTextSelector: "*" },
  });
  expect(posthog.register).toHaveBeenCalledWith({ role: "recruiter" });
  expect(JSON.stringify(posthog.register.mock.calls)).not.toMatch(/example|Testowy/);
  expect(posthog.capture).toHaveBeenCalledWith("$pageview");

  // before_send z init: adres z id kandydata wychodzi jako wzorzec trasy.
  const sent = options.before_send({
    uuid: "u",
    event: "$pageview",
    properties: { $current_url: `${window.location.origin}/candidates/4821` },
  });
  expect(sent.properties.$current_url).toBe(`${window.location.origin}/candidates/[id]`);
});

it("kliknięcie przycisku wysyła data-track, nie treść", async () => {
  await mount({ body: { usageAnalytics: KEY } });
  document.body.innerHTML = '<button data-track="cv.download">Pobierz CV Jan Kowalski</button>';
  document.querySelector("button")?.click();
  expect(posthog.capture).toHaveBeenCalledWith("ui_click", {
    target: "cv.download",
    source: "data-track",
    element: "button",
  });
});

it("„Podgląd jako” nie startuje pomiaru ani sondy", async () => {
  const fetchMock = await mount({ body: { usageAnalytics: KEY }, impersonating: true });
  expect(fetchMock).not.toHaveBeenCalled();
  expect(posthog.init).not.toHaveBeenCalled();
});

it("staging nie wysyła do PostHog", async () => {
  vi.stubEnv("NEXT_PUBLIC_NEXUS_ENV", "staging");
  await mount({ body: { usageAnalytics: KEY } });
  expect(posthog.init).not.toHaveBeenCalled();
});

it("harness /preview/* nie startuje pomiaru", async () => {
  pathname = "/preview/board";
  const fetchMock = await mount({ body: { usageAnalytics: KEY } });
  expect(fetchMock).not.toHaveBeenCalled();
  expect(posthog.init).not.toHaveBeenCalled();
});

it("po udanej sondzie nie pyta API drugi raz", async () => {
  const fetchMock = await mount({ body: { usageAnalytics: KEY } });
  const { useAuthStore } = await import("@/store/auth");
  await act(async () => {
    useAuthStore.setState({ user: { id: 8, role: "delivery_lead" } as never });
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(posthog.identify).toHaveBeenCalledWith("user-8");
  expect(posthog.register).toHaveBeenLastCalledWith({ role: "delivery_lead" });
});
