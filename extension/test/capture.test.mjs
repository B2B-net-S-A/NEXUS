// `capturePage` (funkcja wstrzykiwana do karty) na syntetycznym DOM-ie
// w układzie zmierzonym na LinkedInie 28.10.2026: haszowane klasy, imię w h2,
// pozycje doświadczenia rozdzielone <hr>, wyniki w [role=list] [role=listitem].
// linkedom nie liczy układu, więc `innerText` zastępujemy prostym podziałem
// na linie po elementach blokowych — to wystarcza do sprawdzenia struktury zrzutu.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { parseHTML } from "linkedom";

let capturePage, captureConfig, readPage;

const BLOCK = new Set(["DIV", "P", "SECTION", "LI", "UL", "OL", "H1", "H2", "H3", "HR", "ARTICLE", "MAIN", "HEADER", "NAV", "ASIDE", "TR", "TABLE", "BUTTON"]);

function layoutText(node) {
  if (node.nodeType === 3) return node.textContent;
  if (node.nodeType !== 1) return "";
  const inner = [...node.childNodes].map(layoutText).join("");
  return BLOCK.has(node.tagName) ? `\n${inner}\n` : inner;
}

function load(html, url) {
  const { window, document } = parseHTML(html);
  Object.defineProperty(window.HTMLElement.prototype, "innerText", {
    configurable: true,
    get() {
      return layoutText(this).replace(/\n\s*\n+/g, "\n").trim();
    },
  });
  globalThis.document = document;
  globalThis.location = { href: url };
}

before(async () => {
  ({ capturePage, captureConfig } = await import("../src/page.js"));
  ({ readPage } = await import("../src/readers/index.js"));
});

const PROFILE_URL = "https://www.linkedin.com/in/zofia-testowa-123/";
const PROFILE_HTML = `<!doctype html><html><body>
<header><nav><a href="https://www.linkedin.com/in/rekruter-z-nawigacji/">Ja</a></nav></header>
<main class="a1b2">
  <section class="x9f">
    <div class="q1"><h2 class="k7">Zofia Testowa</h2><span class="p3">She/Her</span><span class="p4"> · 2nd</span></div>
    <div class="z8">Senior Java Developer · Spring | Kotlin</div>
    <div class="z9"><span>Kraków, Małopolskie, Poland</span><span><div>·</div></span><a href="#">Contact info</a></div>
    <ul class="c1"><li><button>Fikcyjna Software</button></li><li><button>Politechnika Wymyślona</button></li></ul>
    <div>500+ connections</div>
    <button>Connect</button><button>Message</button><button>More</button>
  </section>
  <section componentkey="about"><div><h2>About</h2></div><div><span>Buduję systemy płatności w Javie od 2016 roku.</span></div></section>
  <section componentkey="experience">
    <div class="h"><h2>Experience</h2></div>
    <div class="list7">
      <div class="it"><div class="r"><p>Senior Java Developer</p><p>Fikcyjna Software · Full-time</p><p>May 2023 - Present · 3 yrs 6 mos</p><p>Kraków, Poland · Hybrid</p></div></div>
      <div class="it"><hr role="presentation"><div class="r">
        <p>Przykładowy Bank SA</p><p>Full-time · 4 yrs</p>
        <div class="roles">
          <div class="role"><p>Java Developer</p><p>May 2019 - Apr 2023 · 4 yrs</p><p>Warsaw, Poland</p></div>
          <div class="role"><hr role="presentation"><p>Junior Java Developer</p><p>Oct 2017 - May 2019 · 1 yr 8 mos</p></div>
        </div>
      </div></div>
      <div class="it"><hr role="presentation"><div class="r"><p>Stażystka</p><p>Wymyślony Software House · Internship</p><p>Jan 2017 - Sep 2017 · 9 mos</p></div></div>
    </div>
    <div><hr role="presentation"><div><a href="#">Show all 6 experiences</a></div></div>
  </section>
  <section><div><h2>Skills</h2></div><div class="sk">
    <div class="s"><p>Java</p><p>Endorsed by Anna Fikcyjna and 3 others</p></div>
    <div class="s"><hr role="presentation"><p>Spring Boot</p></div>
  </div></section>
</main>
<aside><a href="https://www.linkedin.com/in/ktos-inny/">Ktoś Inny</a></aside>
</body></html>`;

