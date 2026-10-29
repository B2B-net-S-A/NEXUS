// Odczyt aktywnej karty LinkedIna — wyłącznie na żądanie panelu
// (otwarcie panelu, zmiana adresu karty, klik „Sprawdź tę stronę”).
//
// Nowy LinkedIn (2025/26) ma haszowane klasy, więc w karcie budujemy
// ustrukturyzowany zrzut TEKSTU żywej strony (`innerText` — podział na linie
// wynika z układu, którego kopia z DOMParsera nie ma): imię z pierwszego
// nagłówka, linie karty górnej, sekcje po nagłówkach, pozycje list. Czytniki
// (src/readers/text.js) parsują ten zrzut w panelu jako czyste funkcje.
// Kopia HTML (bez skryptów, obrazków i bloków <code> z danymi wewnętrznego API
// LinkedIna) jedzie obok jako zapas dla selektorów starszego układu.

import { CAPTURE, FOREIGN_REGIONS } from "./readers/selectors.js";
import { readPage } from "./readers/index.js";
import { PAGE_KINDS, detectPage } from "./readers/kinds.js";

/* Ta funkcja jest serializowana i uruchamiana w karcie — nie może używać
   niczego spoza swojego ciała i argumentu `cfg` (dane JSON). */
export async function capturePage(cfg) {
  const captureUrl = location.href;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // Starszy układ podaje tekst dwa razy (widoczny + dla czytnika ekranu), a
  // innerText skleja je bez separatora: „JavaJava”. Linia z dwóch równych połówek = jedna.
  const undouble = (s) => {
    const half = s.length / 2;
    return s.length >= 4 && Number.isInteger(half) && s.slice(0, half) === s.slice(half) ? s.slice(0, half).trim() : s;
  };
  const linesOf = (el) =>
    String((el && (el.innerText ?? el.textContent)) || "")
      .split("\n")
      .map((s) => undouble(s.replace(/\s+/g, " ").trim()))
      .filter(Boolean);
  const textOf = (el) => linesOf(el).join(" ");
  const isForeign = (el) => {
    try {
      return Boolean(el.closest(cfg.foreign));
    } catch {
      return false;
    }
  };
  const topLevel = (els) => els.filter((el) => !els.some((o) => o !== el && o.contains(el)));
  const isHidden = (el) => {
    for (let p = el; p; p = p.parentElement) {
      if (p.hasAttribute("hidden") || p.getAttribute("aria-hidden") === "true") return true;
      if (/(?:^|;)\s*display\s*:\s*none\s*(?:;|$)/i.test(p.getAttribute("style") || "")) return true;
    }
    return false;
  };

  let main = null;
  let profileScopeInvalid = false;
  if (cfg.recruiterProfile) {
    for (const sel of cfg.recruiterRoots) {
      const all = [...document.querySelectorAll(sel)];
      if (!all.length) continue;
      const active = all.filter((el) => !isHidden(el));
      if (active.length === 1) main = active[0];
      else profileScopeInvalid = true;
      break;
    }
  }
  if (!main && !profileScopeInvalid) {
    for (const sel of cfg.main) main = main || document.querySelector(sel);
    main = main || document.body;
    if (cfg.recruiterProfile && main.querySelector("[data-test-paginated-list-item], article.profile-list-item") && !cfg.recruiterTopCards.some((sel) => main.querySelector(sel))) profileScopeInvalid = true;
  }
  if (profileScopeInvalid) main = document.createElement("div");

  // Public-profile links can be rendered in a tooltip portal. Only portals
  // explicitly bound to the selected profile belong to this capture.
  let scopes = [main];
  if (cfg.recruiterProfile) {
    for (const trigger of main.querySelectorAll("[aria-controls], [aria-describedby]")) {
      const ids = `${trigger.getAttribute("aria-controls") || ""} ${trigger.getAttribute("aria-describedby") || ""}`.split(/\s+/).filter(Boolean);
      for (const id of ids) {
        const portal = document.getElementById(id);
        if (portal && portal.querySelector("a[href*='/in/']") && !isHidden(portal) && !scopes.includes(portal) && !main.contains(portal)) scopes.push(portal);
      }
    }
  }

  // Sekcje doładowują się dopiero po przewinięciu. Przewijamy kontener strony
  // (u LinkedIna to nie window) krokami, potem wracamy tam, gdzie był użytkownik.
  if (cfg.scroll && !profileScopeInvalid) {
    let scroller = cfg.recruiterProfile ? main : document.scrollingElement || document.documentElement;
    let best = scroller.scrollHeight - scroller.clientHeight;
    const candidates = cfg.recruiterProfile ? [main, ...main.querySelectorAll("*")] : [...document.querySelectorAll("body *")];
    if (cfg.recruiterProfile) {
      for (let p = main.parentElement; p && p !== document.body; p = p.parentElement) {
        candidates.push(p);
        if (p.matches(".profile-slidein__container")) break;
      }
    }
    for (const el of candidates) {
      const extra = el.scrollHeight - el.clientHeight;
      if (extra <= best || extra < 200) continue;
      const oy = getComputedStyle(el).overflowY;
      if (oy === "auto" || oy === "scroll") {
        scroller = el;
        best = extra;
      }
    }
    const start = scroller.scrollTop;
    const deadline = Date.now() + cfg.scrollBudgetMs;
    let pos = start;
    while (Date.now() + cfg.scrollPauseMs < deadline) {
      const max = scroller.scrollHeight - scroller.clientHeight;
      if (pos >= max) break;
      pos = Math.min(pos + cfg.scrollStepPx, max);
      scroller.scrollTop = pos;
      await sleep(cfg.scrollPauseMs);
    }
    scroller.scrollTop = start;
  }

  // A recruiter may change the selected person while lazy sections load.
  // Never pair the previous DOM identity with the next profile's address.
  if (cfg.recruiterProfile && (location.href !== captureUrl || !document.documentElement.contains(main))) {
    profileScopeInvalid = true;
    main = document.createElement("div");
    scopes = [main];
  }

  // Profil: imię to pierwszy h2 w main (zmierzone — h1 nie ma); starszy układ ma
  // imię w h1 karty górnej, a h2 to nagłówki sekcji, więc h1 w sekcji idzie pierwszy.
  // Recruiter: h1 albo h2.
  let heading = null;
  for (const sel of cfg.headingSelectors) {
    heading = heading || [...main.querySelectorAll(sel)].find((h) => !isForeign(h) && textOf(h)) || null;
  }
  const firstSection = main.querySelector("section");
  const recruiterTop = cfg.recruiterProfile && cfg.recruiterTopCards.map((sel) => main.querySelector(sel)).find(Boolean);
  const topEl = recruiterTop || (heading && heading.closest("section")) || firstSection || (heading && heading.parentElement);

  // Pozycje sekcji: separatory <hr> (zmierzone w doświadczeniu), potem role/listy.
  const itemsOf = (sec) => {
    const hrs = [...sec.querySelectorAll("hr")];
    if (hrs.length) {
      const depth = (el) => {
        let d = 0;
        for (let p = el; p && p !== sec; p = p.parentElement) d += 1;
        return d;
      };
      // Rodzic, którego dzieli najwięcej <hr>, to lista pozycji. Pojedynczy
      // <hr> płycej stoi przy stopce „Show all” (zmierzone 28.10.2026 — wybór
      // najpłytszego brał stopkę i zwracał jedną pozycję). Remis: płytszy, bo
      // wewnętrzne <hr> pozycji grupowej siedzą głębiej.
      const counts = new Map();
      for (const hr of hrs) {
        const c = hr.parentElement && hr.parentElement.parentElement;
        if (c && sec.contains(c)) counts.set(c, (counts.get(c) || 0) + 1);
      }
      const containers = [...counts.keys()];
      containers.sort((a, b) => counts.get(b) - counts.get(a) || depth(a) - depth(b));
      const box = containers[0];
      if (box) {
        const items = [...box.children].map(linesOf).filter((l) => l.length);
        if (items.length) return { by: "hr", items };
      }
    }
    for (const sel of cfg.sectionItems) {
      const els = topLevel([...sec.querySelectorAll(sel)]);
      const items = els.map(linesOf).filter((l) => l.length);
      if (items.length) return { by: sel, items };
    }
    return { by: null, items: [] };
  };

  const sections = [];
  const seen = new Set();
  for (const sec of main.querySelectorAll("section")) {
    if (sections.length >= cfg.maxSections) break;
    const h = sec.querySelector("h1, h2, h3");
    const { by, items } = itemsOf(sec);
    sections.push({ heading: h ? textOf(h) : "", lines: linesOf(sec), items, itemsBy: by });
    if (h) seen.add(h);
  }
  // Nagłówki poza <section> (Recruiter): blok = najbliższy przodek z treścią.
  for (const h of main.querySelectorAll("h2, h3")) {
    if (seen.has(h) || h.closest("section") || isForeign(h) || sections.length >= cfg.maxSections) continue;
    let block = h.parentElement;
    for (let i = 0; i < 4 && block && block !== main && linesOf(block).length < 4; i += 1) block = block.parentElement;
    if (!block) continue;
    const { by, items } = itemsOf(block);
    sections.push({ heading: textOf(h), lines: linesOf(block), items, itemsBy: by });
  }

  let listItems = [];
  for (const sel of cfg.listItems) {
    const els = topLevel([...main.querySelectorAll(sel)]).filter((el) => !isForeign(el) && el.querySelector(cfg.personLinks));
    if (els.length) {
      listItems = els.slice(0, cfg.maxListItems).map((el) => ({
        lines: linesOf(el),
        links: [...el.querySelectorAll(cfg.personLinks)].map((a) => a.href),
      }));
      break;
    }
  }

  const links = [...new Set(scopes.flatMap((scope) => [...scope.querySelectorAll("a[href*='/in/']")]))].slice(0, cfg.maxLinks).map((a) => ({
    href: a.href,
    text: textOf(a),
    label: [a.getAttribute("aria-label"), a.getAttribute("title"), a.matches(cfg.publicLinkSelectors) ? "Public profile" : ""].filter(Boolean).join(" "),
    foreign: isForeign(a),
    inTop: Boolean(topEl && topEl.contains(a)),
  }));

  let clone;
  if (cfg.recruiterProfile) {
    clone = document.documentElement.cloneNode(false);
    const body = document.createElement("body");
    for (const scope of scopes) body.appendChild(scope.cloneNode(true));
    clone.appendChild(body);
  } else clone = document.documentElement.cloneNode(true);
  clone
    .querySelectorAll("script, style, code, svg, img, picture, video, iframe, noscript, link, meta, template, canvas")
    .forEach((n) => n.remove());

  return {
    url: location.href,
    heading: heading ? { text: textOf(heading), level: /^H[1-6]$/.test(heading.tagName) ? Number(heading.tagName.slice(1)) : null } : null,
    top: { lines: linesOf(topEl) },
    sections,
    listItems,
    links,
    html: `<!doctype html>${clone.outerHTML}`,
    profileScopeInvalid,
  };
}

