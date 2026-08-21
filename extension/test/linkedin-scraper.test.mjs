// Testy jednostkowe rozwiązywania kanonicznego URL-a profilu LinkedIn.
//
// DLACZEGO akurat tu: regresja w tej ścieżce jest CICHA. Wtyczka wysyła
// `linkedin_url` obcej osoby, podgląd pokazuje właściwe nazwisko (idzie z
// innego źródła), backend deduplikuje WYŁĄCZNIE po URL-u, a Proxycurl
// nadpisuje potem firmę/stanowisko/historię danymi tej obcej osoby. Nic tego
// nie sygnalizuje — dlatego reguły wyboru slugu muszą być przybite testem.
//
// Uruchomienie (zero zależności, wbudowany runner Node >= 18):
//   node --test extension/test/*.test.mjs
//
// Moduł ładujemy przez data: URL, bo `extension/` nie ma `package.json`, więc
// `import` pliku `.js` potraktowałby go jako CommonJS.

import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const src = await readFile(
  new URL("../src/content/linkedin-scraper.js", import.meta.url),
  "utf8",
);
const scraper = await import(
  "data:text/javascript;base64," + Buffer.from(src, "utf8").toString("base64")
);

const {
  collectSlugsFromRoots,
  nameTokens,
  slugIsOpaque,
  slugContradictsName,
  pickCanonicalSlug,
} = scraper;

/** Minimalna atrapa kotwicy: tyle DOM-u, ile kod faktycznie dotyka. */
function anchor(href, { foreignRegion = false } = {}) {
  return {
    getAttribute: (name) => (name === "href" ? href : null),
    closest: () => (foreignRegion ? {} : null),
  };
}

function root(anchors) {
  return { querySelectorAll: () => anchors };
}

// ── collectSlugsFromRoots ────────────────────────────────────────────────────

test("zbiera slugi z URL-i bezwzględnych i względnych, bez duplikatów", () => {
  const slugs = collectSlugsFromRoots(
    [
      root([
        anchor("https://www.linkedin.com/in/anna-nowak-123/"),
        anchor("/in/anna-nowak-123"),
        anchor("https://www.linkedin.com/in/jan-kowalski?trk=x"),
        anchor("https://www.linkedin.com/company/acme/"),
      ]),
    ],
    false,
  );
  assert.deepEqual(slugs, ["anna-nowak-123", "jan-kowalski"]);
});

test("odsiewa kotwice z nawigacji i „podobnych profili”, gdy pas tego wymaga", () => {
  const anchors = [
    anchor("/in/operator-wtyczki", { foreignRegion: true }),
    anchor("/in/anna-nowak"),
  ];
  assert.deepEqual(collectSlugsFromRoots([root(anchors)], true), ["anna-nowak"]);
  // Bez odsiewania (pas „wewnątrz karty profilu”) kolejność dokumentu wraca.
  assert.deepEqual(collectSlugsFromRoots([root(anchors)], false), [
    "operator-wtyczki",
    "anna-nowak",
  ]);
});

test("korzeń bez querySelectorAll jest pomijany, nie wysadza całości", () => {
  assert.deepEqual(
    collectSlugsFromRoots([null, undefined, root([anchor("/in/anna-nowak")])], true),
    ["anna-nowak"],
  );
});

// ── tokeny nazwiska / nieprzezroczystość slugu ───────────────────────────────

test("tokeny nazwiska zdejmują polskie diakrytyki (także ł, które nie ma NFD)", () => {
  assert.deepEqual(nameTokens("Paweł Wiśniewski"), ["pawel", "wisniewski"]);
  assert.deepEqual(nameTokens("Łukasz Żółć"), ["lukasz", "zolc"]);
});

test("tokeny krótsze niż 3 znaki są pomijane — brak dowodu zamiast złego dowodu", () => {
  assert.deepEqual(nameTokens("Li Wu"), []);
  assert.deepEqual(nameTokens("Jan de Vries"), ["jan", "vries"]);
});

test("slug oparty o member-id i slug numeryczny są nieprzezroczyste", () => {
  assert.equal(slugIsOpaque("ACoAAABcDeFgHiJk"), true);
  assert.equal(slugIsOpaque("12345678"), true);
  assert.equal(slugIsOpaque(""), true);
  assert.equal(slugIsOpaque("anna-nowak"), false);
});

// ── sprzeczność slug ↔ nazwisko ──────────────────────────────────────────────

test("sprzeczność orzekana tylko przy pozytywnym dowodzie", () => {
  // Zgodny slug.
  assert.equal(slugContradictsName("anna-nowak-12345", "Anna Nowak"), false);
  // Zgodny po zdjęciu diakrytyków.
  assert.equal(slugContradictsName("pawel-wisniewski", "Paweł Wiśniewski"), false);
  // Sam nazwisko w slugu wystarczy (imię zdrobniałe / panieńskie).
  assert.equal(slugContradictsName("nowak-anna-dev", "Ania Nowak"), false);
  // Cudza osoba — to jest ten cichy błąd.
  assert.equal(slugContradictsName("jan-kowalski", "Anna Nowak"), true);
  // Brak nazwiska = brak dowodu.
  assert.equal(slugContradictsName("jan-kowalski", null), false);
  // Nieprzezroczysty slug = brak dowodu.
  assert.equal(slugContradictsName("ACoAAABcDeFgHiJk", "Anna Nowak"), false);
});

