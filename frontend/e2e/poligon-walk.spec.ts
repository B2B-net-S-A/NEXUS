import { expect, test, type Page, type Route } from "@playwright/test";

import SHELL from "./fixtures/poligon-shell.json";

/**
 * Poligon NEXUSA — cała ścieżka onboardingu (19 ćwiczeń) bez backendu.
 *
 * Nowa osoba ma zablokowany NEXUS, dopóki nie zaliczy wszystkich ćwiczeń
 * (`docs/claude/ui/poligon-nexusa-onboarding.md`). Ćwiczenia idą na
 * prawdziwych ekranach, a odczyty rekrutacji ćwiczebnej podaje zestaw
 * `src/lib/poligon/dataset.json` nagrany 14.11.2026. Gdy ekran zacznie pytać
 * o adres, którego zestaw nie zna, adapter pisze tylko ostrzeżenie w konsoli —
 * a osoba utyka na ćwiczeniu, którego nie da się zaliczyć. Ten test przechodzi
 * całą ścieżkę i pada na każde takie ostrzeżenie, na błąd strony i na zapis,
 * który wyszedłby z przeglądarki poza postępem `poligon-*`.
 *
 * Backend jest w całości podstawiony (`page.route`): powłoka dostaje fikcyjną
 * osobę, szablon etapów z `fixtures/poligon-shell.json` (konfiguracja, bez
 * osób) i 404 na resztę, więc test nie potrzebuje bazy ani logowania.
 * Uruchomienie: `E2E_BASE_URL=http://localhost:3000 npx playwright test --project=poligon-chromium`
 * (frontend z `NEXT_PUBLIC_API_URL`, domyślnie http://localhost:8000; `next dev` też
 * działa). `POLIGON_E2E_DEBUG=1` wypisuje każde zapytanie do podstawionego API.
 */

const API_ORIGIN = (process.env.E2E_API_ORIGIN || "http://localhost:8000").replace(/\/$/, "");
const TOTAL = 19;

const USER = {
  id: 990900,
  email: "nowa.rekruterka@poligon.example",
  first_name: "Nowa",
  last_name: "Rekruterka",
  full_name: "Nowa Rekruterka",
  role: "recruiter",
  roles: ["recruiter"],
  is_active: true,
  allowed_sections: [],
  profile_completed: true,
  has_password: true,
  created_at: "2026-11-16T07:00:00+00:00",
};

