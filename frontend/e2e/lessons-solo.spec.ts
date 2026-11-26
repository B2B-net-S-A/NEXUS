import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page, type Route } from "@playwright/test";

import { LESSON_SCREENS } from "./fixtures/lesson-screens";
import SHELL from "./fixtures/poligon-shell.json";

/**
 * Lekcje nowości: etap „sam” każdej lekcji da się przejść tym, co pokazał pokaz
 * (Artur, 26.11.2026: „ciągle są błędy i blokujesz ludziom pracę”).
 *
 * Od 23.11 poranna porcja lekcji blokuje pracę, a co dzień wchodzą nowe lekcje.
 * Na produkcji 26.11 lekcje „Wysyłka do podpisu”, „Porcja: karta”, „Arkusz
 * rozmowy”, „CV do klienta” i „Karty bez śladu” zaliczało furtką „Coś nie
 * działa” od 4 do 6 osób, a Delivery Lead klikał „Wróć do pokazu” po kilka razy
 * i stał. CI przechodził tylko ćwiczenia Poligonu (`poligon-walk.spec.ts`),
 * a automat lekcji z 25.11 chodził poza repo i był pobłażliwy: pomijał
 * niewidoczne kroki i klikał „na siłę”.
 *
 * Ten test robi to, co człowiek po pokazie, i nic więcej:
 * - lekcja startuje w etapie „sam” na `solo_href` przy 1280 × 720;
 * - osoba powtarza kroki pokazu (bez kroków „Rozumiem”) w kolejności; każdy
 *   element musi dać się zobaczyć i kliknąć — przewinięcie wolno, zwinięcie
 *   karty zadania też, kliknięcie przez zasłonę nie;
 * - na końcu klika element z zadania (warunek `click`) albo dochodzi do ekranu
 *   (warunek `page`) i lekcja przechodzi do pytania.
 *
 * Każda rola z odbiorców lekcji, która ma ścieżkę na Poligonie. Ruch karty
 * (warunek `move`) sprawdza ocena w `lessons.test.ts`.
 *
 * Uruchomienie jak `poligon-walk.spec.ts` (`--project=poligon-chromium`).
 * `LESSONS_E2E_ONLY=lekcja-a,lekcja-b` zawęża bieg do wybranych lekcji,
 * `LESSONS_E2E_SHOTS=1` zapisuje zrzut po każdym kroku pokazu (katalog wyników testu).
 */

const API_ORIGIN = (process.env.E2E_API_ORIGIN || "http://localhost:8000").replace(/\/$/, "");
const DATA = path.resolve(__dirname, "../../backend/app/data/novelties");

interface Step {
  anchor: string;
  text: string;
  hint?: string;
  ack?: boolean;
}
interface NoveltyDef {
  id: string;
  title: string;
  why: string;
  dot_anchor?: string | null;
  steps?: Step[];
  audience?: { roles?: string[]; permissions?: string[] } | null;
  [key: string]: unknown;
}
type Check =
  | { kind: "click"; anchor: string }
  | { kind: "page"; path_prefix: string; query?: Record<string, string> }
  | { kind: "move"; to: string };
interface LessonDef {
  id: string;
  title: string;
  task: string;
  solo_href: string;
  check: Check;
  questions: unknown[];
  novelties: string[];
}

const LESSONS = JSON.parse(readFileSync(path.join(DATA, "lessons.json"), "utf8")) as LessonDef[];
const NOVELTIES = new Map(
  (JSON.parse(readFileSync(path.join(DATA, "novelties.json"), "utf8")) as NoveltyDef[]).map((n) => [n.id, n]),
);

/**
 * Lekcje, których etap „sam” nie przechodzi drogą z pokazu, sprzed strażnika
 * (26.11.2026). Na produkcji przechodzą bez furtki, ale wymagają kroku, którego
 * pokaz nie pokazał. Lista może tylko maleć: nowa lekcja nie wchodzi na nią,
 * a poprawiona schodzi (test niżej pada na wpis, który już przechodzi).
 */
const KNOWN_GAPS = new Set<string>([]);

/**
 * Role, które test przechodzi. Rekruter i Delivery Lead mają różne ekrany
 * (bramki pól, przegląd DL), więc lekcja rekrutacji idzie każdą z nich osobno —
 * to ich porcja blokuje pracę co rano. Lekcja bez tych ról (Finanse, Sprzedaż,
 * kontrakty, klienci) idzie jedną rolą ze swoich odbiorców: Finanse, a gdy
 * odbiorców wyznacza uprawnienie (wpis bez ról) — admin, który ma wszystkie.
 */