export function captureConfig(url) {
  const kind = detectPage(url).kind;
  return {
    ...CAPTURE,
    foreign: FOREIGN_REGIONS,
    recruiterProfile: kind === PAGE_KINDS.RECRUITER_PROFILE,
    scroll: kind === PAGE_KINDS.PROFILE || kind === PAGE_KINDS.RECRUITER_PROFILE,
    headingSelectors: kind === PAGE_KINDS.PROFILE ? ["section h1", "h2", "h1"] : kind === PAGE_KINDS.RECRUITER_PROFILE ? [...CAPTURE.recruiterNames, "h1, h2"] : ["h1, h2"],
  };
}

export async function captureTab(tabId, url) {
  const [injection] = await chrome.scripting.executeScript({ target: { tabId }, func: capturePage, args: [captureConfig(url)] });
  const snap = injection && injection.result;
  if (!snap || typeof snap.url !== "string") throw new Error("Pusta odpowiedź z karty");
  return snap;
}

/** Zrzut karty → wynik czytnika. `url` to adres karty (wybiera, czy przewijać). */
export async function readTab(tabId, url) {
  const snapshot = await captureTab(tabId, url);
  let doc = null;
  if (typeof snapshot.html === "string") {
    try {
      doc = new DOMParser().parseFromString(snapshot.html, "text/html");
    } catch {
      doc = null; // zapas HTML jest opcjonalny
    }
  }
  return readPage({ url: snapshot.url, snapshot, doc });
}