test("zrzut profilu: imię z pierwszego h2, linie karty górnej, sekcje i pozycje po <hr>", async () => {
  load(PROFILE_HTML, PROFILE_URL);
  const snap = await capturePage({ ...captureConfig(PROFILE_URL), scroll: false });
  assert.equal(snap.url, PROFILE_URL);
  assert.deepEqual(snap.heading, { text: "Zofia Testowa", level: 2 });
  assert.ok(snap.top.lines.includes("Contact info"));
  const exp = snap.sections.find((s) => s.heading === "Experience");
  assert.equal(exp.itemsBy, "hr");
  assert.equal(exp.items.length, 3, "trzy pozycje — wewnętrzny <hr> grupy nie dzieli listy");
  assert.equal(exp.items[1][0], "Przykładowy Bank SA");
  assert.ok(!snap.html.includes("<script"));
});

test("zrzut profilu → czytnik: komplet pól, także pozycja grupowa", async () => {
  load(PROFILE_HTML, PROFILE_URL);
  const snap = await capturePage({ ...captureConfig(PROFILE_URL), scroll: false });
  const { profile, missing } = readPage({ url: snap.url, snapshot: snap });
  assert.equal(profile.full_name, "Zofia Testowa");
  assert.equal(profile.headline, "Senior Java Developer · Spring | Kotlin");
  assert.equal(profile.location, "Kraków, Małopolskie, Poland");
  assert.equal(profile.current_company, "Fikcyjna Software");
  assert.equal(profile.current_title, "Senior Java Developer");
  assert.deepEqual(
    profile.experience.map((e) => [e.title, e.company, e.start, e.end]),
    [
      ["Senior Java Developer", "Fikcyjna Software", "2023-05", null],
      ["Java Developer", "Przykładowy Bank SA", "2019-05", "2023-04"],
      ["Junior Java Developer", "Przykładowy Bank SA", "2017-10", "2019-05"],
      ["Stażystka", "Wymyślony Software House", "2017-01", "2017-09"],
    ],
  );
  assert.deepEqual(profile.skills, ["Java", "Spring Boot"]);
  assert.deepEqual(missing, []);
});

test("zrzut listy wyników: pozycje z [role=list] [role=listitem] z linkami /in/", async () => {
  const url = "https://www.linkedin.com/search/results/people/?keywords=java";
  load(
    `<main><div role="list">
      <div role="listitem"><div><a componentkey="k1" href="https://www.linkedin.com/in/marta-fikcyjna?mini=1"><p>Marta Fikcyjna</p></a><p>• 2nd</p></div>
        <p>Frontend Developer | React</p><p>Poznań</p><button>Connect</button><p>Current: Senior Frontend Developer at Wymyślone Studio</p></div>
      <div role="listitem"><div><a href="https://www.linkedin.com/in/tomasz-testowy-77/"><p>Tomasz Testowy</p></a></div><p>Backend Engineer at Nieistniejący Bank</p><p>Łódź</p><button>Follow</button></div>
    </div></main>`,
    url,
  );
  const snap = await capturePage(captureConfig(url));
  assert.equal(snap.listItems.length, 2);
  const r = readPage({ url, snapshot: snap });
  assert.deepEqual(
    r.people.map((p) => [p.full_name, p.public_url, p.current_company, p.location]),
    [
      ["Marta Fikcyjna", "https://www.linkedin.com/in/marta-fikcyjna", "Wymyślone Studio", "Poznań"],
      ["Tomasz Testowy", "https://www.linkedin.com/in/tomasz-testowy-77", "Nieistniejący Bank", "Łódź"],
    ],
  );
});

test("captureConfig: przewijanie tylko na profilach, imię z h2 na profilu publicznym", () => {
  assert.equal(captureConfig(PROFILE_URL).scroll, true);
  assert.deepEqual(captureConfig(PROFILE_URL).headingSelectors, ["h2", "h1"]);
  assert.equal(captureConfig("https://www.linkedin.com/talent/profile/AEMA1").scroll, true);
  assert.equal(captureConfig("https://www.linkedin.com/search/results/people/?k=1").scroll, false);
  assert.ok(captureConfig(PROFILE_URL).scrollBudgetMs <= 4000);
});
