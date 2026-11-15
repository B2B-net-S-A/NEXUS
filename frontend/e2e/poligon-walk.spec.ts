import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test";

import SHELL from "./fixtures/poligon-shell.json";

/**
 * Poligon NEXUSA — cała ścieżka onboardingu każdej roli bez backendu:
 * rekruter (19 ćwiczeń), Delivery Lead (15) i TCM (11, od 15.11.2026).
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

type Role = "recruiter" | "delivery_lead" | "talent_community_manager";

function person(role: Role) {
  return {
    id: 990900,
    email: `nowa.osoba.${role}@poligon.example`,
    first_name: "Nowa",
    last_name: "Osoba",
    full_name: "Nowa Osoba",
    role,
    roles: [role],
    is_active: true,
    allowed_sections: [],
    profile_completed: true,
    has_password: true,
    // Delivery Lead przesuwa bez bramek pól (`/api/auth/me`, 22.10.2026).
    skips_fill_gates: role === "delivery_lead",
    created_at: "2026-11-16T07:00:00+00:00",
  };
}
type Person = ReturnType<typeof person>;

function fakeJwt(user: Person): string {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const exp = Math.floor(Date.now() / 1000) + 8 * 3600;
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: String(user.id), role: user.role, roles: user.roles, exp, type: "access" })}.poligon`;
}

interface Backend {
  done: Set<string>;
  writes: string[];
}

/** Podstawiony backend: osoba, Start z poligonem i zapis postępu. Reszta = pusta odpowiedź. */
async function fakeBackend(page: Page, appOrigin: string, user: Person, total: number): Promise<Backend> {
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
    if (path === "/api/auth/me") return json(route, user);
    if (path in SHELL) return json(route, (SHELL as Record<string, unknown>)[path]);
    if (path === "/api/novelties/start") {
      const ids = [...state.done];
      const due = ids.length < total;
      return json(route, {
        enforced: true,
        items: [],
        done: 0,
        total: 0,
        poligon_due: due,
        redirect: due ? "/poligon" : "/start",
        poligon: { open: true, required: true, done_ids: ids, done: ids.length, total },
      });
    }
    return json(route, {}, 404);
  });
  return state;
}

const COACH = 'section[aria-label="Ćwiczenie na poligonie"]';

/** Nowa osoba danej roli na poligonie: blokada, mapa i pomocnicze kroki ćwiczeń. */
async function onPoligon(page: Page, context: BrowserContext, baseURL: string | undefined, role: Role, total: number) {
  await page.setViewportSize({ width: 1280, height: 720 });
  const user = person(role);
  const origin = new URL(baseURL ?? "http://localhost:3000");
  const backend = await fakeBackend(page, origin.origin, user, total);
  const misses: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (m) => {
    if (m.text().includes("[poligon] brak odpowiedzi w zestawie")) misses.push(m.text());
  });
  page.on("pageerror", (e) => pageErrors.push(`${new URL(page.url()).pathname}: ${String(e).slice(0, 300)}`));

  await context.addCookies([{ name: "nexus_access", value: fakeJwt(user), domain: origin.hostname, path: "/" }]);
  await context.addInitScript((u) => {
    if (!window.localStorage.getItem("nexus_user")) window.localStorage.setItem("nexus_user", JSON.stringify(u));
  }, user);

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
  await expect(page.getByText(`0 z ${total}`)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: /Zacznij onboarding/ }).click();
  await page.waitForURL(/\/jobs/, { timeout: 30_000 });
  await expect(coach).toBeVisible({ timeout: 30_000 });

  /** Koniec: blokada zdjęta, osoba wchodzi do pracy; nic nie brakowało i nic nie wyszło. */
  const finish = async () => {
    expect(backend.done.size).toBe(total);
    await coach.getByRole("button", { name: /Zacznij pracę/ }).click();
    await page.waitForURL(/\/jobs$/, { timeout: 30_000 });
    await page.goto("/candidates");
    await expect(page).not.toHaveURL(/\/poligon/);

    expect(misses, "ekran pyta o adres, którego nie ma w zestawie — nagraj go jeszcze raz").toEqual([]);
    expect(backend.writes, "zapis wyszedł z przeglądarki poza postępem poligonu").toEqual([]);
    expect(pageErrors, "błąd strony na poligonie").toEqual([]);
  };

  return { coach, done, next, card, board, openCard, moveNext, finish };
}
type Walk = Awaited<ReturnType<typeof onPoligon>>;

async function listExercises(page: Page, w: Walk) {
  await page.locator('[data-tour="jobs.list.scope"] button, [data-help="jobs.list.scope"] button').first().click();
  await w.done("lista-zakres");
  await w.next();
  await page.locator('[data-tour="jobs.list.filters"], [data-help="jobs.list.filters"]').first().click({ position: { x: 20, y: 12 } });
  await page.keyboard.press("Escape");
  await w.done("lista-filtry");
  await w.next();
  await page.locator('[data-tour="jobs.list.title"]').first().click();
  await page.waitForURL(/\/jobs\/990001/, { timeout: 30_000 });
  await w.done("lista-otworz");
  await w.next();
}

async function moveFirstCard(page: Page, w: Walk) {
  const first = page.locator("[data-kanban-card]").first();
  await first.hover();
  await first.getByRole("button", { name: /na następny etap/ }).click();
  await w.done("tablica-przesun");
  await w.next();
}

async function sourcesBar(page: Page, w: Walk) {
  await page.locator('[data-help="jobs.board.sources"]').first().click({ position: { x: 30, y: 15 } });
  await page.keyboard.press("Escape");
  await w.done("tablica-zrodla");
  await w.next();
}

