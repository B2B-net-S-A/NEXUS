// Runtime responsiveness measurement. Usage: node measure.mjs <baseUrl> <outDir> [filter]
import { createRequire } from "module";
import fs from "fs";
import path from "path";
const require = createRequire(process.env.FRONTEND_DIR + "/package.json");
const { chromium } = require("@playwright/test");

const BASE = process.argv[2];
const OUT = process.argv[3];
const FILTER = process.argv[4] || "";
const WIDTHS = process.env.WIDTHS ? process.env.WIDTHS.split(",").map(Number) : [360, 390, 768, 1024, 1280, 1440, 1920];
const SHOT_WIDTHS = new Set([390, 768, 1280]);

const previews = fs
  .readdirSync(path.join(process.env.FRONTEND_DIR, "src/app/preview"))
  .filter((d) => fs.existsSync(path.join(process.env.FRONTEND_DIR, "src/app/preview", d, "page.tsx")))
  .filter((d) => !["cortex", "ds-kit"].includes(d)).sort();
const urls = [
  ...previews.map((p) => `/preview/${p}`),
  "/preview/candidate-profile?tab=recruitments",
  "/preview/candidate-profile?tab=activity",
  "/preview/candidate-profile?tab=documents",
  "/preview/candidates-list?dialog=1",
  "/preview/new-job?state=request",
  "/preview/new-job?state=gaps",
  "/preview/calendar-cycle?as=dl",
  "/preview/pipeline-v4?as=dl",
  "/login",
  "/register",
  "/kariera",
  "/kariera/rodo",
].filter((u) => u.includes(FILTER));

function slug(u) {
  return u.replace(/^\//, "").replace(/[/?=&]/g, "_") || "root";
}

async function measure(page, width) {
  return page.evaluate((width) => {
    const layoutVw = window.innerWidth;
    const vw = width; // nominal device width: mobile emulation widens the layout viewport to fit overflowing content
    const docOverflow = Math.max(document.documentElement.scrollWidth, layoutVw) - vw;
    const bodyOverflow = document.body ? document.body.scrollWidth - vw : 0;
    const sel = (el) => {
      const parts = [];
      let e = el;
      for (let i = 0; e && e.nodeType === 1 && i < 4; i++) {
        let s = e.tagName.toLowerCase();
        if (e.id) s += "#" + e.id;
        const tid = e.getAttribute("data-testid");
        if (tid) s += `[data-testid=${tid}]`;
        parts.unshift(s);
        e = e.parentElement;
      }
      return parts.join(" > ");
    };
    // Returns null (not clipped), "scroll" (inside auto/scroll container) or "hidden" (clipped by overflow hidden/clip), honoring containing blocks
    const clipKind = (el) => {
      let pos = getComputedStyle(el).position;
      let p = el.parentElement;
      let skipStatic = pos === "absolute";
      if (pos === "fixed") return null;
      while (p && p !== document.documentElement) {
        const cs = getComputedStyle(p);
        const positioned = cs.position !== "static" || cs.transform !== "none" || cs.contain.includes("paint") || cs.contain.includes("layout");
        if (!skipStatic || positioned) {
          if (["auto", "scroll"].includes(cs.overflowX)) return { kind: "scroll", anc: p };
          if (["hidden", "clip"].includes(cs.overflowX)) return { kind: "hidden", anc: p };
          if (cs.position === "fixed") return null;
          skipStatic = cs.position === "absolute";
        }
        p = p.parentElement;
      }
      return null;
    };
    const offenders = [];
    const hiddenClip = [];
    {
      for (const el of document.body.querySelectorAll("*")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === "hidden" || cs.display === "none") continue;
        const over = Math.max(r.right - vw, -r.left);
        if (over <= 1) continue;
        const ck = clipKind(el);
        if (ck && ck.kind === "scroll") continue;
        if (ck && ck.kind === "hidden") {
          const ar = ck.anc.getBoundingClientRect();
          // page-wide clipping container (e.g. main.overflow-x-hidden) hiding content beyond the viewport
          if (ar.width >= vw * 0.9 && r.right > vw + 8 && !String(ck.anc.className).includes("truncate")) {
            hiddenClip.push({ over: Math.round(r.right - vw), sel: sel(el), cls: String(el.getAttribute("class") || "").slice(0, 160), anc: sel(ck.anc) + " ." + String(ck.anc.getAttribute("class") || "").slice(0, 100), text: (el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 50), depth: (() => { let d = 0, q = el; while (q) { d++; q = q.parentElement; } return d; })() });
          }
          continue;
        }
        offenders.push({
          over: Math.round(over),
          side: r.right - vw > -r.left ? "right" : "left",
          sel: sel(el),
          cls: (typeof el.className === "string" ? el.className : el.getAttribute("class") || "").slice(0, 200),
          text: (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 60),
          w: Math.round(r.width),
          depth: (() => { let d = 0, p = el; while (p) { d++; p = p.parentElement; } return d; })(),
        });
      }
    }
    // keep the "root causes": for equal overflow, prefer the shallowest element that overflows but whose children... just sort by over desc, depth asc
    offenders.sort((a, b) => b.over - a.over || b.depth - a.depth);
    // dedupe by overflow amount: keep deepest element per over value (most specific) plus shallowest
    const byOver = new Map();
    for (const o of offenders) {
      const k = o.over;
      if (!byOver.has(k)) byOver.set(k, { deepest: o, shallowest: o, count: 0 });
      const g = byOver.get(k);
      g.count++;
      if (o.depth > g.deepest.depth) g.deepest = o;
      if (o.depth < g.shallowest.depth) g.shallowest = o;
    }
    const top = [...byOver.entries()].sort((a, b) => b[0] - a[0]).slice(0, 5).map(([over, g]) => ({ over, count: g.count, deepest: g.deepest, shallowest: g.shallowest }));

    let small = [], smallCount = 0, tinyText = 0, tinyTextEx = [], interactiveCount = 0;
    if (width === 390) {
      const inter = document.querySelectorAll('a[href], button, [role=button], input:not([type=hidden]), select, textarea, [role=tab], [role=checkbox], [role=switch]');
      for (const el of inter) {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (r.width === 0 || r.height === 0 || cs.visibility === "hidden") continue;
        if (r.bottom < 0 || r.top > document.documentElement.scrollHeight) continue;
        interactiveCount++;
        if (r.width < 32 || r.height < 32) {
          smallCount++;
          if (small.length < 6)
            small.push({ sel: sel(el), w: Math.round(r.width), h: Math.round(r.height), label: (el.getAttribute("aria-label") || el.innerText || el.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 40), cls: (typeof el.className === "string" ? el.className : "").slice(0, 120) });
        }
      }
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const seen = new Set();
      while (walker.nextNode()) {
        const t = walker.currentNode;
        if (!t.textContent.trim()) continue;
        const el = t.parentElement;
        if (!el || seen.has(el)) continue;
        seen.add(el);
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0) continue;
        const fs = parseFloat(cs.fontSize);
        if (fs < 11) {
          tinyText++;
          if (tinyTextEx.length < 4) tinyTextEx.push({ fs, text: t.textContent.trim().slice(0, 40), cls: (typeof el.className === "string" ? el.className : "").slice(0, 100) });
        }
      }
    }
    hiddenClip.sort((a, b) => b.over - a.over || a.depth - b.depth);
    const hiddenTop = hiddenClip.slice(0, 5);
    return { vw, layoutVw, hiddenClipCount: hiddenClip.length, hiddenTop, docOverflow, bodyOverflow, top, offendersCount: offenders.length, interactiveCount, smallCount, small, tinyText, tinyTextEx, title: document.title, bodyTextLen: (document.body.innerText || "").length, finalUrl: location.pathname + location.search };
  }, width);
}