type Role = "recruiter" | "delivery_lead" | "finance" | "admin";

function audienceRoles(lesson: LessonDef): Role[] {
  const roles = new Set<string>();
  let everyone = false;
  for (const id of lesson.novelties) {
    const listed = NOVELTIES.get(id)?.audience?.roles;
    if (!listed || listed.length === 0) everyone = true;
    else listed.forEach((r) => roles.add(r));
  }
  const recruiting = (["recruiter", "delivery_lead"] as const).filter((r) => roles.has(r));
  if (recruiting.length) return recruiting;
  if (roles.has("finance")) return ["finance"];
  return roles.has("admin") || everyone ? ["admin"] : [];
}

/** Kroki pokazu jak we froncie (`withSteps`): wpis bez kroków dostaje krok na kropce. */
function showSteps(novelty: NoveltyDef): Step[] {
  if (novelty.steps && novelty.steps.length > 0) return novelty.steps;
  return novelty.dot_anchor ? [{ anchor: novelty.dot_anchor, text: novelty.title, hint: novelty.why, ack: true }] : [];
}

/**
 * Droga z pokazu do warunku lekcji: kroki do klikania (bez „Rozumiem”).
 * Warunek `click`: kroki wpisu, w którym pokaz wskazał element z zadania,
 * do tego elementu. Element, którego pokaz nie wskazał, nie ma drogi (`null`).
 */
function soloPath(lesson: LessonDef): Step[] | null {
  const novelties = lesson.novelties.map((id) => NOVELTIES.get(id)).filter((n): n is NoveltyDef => Boolean(n));
  if (lesson.check.kind === "click") {
    const anchor = lesson.check.anchor;
    for (const n of novelties) {
      const steps = showSteps(n);
      const at = steps.findIndex((s) => s.anchor === anchor);
      if (at >= 0) return steps.slice(0, at).filter((s) => !s.ack);
    }
    return null;
  }
  // Kilka wpisów zaczyna od tego samego kroku („Kliknij wiersz kontraktu”):
  // człowiek nie wraca na listę, żeby kliknąć go drugi raz.
  const seen = new Set<string>();
  return novelties
    .flatMap((n) => showSteps(n).filter((s) => !s.ack))
    .filter((s) => (seen.has(s.anchor) ? false : (seen.add(s.anchor), true)));
}

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
    skips_fill_gates: role === "delivery_lead",
    created_at: "2026-10-01T07:00:00+00:00",
    // Delivery Lead widzi swoich klientów; Poligon dokleja do portfela klienta
    // ćwiczebnego (`withPracticeClient`), więc portfel jest pusty, ale jest.
    ...(role === "delivery_lead"
      ? { data_scope: { kind: "delivery_clients", allowed_client_ids: [], finance_client_ids: [] } }
      : {}),
  };
}