// ── wybór slugu ──────────────────────────────────────────────────────────────

test("pierwszeństwo ma slug zgodny z nazwiskiem, a nie pierwszy w dokumencie", () => {
  // Dokładnie regresja z findingu: link operatora/„podobnego profilu” stoi
  // pierwszy w kolejności dokumentu.
  assert.equal(
    pickCanonicalSlug(["operator-rekruter", "anna-nowak-77"], "Anna Nowak"),
    "anna-nowak-77",
  );
});

test("jeden kandydat przechodzi mimo nietypowego vanity-slugu", () => {
  // Fałszywe odrzucenie kosztuje ręczne wklejanie URL-a przy KAŻDYM profilu,
  // a przy jednym linku nie ma z czego wybrać źle.
  assert.equal(pickCanonicalSlug(["iamthebestdev"], "Anna Nowak"), "iamthebestdev");
});

test("kilku kandydatów i żaden nie pasuje → null, nie losowanie", () => {
  assert.equal(
    pickCanonicalSlug(["operator-rekruter", "jan-kowalski"], "Anna Nowak"),
    null,
  );
});

test("brak slugów → null", () => {
  assert.equal(pickCanonicalSlug([], "Anna Nowak"), null);
  assert.equal(pickCanonicalSlug(undefined, "Anna Nowak"), null);
});

test("bez nazwiska zachowana jest stara kolejność dokumentu", () => {
  assert.equal(pickCanonicalSlug(["a-slug", "b-slug"], null), "a-slug");
});

// ── Ścieżka end-to-end na Sales Navigatorze ──────────────────────────────────
// Unit-testy wyżej pilnują reguł wyboru; ten test pilnuje, że reguły są w
// ogóle podpięte — czyli że zawężenie do karty profilu i kontrola krzyżowa
// działają na tej powierzchni, na której powstawał cichy zapis na złą osobę.

function el(text) {
  return { textContent: text, getAttribute: () => null };
}

function installDom({ pathname, title, nodes, documentAnchors, mainAnchors }) {
  const main = mainAnchors ? root(mainAnchors) : null;
  globalThis.location = {
    pathname,
    href: `https://www.linkedin.com${pathname}`,
  };
  globalThis.document = {
    title,
    body: root([]),
    querySelector: (sel) => {
      if (sel === "main") return main;
      return Object.prototype.hasOwnProperty.call(nodes, sel) ? nodes[sel] : null;
    },
    querySelectorAll: () => documentAnchors,
  };
}

test("Sales Navigator: wygrywa kotwica z karty profilu, nie pierwsza w dokumencie", () => {
  installDom({
    pathname: "/sales/lead/ABC123,NAME_SEARCH",
    title: "Anna Nowak | LinkedIn",
    nodes: {
      '[data-anonymize="person-name"]': el("Anna Nowak"),
      "#profile-card-section": root([anchor("/in/anna-nowak-77")]),
    },
    // W dokumencie pierwszy jest link operatora — dokładnie to brał stary kod.
    documentAnchors: [anchor("/in/operator-rekruter"), anchor("/in/anna-nowak-77")],
  });
  assert.equal(
    scraper.getProfileUrl(),
    "https://www.linkedin.com/in/anna-nowak-77/",
  );
});

test("Sales Navigator: bez karty profilu sprzeczne slugi dają widoczną awarię, nie cudzy profil", () => {
  installDom({
    pathname: "/sales/lead/ABC123,NAME_SEARCH",
    title: "Anna Nowak | LinkedIn",
    nodes: { '[data-anonymize="person-name"]': el("Anna Nowak") },
    documentAnchors: [anchor("/in/operator-rekruter"), anchor("/in/jan-kowalski")],
  });
  // Fallback na URL strony /sales/ — backend odpowiada czytelnym 400
  // („Expected a 'linkedin.com/in/<slug>' profile link”), czyli awarią, którą
  // widać. Wysłanie „jan-kowalski” byłoby zapisem, którego NIE widać.
  assert.equal(
    scraper.getProfileUrl(),
    "https://www.linkedin.com/sales/lead/ABC123,NAME_SEARCH",
  );
});

test("publiczny profil dalej rozstrzyga się z samego URL-a", () => {
  installDom({
    pathname: "/in/anna-nowak-77/",
    title: "Anna Nowak | LinkedIn",
    nodes: {},
    documentAnchors: [anchor("/in/ktos-inny")],
  });
  assert.equal(
    scraper.getProfileUrl(),
    "https://www.linkedin.com/in/anna-nowak-77/",
  );
});
