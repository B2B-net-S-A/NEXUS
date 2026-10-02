/**
 * Uwierzytelniony klient API dla scenariuszy E2E.
 *
 * Aplikacja trzyma JWT w localStorage i wysyła go nagłówkiem `Authorization`.
 * Fixture `request` Playwrighta niesie wyłącznie cookies ze storageState, więc
 * dawne scenariusze wołały API BEZ tokena — dostawały 401, a asercja
 * `status < 500` przyjmowała to jako sukces. Tutaj każdy kontekst dokleja
 * Bearer do każdego wywołania. Token roli jest pamiętany w procesie workera
 * i sprawdzany przez `/api/auth/me`; ponowne logowanie tylko po 401 (zmiana
 * uprawnień wylogowuje konto). Logowanie ma limit 30/min na adres, a jedno
 * logowanie na test wyczerpywało go w połowie zestawu.
 *
 * Konta: `backend/scripts/seed_e2e.py` zakłada je na stacku E2E z jednym
 * hasłem `E2E_USER_PASSWORD`.
 */
import {
  test as base,
  expect,
  request as playwrightRequest,
  type APIRequestContext,
  type APIResponse,
} from "@playwright/test";

export const API_URL = process.env.E2E_API_URL || "https://api.nexus.dynaminds.pl";

export type E2ERole = "admin" | "recruiter" | "delivery_lead" | "finance";

const ROLE_EMAILS: Record<E2ERole, string> = {
  admin: process.env.E2E_USER_EMAIL || "e2e-admin@example.com",
  recruiter: process.env.E2E_RECRUITER_EMAIL || "e2e-recruiter@example.com",
  delivery_lead: process.env.E2E_DL_EMAIL || "e2e-dl@example.com",
  finance: process.env.E2E_FINANCE_EMAIL || "e2e-finance@example.com",
};

export interface ApiSession {
  api: APIRequestContext;
  userId: number;
  email: string;
  name: string;
}

const tokens = new Map<E2ERole, string>();

async function freshToken(role: E2ERole, email: string): Promise<string> {
  const password = process.env.E2E_USER_PASSWORD || "";
  expect(password, "E2E_USER_PASSWORD jest wymagane do scenariuszy API").not.toBe("");

  const anonymous = await playwrightRequest.newContext({ baseURL: API_URL });
  const response = await anonymous.post("/api/auth/login", { data: { email, password } });
  await expectStatus(response, 200, `logowanie ${role}`);
  const { access_token: token } = (await response.json()) as { access_token: string };
  await anonymous.dispose();
  tokens.set(role, token);
  return token;
}

async function login(role: E2ERole): Promise<ApiSession> {
  const email = ROLE_EMAILS[role];
  const cached = tokens.get(role);

  for (const token of [cached, null]) {
    const api = await playwrightRequest.newContext({
      baseURL: API_URL,
      extraHTTPHeaders: {
        Authorization: `Bearer ${token ?? (await freshToken(role, email))}`,
      },
    });
    const me = await api.get("/api/auth/me");
    // Zapamiętany token unieważniony (zmiana uprawnień) — logujemy się od nowa.
    if (token && me.status() === 401) {
      tokens.delete(role);
      await api.dispose();
      continue;
    }
    await expectStatus(me, 200, `/api/auth/me ${role}`);
    const body = (await me.json()) as { id: number; name: string };
    return { api, userId: body.id, email, name: body.name };
  }
  throw new Error(`logowanie ${role}: sesja odrzucona zaraz po zalogowaniu`);
}

/**
 * Dokładny status z treścią odpowiedzi w komunikacie — porażka ma od razu
 * mówić, CO odpowiedział serwer, a nie tylko „expected 201, got 422".
 */
export async function expectStatus(
  response: APIResponse,
  expected: number,
  label: string
): Promise<void> {
  if (response.status() !== expected) {
    const body = await response.text().catch(() => "<brak treści>");
    throw new Error(
      `${label}: oczekiwano HTTP ${expected}, jest ${response.status()} — ${body.slice(0, 800)}`
    );
  }
}

/** JSON odpowiedzi po sprawdzeniu dokładnego statusu. */
export async function jsonOf<T>(
  response: APIResponse,
  expected: number,
  label: string
): Promise<T> {
  await expectStatus(response, expected, label);
  return (await response.json()) as T;
}

/** Krótki unikalny sufiks — każdy scenariusz zakłada własne dane. */
export function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

type ApiFixtures = {
  /** Sesja administratora E2E. */
  admin: ApiSession;
  /** Sesja dowolnej roli; konteksty są zamykane po teście. */
  apiAs: (role: E2ERole) => Promise<ApiSession>;
};

export const test = base.extend<ApiFixtures>({
  // Parametr fixture'a nazwany `provide`, nie `use` — reguła react-hooks
  // bierze każde `use(...)` za hook Reacta.
  apiAs: async ({}, provide) => {
    const opened: ApiSession[] = [];
    await provide(async (role) => {
      const session = await login(role);
      opened.push(session);
      return session;
    });
    await Promise.all(opened.map((session) => session.api.dispose()));
  },
  admin: async ({ apiAs }, provide) => {
    await provide(await apiAs("admin"));
  },
});

export { expect };