const browser = await chromium.launch();
const results = [];
const resFile = path.join(OUT, process.env.RESFILE || `results${FILTER ? "-" + slug(FILTER) : ""}.json`);

async function runUrl(u) {
  for (const width of WIDTHS) {
    const mobile = width < 768;
    const ctx = await browser.newContext({ viewport: { width, height: 800 }, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e.message).slice(0, 200)));
    const t0 = Date.now();
    let rec = { url: u, width };
    try {
      await page.goto(BASE + u, { waitUntil: "networkidle", timeout: 60000 });
      await page.waitForTimeout(1500);
      const m = await measure(page, width);
      rec = { ...rec, ...m };
      if (SHOT_WIDTHS.has(width)) {
        const f = path.join(OUT, "shots", `${slug(u)}__${width}.png`);
        await page.screenshot({ path: f, fullPage: true, timeout: 30000 }).catch((e) => errors.push("shot:" + e.message));
        rec.shot = f;
      }
    } catch (e) {
      rec.error = String(e.message).slice(0, 300);
    }
    rec.pageErrors = errors;
    rec.ms = Date.now() - t0;
    results.push(rec);
    console.log(`${u} @${width}: overflow=${rec.docOverflow ?? "ERR"} ${rec.error ? rec.error.slice(0, 80) : ""} (${rec.ms}ms)`);
    await ctx.close();
  }
  fs.writeFileSync(resFile, JSON.stringify(results, null, 1));
}

// warm-up compile sequentially at one width, then run with concurrency 3
const queue = [...urls];
const workers = Array.from({ length: 4 }, async () => {
  while (queue.length) await runUrl(queue.shift());
});
await Promise.all(workers);
fs.writeFileSync(resFile, JSON.stringify(results, null, 1));
await browser.close();
console.log("DONE", results.length);