function fakeJwt(): string {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const exp = Math.floor(Date.now() / 1000) + 8 * 3600;
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: String(USER.id), role: "recruiter", roles: ["recruiter"], exp, type: "access" })}.poligon`;
}

interface Backend {
  done: Set<string>;
  writes: string[];
}

/** Podstawiony backend: osoba, Start z poligonem i zapis postępu. Reszta = pusta odpowiedź. */
async function fakeBackend(page: Page, appOrigin: string): Promise<Backend> {
  const state: Backend = { done: new Set(), writes: [] };
  // API stoi na innym originie niż front, więc podstawione odpowiedzi muszą
  // przejść CORS z ciasteczkami jak prawdziwe.
  const cors = {
    "access-control-allow-origin": appOrigin,
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "*",
    "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
  };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, headers: cors, contentType: "application/json", body: JSON.stringify(body) });

  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers: cors });

    const progress = path.match(/^\/api\/novelties\/(poligon-[a-z0-9-]+)\/events$/);
    if (progress && method === "POST") {
      const body = req.postDataJSON() as { event?: string } | null;
      if (body?.event === "used") state.done.add(progress[1]);
      return json(route, { novelty_id: progress[1], completed: body?.event === "used" });
    }
    if (process.env.POLIGON_E2E_DEBUG) console.log("API", method, path);
    if (method !== "GET" && method !== "HEAD") {
      state.writes.push(`${method} ${path}`);
      return json(route, { detail: "poligon-e2e: zapis poza poligonem" }, 409);
    }
    if (path === "/api/auth/me") return json(route, USER);
    if (path in SHELL) return json(route, (SHELL as Record<string, unknown>)[path]);
    if (path === "/api/novelties/start") {
      const ids = [...state.done];
      const due = ids.length < TOTAL;
      return json(route, {
        enforced: true,
        items: [],
        done: 0,
        total: 0,
        poligon_due: due,
        redirect: due ? "/poligon" : "/start",
        poligon: { open: true, required: true, done_ids: ids, done: ids.length, total: TOTAL },
      });
    }
    return json(route, {}, 404);
  });
  return state;
}

const COACH = 'section[aria-label="Ćwiczenie na poligonie"]';

test.describe("Poligon NEXUSA — onboarding dnia 1", () => {
  test.setTimeout(6 * 60_000);
  test.use({ actionTimeout: 20_000 });

  test("nowa osoba przechodzi 19 ćwiczeń, a zestaw zna każdy odczyt", async ({ page, context, baseURL }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    const origin = new URL(baseURL ?? "http://localhost:3000");
    const backend = await fakeBackend(page, origin.origin);
    const misses: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (m) => {
      if (m.text().includes("[poligon] brak odpowiedzi w zestawie")) misses.push(m.text());
    });
    page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));

    await context.addCookies([{ name: "nexus_access", value: fakeJwt(), domain: origin.hostname, path: "/" }]);
    await context.addInitScript((user) => {
      if (!window.localStorage.getItem("nexus_user")) window.localStorage.setItem("nexus_user", JSON.stringify(user));
    }, USER);

    const coach = page.locator(COACH);
    const done = (id: string) =>
      expect.poll(() => backend.done.has(`poligon-${id}`), { message: `ćwiczenie ${id} niezaliczone`, timeout: 15_000 }).toBe(true);
    const next = async () => {
      await coach.getByRole("button", { name: /^Dalej|Zakończ onboarding/ }).click();
    };
    const card = (text: string) => page.locator("[data-kanban-card]", { hasText: text }).first();
    // Stan poligonu (ruchy, screening) żyje w pamięci karty, więc na Tablicę
    // wracamy bez przeładowania strony — tak jak osoba w aplikacji.
    const board = async () => {
      if (new URL(page.url()).pathname === "/jobs/990001") {
        await page.keyboard.press("Escape");
        await page.keyboard.press("Escape");
      } else {
        await page.goto("/jobs/990001");
      }
      await expect(page.locator("[data-kanban-card]").first()).toBeVisible({ timeout: 30_000 });
    };
    const openCard = async (text: string, tab?: string) => {
      await board();
      await card(text).click({ position: { x: 110, y: 40 } });
      if (tab) await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).first().click();
    };
    const moveNext = async (text: string) => {
      const c = card(text);
      await c.hover();
      await c.getByRole("button", { name: /na następny etap/ }).click();
    };

    // Blokada: każdy ekran prowadzi na mapę poligonu.
    await page.goto("/jobs");
    await page.waitForURL(/\/poligon$/, { timeout: 30_000 });
    await page.getByRole("button", { name: /Zacznij onboarding/ }).click();
    await page.waitForURL(/\/jobs/, { timeout: 30_000 });
    await expect(coach).toBeVisible({ timeout: 30_000 });

    // Lista rekrutacji
    await page.locator('[data-tour="jobs.list.scope"] button, [data-help="jobs.list.scope"] button').first().click();
    await done("lista-zakres");
    await next();
    await page.locator('[data-tour="jobs.list.filters"], [data-help="jobs.list.filters"]').first().click({ position: { x: 20, y: 12 } });
    await page.keyboard.press("Escape");
    await done("lista-filtry");
    await next();
    await page.locator('[data-tour="jobs.list.title"]').first().click();
    await page.waitForURL(/\/jobs\/990001/, { timeout: 30_000 });
    await done("lista-otworz");
    await next();

    // Tablica
    await page.locator("[data-kanban-card] button", { hasText: "Biorę" }).first().click();
    await done("tablica-biore");
    await next();
    const first = page.locator("[data-kanban-card]").first();
    await first.hover();
    await first.getByRole("button", { name: /na następny etap/ }).click();
    await done("tablica-przesun");
    await next();
    await page.locator('[data-help="jobs.board.sources"]').first().click({ position: { x: 30, y: 15 } });
    await page.keyboard.press("Escape");
    await done("tablica-zrodla");
    await next();
    await board();
    await page.locator('[data-tour="jobs.sources.my-people"]').first().click();
    await done("tablica-moi-ludzie");
    await page.keyboard.press("Escape");
    await next();

    // Panel osoby
    await board();
    await page.locator("[data-kanban-card]").nth(1).click({ position: { x: 110, y: 40 } });
    const note = page.locator('[data-help="jobs.person.note"] textarea').first();
    await note.fill("Rozmowa telefoniczna: chce 140 zł/h na B2B, dostępna od 1 grudnia, szuka większego projektu w banku.");
    await note.press("Enter");
    await done("panel-notatka");
    await next();
    await note.click();
    await note.pressSequentially("@Ann", { delay: 40 });
    await expect(page.getByRole("option").first()).toBeVisible({ timeout: 10_000 });
    await page.keyboard.press("Enter");
    await note.pressSequentially(" czy 140 zł/h mieści się w budżecie?");
    await note.press("Enter");
    await done("panel-wzmianka");
    await next();
    await page.getByRole("button", { name: /Odrzuć z powodem/ }).first().click();
    const reject = page.getByRole("dialog");
    await reject.getByText("Za wysokie oczekiwania finansowe", { exact: true }).click();
    const rate = reject.locator('input[type="number"], input[inputmode="decimal"], input[inputmode="numeric"]').first();
    if (await rate.count()) await rate.fill("160");
    await reject.getByRole("button", { name: "Potwierdź" }).click();
    await done("panel-odrzuc");
    await next();

    // Screening i weryfikacja
    await openCard("Aleksandra", "Screening");
    await page.locator('[data-help="jobs.person.screening-form"]').first().click({ position: { x: 40, y: 20 } });
    await done("screening-otworz");
    await next();
    await board();
    await moveNext("Aleksandra");
    await done("screening-bramka");
    await page.keyboard.press("Escape");
    await next();
    await openCard("Aleksandra", "Screening");
    const form = page.locator('[data-help="jobs.person.screening-form"]').first();
    await form.locator('input[name="card.location"]').fill("Gdańsk");
    await form.locator('input[name="card.work_mode"]').fill("hybrydowo, 3 dni w biurze");
    for (const q of ["q1", "q2", "q3", "q4"]) {
      const answer = form.locator(`textarea[name="answers.${q}.response"]`);
      if (await answer.count()) await answer.fill("Prowadziła program migracji płatności w banku: 4 zespoły, 2 lata, raporty dla komitetu.");
    }
    await form.locator('textarea[name="card.recommendation"]').fill(
      "Prowadziła migrację płatności w banku z czterema zespołami; zna regulacje i raportuje do komitetu sterującego.",
    );
    await form.getByRole("button", { name: /^Zapisz$/ }).click();
    await done("screening-zapisz");
    await next();
    await board();
    await moveNext("Aleksandra");
    await page.getByRole("dialog").getByRole("button", { name: /Przesuń|Zweryfikowany/ }).last().click();
    // Po weryfikacji bywa drugie okno (np. potwierdzenie stawki) — zatwierdzamy je.
    const confirm = page.getByRole("dialog");
    await page.waitForTimeout(1500);
    if (await confirm.count()) {
      const ok = confirm.getByRole("button", { name: /Zapisz|Przesuń|Potwierdź/ }).last();
      if (await ok.count()) await ok.click();
    }
    await done("screening-zweryfikuj");
    await next();

    // Rekomendacja
    await openCard("Helena", "CV");
    await done("rekomendacja-cv");
    await next();
    await board();
    await moveNext("Jaworek");
    const qc = page.getByRole("dialog");
    if (await qc.count()) await qc.getByRole("button", { name: /Przesuń|QC/ }).last().click();
    await done("rekomendacja-qc");
    await next();

    // Baza kandydatów
    await page.goto("/candidates");
    const search = page.locator('input[placeholder*="Nazwisko"]').first();
    await search.fill("Olszyńska");
    await search.press("Enter");
    await done("baza-szukaj");
    await next();
    await page.getByRole("link", { name: /Laura Olszyńska/ }).first().click();
    await page.waitForURL(/\/candidates\/99\d+/, { timeout: 30_000 });
    await done("baza-profil");
    await next();
    await page.locator('[data-help="candidate.profile.assign"]').first().click();
    await page.getByRole("dialog").getByRole("button", { name: /^Przypisz$/ }).first().click();
    await done("baza-przypisz");
    await page.getByRole("dialog").getByRole("button", { name: "Zamknij" }).last().click();
    await next();

    // Koniec: blokada zdjęta, osoba wchodzi do pracy.
    expect(backend.done.size).toBe(TOTAL);
    await coach.getByRole("button", { name: /Zacznij pracę/ }).click();
    await page.waitForURL(/\/jobs$/, { timeout: 30_000 });
    await page.goto("/candidates");
    await expect(page).not.toHaveURL(/\/poligon/);

    expect(misses, "ekran pyta o adres, którego nie ma w zestawie — nagraj go jeszcze raz").toEqual([]);
    expect(backend.writes, "zapis wyszedł z przeglądarki poza postępem poligonu").toEqual([]);
    expect(pageErrors, "błąd strony na poligonie").toEqual([]);
  });
});