function fakeJwt(user: ReturnType<typeof person>): string {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const exp = Math.floor(Date.now() / 1000) + 8 * 3600;
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: String(user.id), role: user.role, roles: user.roles, exp, type: "access" })}.poligon`;
}

/** Podstawiony backend: osoba, brak blokad, zapis etapów lekcji. Reszta = 404. */
async function fakeBackend(page: Page, appOrigin: string, user: ReturnType<typeof person>) {
  const events: string[] = [];
  /** Odczyty bez odpowiedzi (404) — w opisie porażki, bo zwykle to brak w podstawionym backendzie. */
  const misses = new Set<string>();
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
    const p = new URL(req.url()).pathname;
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    const lessonEvent = p.match(/^\/api\/novelties\/lessons\/([^/]+)\/events$/);
    if (lessonEvent && req.method() === "POST") {
      events.push(`${lessonEvent[1]}:${(req.postDataJSON() as { event?: string } | null)?.event}`);
      return route.fulfill({ status: 204, headers: cors });
    }
    if (req.method() !== "GET") return json(route, { detail: "lessons-e2e: zapis poza lekcją" }, 409);
    if (p === "/api/auth/me") return json(route, user);
    if (p in SHELL) return json(route, (SHELL as Record<string, unknown>)[p]);
    // Paleta szuka firm sprzedaży po NIP-ie (`?q=`): nowy NIP nie ma jeszcze
    // firmy, więc akcja „Załóż firmę z NIP” zostaje na liście (lekcja-firma-z-nip).
    if (p === "/api/sales/companies" && new URL(req.url()).searchParams.get("q")) {
      return json(route, { items: [], total: 0 });
    }
    if (p in LESSON_SCREENS) return json(route, LESSON_SCREENS[p]);
    if (p === "/api/novelties/start") return json(route, { enforced: false, items: [], done: 0, total: 0, poligon: null });
    if (p === "/api/novelties/daily") return json(route, { gate_on: false, enforced: false, items: [], lessons: [] });
    misses.add(p);
    return json(route, {}, 404);
  });
  return { events, misses };
}

/** Element kotwicy widoczny i nie zasłonięty — punkt do kliknięcia albo powód. */
async function reach(page: Page, anchor: string, stepText = ""): Promise<{ x: number; y: number } | string> {
  const selector = `[data-tour="${anchor}"], [data-help="${anchor}"]`;
  // Krok „Kliknij „Edytuj” przy …” na kotwicy całej karty: człowiek klika przycisk
  // z tekstu kroku, nie środek karty.
  const labels = [...stepText.matchAll(/„([^”]{1,40})”/g)].map((m) => m[1]);
  const deadline = Date.now() + 15_000;
  let why = "nie ma go na ekranie";
  while (Date.now() < deadline) {
    const first = page.locator(selector).first();
    if ((await page.locator(selector).count()) > 0) {
      await first.scrollIntoViewIfNeeded({ timeout: 2_000 }).catch(() => {});
    }
    const probe = await page.evaluate(({ sel, labels }) => {
      for (const anchorEl of Array.from(document.querySelectorAll(sel))) {
        const named = labels.length
          ? Array.from(anchorEl.querySelectorAll("button, a, [role=button], [role=tab]")).find((b) =>
              labels.some((l) => (b.textContent ?? "").trim().startsWith(l)),
            )
          : undefined;
        const el = named ?? anchorEl;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
        if ((el as HTMLButtonElement).disabled || el.getAttribute("aria-disabled") === "true") return "jest wyłączony";
        const y = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 2);
        for (const f of [0.5, 0.25, 0.75, 0.1, 0.9]) {
          const x = Math.min(Math.max(r.left + r.width * f, 1), innerWidth - 2);
          const hit = document.elementFromPoint(x, y);
          if (hit && (el.contains(hit) || hit.contains(el))) return { x, y };
          if (hit?.closest('[data-testid="lesson-solo"]')) return "zasłania go karta zadania";
        }
        return "coś go zasłania";
      }
      return document.querySelector(sel) ? "jest poza widokiem albo ma zerowy rozmiar" : "nie ma go na ekranie";
    }, { sel: selector, labels });
    if (typeof probe !== "string") return probe;
    why = probe;
    // Człowiek zwija kartę zadania, gdy zasłania element (przycisk „Zwiń”).
    if (probe === "zasłania go karta zadania") {
      await page.locator('[data-testid="lesson-solo"] button', { hasText: "Zwiń" }).click();
      continue;
    }
    // Przycisk czeka na treść (np. „Klient coś zmienił”: opis zmiany od
    // klienta) — człowiek ją wpisuje. Pole puste i widoczne, w oknie.
    if (probe === "jest wyłączony") {
      const field = page.locator('[role="dialog"] textarea:visible, [role="dialog"] input[type="text"]:visible').first();
      if ((await field.count()) > 0 && !(await field.inputValue())) {
        await field.fill("Klient dorzuca Pythona jako musi mieć, SAFe już nieważne.");
        continue;
      }
    }
    await page.waitForTimeout(400);
  }
  return why;
}

/**
 * Zadanie „wpisz NIP 111-222-33-32” albo „wpisz „…””: gdy po kroku kursor stoi
 * w pustym polu (paleta ⌘K), człowiek wpisuje wartość z treści zadania.
 */
async function typeFromTask(page: Page, task: string): Promise<void> {
  const value = task.match(/wpisz(?: NIP)? ([0-9][0-9-]{7,})/i)?.[1] ?? task.match(/wpisz „([^”]+)”/i)?.[1];
  if (!value) return;
  const empty = await page.evaluate(() => {
    const el = document.activeElement;
    return (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) && !el.readOnly && el.value === "";
  });
  if (!empty) return;
  await page.keyboard.type(value);
  await page.waitForTimeout(700);
}

const cases = LESSONS.filter((l) => l.check.kind !== "move")
  .filter((l) => !process.env.LESSONS_E2E_ONLY || process.env.LESSONS_E2E_ONLY.split(",").includes(l.id))
  .flatMap((lesson) => audienceRoles(lesson).map((role) => ({ lesson, role })));

test.describe("Lekcje nowości — etap „sam” drogą z pokazu", () => {
  test.describe.configure({ mode: "parallel" });

  for (const { lesson, role } of cases) {
    test(`${lesson.id} (${role})`, async ({ page, context, baseURL }) => {
      test.setTimeout(90_000);
      await page.setViewportSize({ width: 1280, height: 720 });
      const user = person(role);
      const origin = new URL(baseURL ?? "http://localhost:3000");
      const { events, misses } = await fakeBackend(page, origin.origin, user);
      const pageErrors: string[] = [];
      page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));

      const show = lesson.novelties
        .map((id) => NOVELTIES.get(id))
        .filter((n): n is NoveltyDef => Boolean(n))
        .map((n) => ({ ...n, steps: showSteps(n) }))
        .filter((n) => n.steps.length > 0);
      const run = {
        lesson: {
          id: lesson.id,
          title: lesson.title,
          task: lesson.task,
          solo_href: lesson.solo_href,
          check: lesson.check,
          questions: lesson.questions,
        },
        show,
        stage: "solo",
        showIndex: 0,
        review: false,
        origin: "daily",
        question: 0,
        wrongStreak: 0,
      };
      await context.addCookies([{ name: "nexus_access", value: fakeJwt(user), domain: origin.hostname, path: "/" }]);
      await context.addInitScript(
        ({ u, r }) => {
          window.localStorage.setItem("nexus_user", JSON.stringify(u));
          if (!window.sessionStorage.getItem("lessons-e2e")) {
            window.sessionStorage.setItem("lessons-e2e", "1");
            window.sessionStorage.setItem("nexus.poligon", "novelty");
            window.sessionStorage.setItem("nexus:lesson-run:v1", JSON.stringify(r));
          }
        },
        { u: user, r: run },
      );

      const route = soloPath(lesson);
      const known = KNOWN_GAPS.has(lesson.id) && !process.env.LESSONS_E2E_IGNORE_KNOWN;
      const where = `Lekcja „${lesson.title}” (${lesson.id}), rola ${role}, start ${lesson.solo_href}`;
      if (route === null && !known) {
        throw new Error(
          `${where}: zadanie każe kliknąć „${(lesson.check as { anchor: string }).anchor}”, a pokaz tego elementu nie wskazuje. ` +
            "Dopisz go jako krok wpisu lekcji (novelties.json) albo zmień warunek na element z pokazu.",
        );
      }

      await page.goto(lesson.solo_href);
      await expect(page.locator('[data-testid="lesson-solo"]')).toBeVisible({ timeout: 30_000 });
      const quiz = page.locator('[data-testid="lesson-quiz"]');

      const failures: string[] = [];
      for (const { anchor, text } of route ?? []) {
        if (await quiz.isVisible()) break;
        const point = await reach(page, anchor, text);
        if (typeof point === "string") {
          failures.push(`krok pokazu „${anchor}”: ${point}`);
          break;
        }
        await page.mouse.click(point.x, point.y);
        await page.waitForTimeout(700);
        await typeFromTask(page, lesson.task);
        if (process.env.LESSONS_E2E_SHOTS) {
          await page.screenshot({ path: test.info().outputPath(`krok-${anchor}.png`) });
        }
      }
      if (!failures.length && lesson.check.kind === "click" && !(await quiz.isVisible())) {
        const point = await reach(page, lesson.check.anchor);
        if (typeof point === "string") failures.push(`element z zadania „${lesson.check.anchor}”: ${point}`);
        else await page.mouse.click(point.x, point.y);
      }
      const passed = !failures.length && (await quiz.waitFor({ timeout: 10_000 }).then(() => true, () => false));
      if (!passed && !failures.length) failures.push("po drodze z pokazu etap „sam” się nie zaliczył");

      if (known) {
        expect(passed, `${where}: przechodzi już drogą z pokazu — usuń ją z KNOWN_GAPS`).toBe(false);
        return;
      }
      expect(
        failures,
        `${where}: etapu „sam” nie da się przejść drogą z pokazu. Odczyty bez odpowiedzi: ${[...misses].join(", ") || "—"}`,
      ).toEqual([]);
      expect(events).toContain(`${lesson.id}:solo_passed`);
      expect(pageErrors, `${where}: błąd strony`).toEqual([]);
    });
  }
});