/** Notatka, „@” (rekruter oznacza DL-a, pozostali rekrutera) i odrzucenie z powodem. */
async function personPanel(page: Page, w: Walk, mention: string) {
  await w.board();
  await page.locator("[data-kanban-card]").nth(1).click({ position: { x: 110, y: 40 } });
  const note = page.locator('[data-help="jobs.person.note"] textarea').first();
  await note.fill("Rozmowa telefoniczna: chce 140 zł/h na B2B, dostępna od 1 grudnia, szuka większego projektu w banku.");
  await note.press("Enter");
  await w.done("panel-notatka");
  await w.next();
  await note.click();
  await note.pressSequentially(`@${mention}`, { delay: 40 });
  await expect(page.getByRole("option").first()).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("Enter");
  await note.pressSequentially(" czy 140 zł/h mieści się w budżecie?");
  await note.press("Enter");
  await w.done("panel-wzmianka");
  await w.next();
  await page.getByRole("button", { name: /Odrzuć z powodem/ }).first().click();
  const reject = page.getByRole("dialog");
  await reject.getByText("Za wysokie oczekiwania finansowe", { exact: true }).click();
  const rate = reject.locator('input[type="number"], input[inputmode="decimal"], input[inputmode="numeric"]').first();
  if (await rate.count()) await rate.fill("160");
  await reject.getByRole("button", { name: "Potwierdź" }).click();
  await w.done("panel-odrzuc");
  await w.next();
}

async function candidateBase(page: Page, w: Walk) {
  await page.goto("/candidates");
  const search = page.locator('input[placeholder*="Nazwisko"]').first();
  await search.fill("Olszyńska");
  await search.press("Enter");
  await w.done("baza-szukaj");
  await w.next();
  await page.getByRole("link", { name: /Laura Olszyńska/ }).first().click();
  await page.waitForURL(/\/candidates\/99\d+/, { timeout: 30_000 });
  await w.done("baza-profil");
  await w.next();
  await page.locator('[data-help="candidate.profile.assign"]').first().click();
  await page.getByRole("dialog").getByRole("button", { name: /^Przypisz$/ }).first().click();
  await w.done("baza-przypisz");
  await page.getByRole("dialog").getByRole("button", { name: "Zamknij" }).last().click();
  await w.next();
}

test.describe("Poligon NEXUSA — onboarding dnia 1", () => {
  test.setTimeout(6 * 60_000);
  test.use({ actionTimeout: 20_000 });

  test("nowy rekruter przechodzi 19 ćwiczeń, a zestaw zna każdy odczyt", async ({ page, context, baseURL }) => {
    const w = await onPoligon(page, context, baseURL, "recruiter", 19);
    const { done, next, board, openCard, moveNext } = w;

    await listExercises(page, w);

    // Tablica
    await page.locator("[data-kanban-card] button", { hasText: "Biorę" }).first().click();
    await done("tablica-biore");
    await next();
    await moveFirstCard(page, w);
    await sourcesBar(page, w);
    await board();
    await page.locator('[data-tour="jobs.sources.my-people"]').first().click();
    await done("tablica-moi-ludzie");
    await page.keyboard.press("Escape");
    await next();

    await personPanel(page, w, "Ann");

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

    await candidateBase(page, w);
    await w.finish();
  });

  test("nowy Delivery Lead przechodzi 15 ćwiczeń z przeglądem i wysyłką do klienta", async ({ page, context, baseURL }) => {
    const w = await onPoligon(page, context, baseURL, "delivery_lead", 15);
    const { done, next, board, card, openCard } = w;

    await listExercises(page, w);
    // Ścieżka DL-a nie ma „Biorę” ani „Moich ludzi” — Tablica od przesunięcia.
    await moveFirstCard(page, w);
    await sourcesBar(page, w);
    await personPanel(page, w, "Jak");

    await openCard("Helena", "CV");
    await done("rekomendacja-cv");
    await next();

    // Przegląd Delivery Leada: osoba z „QC CV”.
    await board();
    await card("Weronika").getByRole("button", { name: /^Przejrzyj i wyślij/ }).click();
    await done("dl-przeglad-otworz");
    await next();
    // Stawka w budżecie (do 115 zł/h) i powyżej stawki kandydata (105 zł/h).
    await page.getByRole("textbox", { name: "Stawka do klienta" }).fill("112");
    await page.getByRole("button", { name: /^Akceptuj/ }).click();
    await done("dl-wyslij");
    await next();

    // „Wróć do poprawy” z zaznaczonym polem — druga osoba z „QC CV”.
    await board();
    await card("Szymon").getByRole("button", { name: /^Przejrzyj i wyślij/ }).click();
    await page.getByRole("button", { name: /Wróć do poprawy/ }).first().click();
    const fix = page.getByRole("dialog", { name: /Wróć do poprawy/ });
    await fix.getByRole("checkbox", { name: /Angielski/ }).check();
    await fix.getByRole("button", { name: /^Wróć do poprawy \(1\)/ }).click();
    await done("dl-poprawki");
    await next();

    await candidateBase(page, w);
    await w.finish();
  });

  test("nowy TCM przechodzi 11 ćwiczeń wspólnych modułów", async ({ page, context, baseURL }) => {
    const w = await onPoligon(page, context, baseURL, "talent_community_manager", 11);
    await listExercises(page, w);
    await moveFirstCard(page, w);
    await sourcesBar(page, w);
    await personPanel(page, w, "Jak");
    await candidateBase(page, w);
    await w.finish();
  });
});
