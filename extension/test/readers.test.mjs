import { test } from "node:test";
import assert from "node:assert/strict";

import { loadFixture, parse } from "./helpers.mjs";
import { detectPage, readPage } from "../src/readers/index.js";
import { parseDateRange } from "../src/readers/dates.js";
import { slugContradictsName } from "../src/readers/dom.js";
import { splitTitleCompany } from "../src/readers/profile.js";

const read = (fixture, url) => readPage(loadFixture(fixture), url);

test("detectPage rozpoznaje obsługiwane strony LinkedIna", () => {
  const cases = [
    ["https://www.linkedin.com/in/zofia-testowa-123/", "profile"],
    ["https://www.linkedin.com/in/zofia-testowa-123/overlay/contact-info/", "profile"],
    ["https://www.linkedin.com/talent/profile/AEMAAFIKCJA?project=1", "recruiter_profile"],
    ["https://www.linkedin.com/talent/hire/555/discover/recruiterSearch/profile/AEMAAX", "recruiter_profile"],
    ["https://www.linkedin.com/talent/hire/555/manage/all/profile/AEMAAX", "recruiter_profile"],
    ["https://www.linkedin.com/search/results/people/?keywords=java", "search_results"],
    ["https://www.linkedin.com/talent/hire/555/discover/recruiterSearch?searchContextId=1", "search_results"],
    ["https://www.linkedin.com/talent/hire/555/manage/all", "search_results"],
    ["https://www.linkedin.com/feed/", "unsupported"],
    ["https://www.linkedin.com/search/results/companies/?keywords=x", "unsupported"],
    ["https://example.com/in/zofia", "unsupported"],
    ["http://www.linkedin.com/in/zofia", "unsupported"],
    [undefined, "unsupported"],
  ];
  for (const [url, kind] of cases) assert.equal(detectPage(url).kind, kind, url);
});

test("detectPage: klucz strony nie zależy od zapytania ani wielkości liter w slugu profilu", () => {
  assert.equal(detectPage("https://www.linkedin.com/in/Zofia-Testowa/?trk=x").key, detectPage("https://www.linkedin.com/in/zofia-testowa/").key);
  assert.notEqual(
    detectPage("https://www.linkedin.com/search/results/people/?keywords=java&page=1").key,
    detectPage("https://www.linkedin.com/search/results/people/?keywords=java&page=2").key,
  );
});

test("profil publiczny: wszystkie pola z selektorów", () => {
  const r = read("profile-public.html", "https://www.linkedin.com/in/zofia-testowa-123/");
  assert.equal(r.kind, "profile");
  assert.deepEqual(r.missing, []);
  const p = r.profile;
  assert.equal(p.page_kind, "profile");
  assert.equal(p.public_url, "https://www.linkedin.com/in/zofia-testowa-123");
  assert.equal(p.full_name, "Zofia Testowa");
  assert.equal(p.headline, "Senior Java Developer · Spring | Kotlin");
  assert.equal(p.location, "Kraków, Małopolskie, Polska");
  assert.equal(p.current_company, "Fikcyjna Software");
  assert.equal(p.current_title, "Senior Java Developer");
  assert.deepEqual(p.skills, ["Java", "Spring Boot", "Kotlin"]);
  assert.match(p.about, /systemy płatności/);
});

test("profil publiczny: doświadczenie, także kilka ról w jednej firmie", () => {
  const { profile } = read("profile-public.html", "https://www.linkedin.com/in/zofia-testowa-123/");
  assert.deepEqual(profile.experience, [
    { title: "Senior Java Developer", company: "Fikcyjna Software", start: "2022-03", end: null, current: true },
    { title: "Java Developer", company: "Przykładowy Bank SA", start: "2019-01", end: "2022-02", current: false },
    { title: "Junior Developer", company: "Przykładowy Bank SA", start: "2017-01", end: "2018-12", current: false },
  ]);
});

test("profil publiczny: nieznany układ — heurystyki (h1, linia po imieniu, miasto przed „Contact info”, nagłówek sekcji)", () => {
  const r = read("profile-public-unknown-layout.html", "https://www.linkedin.com/in/adam-wymyslony/");
  const p = r.profile;
  assert.equal(p.full_name, "Adam Wymyślony");
  assert.equal(p.headline, "Data Engineer at Nieistniejąca Analityka");
  assert.equal(p.location, "Gdańsk, Pomorskie, Poland");
  assert.equal(p.current_company, "Nieistniejąca Analityka");
  assert.equal(p.current_title, "Data Engineer");
  assert.equal(p.experience.length, 2);
  assert.deepEqual(p.experience[1], { title: "BI Analyst", company: "Fikcyjny Sklep", start: "2018-01", end: "2021-12", current: false });
  assert.deepEqual(r.missing, ["skills"]);
});

test("profil, który się jeszcze nie wczytał: lista brakujących pól zamiast zmyślonych wartości", () => {
  const r = read("profile-public-empty.html", "https://www.linkedin.com/in/x/");
  assert.equal(r.profile.full_name, null);
  for (const f of ["full_name", "headline", "current_title", "current_company", "location", "experience"]) {
    assert.ok(r.missing.includes(f), f);
  }
});

test("profil nie bierze imienia z nawigacji ani z „Inni oglądali też”", () => {
  const { profile } = read("profile-public.html", "https://www.linkedin.com/in/zofia-testowa-123/");
  assert.notEqual(profile.full_name, "Ktoś Inny");
  assert.ok(!JSON.stringify(profile).includes("rekruter-z-nawigacji"));
});

test("Recruiter: pola z atrybutów data-test i link do profilu publicznego", () => {
  const r = read("recruiter-profile.html", "https://www.linkedin.com/talent/profile/AEMAAFIKCJA?project=1");
  const p = r.profile;
  assert.equal(r.kind, "recruiter_profile");
  assert.equal(p.page_kind, "recruiter_profile");
  assert.equal(p.page_url, "https://www.linkedin.com/talent/profile/AEMAAFIKCJA?project=1");
  assert.equal(p.public_url, "https://www.linkedin.com/in/ewa-przykladowa-42");
  assert.equal(p.full_name, "Ewa Przykładowa");
  assert.equal(p.headline, "QA Automation Engineer | Playwright");
  assert.equal(p.location, "Wrocław, Dolnośląskie, Polska");
  assert.equal(p.current_company, "Testerzy Bez Granic");
  assert.equal(p.current_title, "QA Automation Engineer");
  assert.deepEqual(p.skills, ["Playwright", "TypeScript"]);
  assert.equal(p.experience[1].start, "2019-09");
  assert.equal(p.experience[1].end, "2023-03");
});

test("Recruiter bez linku publicznego: public_url pusty, nie link z nawigacji ani z „podobnych”", () => {
  const r = read("recruiter-profile-no-public-link.html", "https://www.linkedin.com/talent/hire/555/discover/recruiterSearch/profile/AEMAAX");
  assert.equal(r.profile.full_name, "Piotr Zmyślony");
  assert.equal(r.profile.public_url, null);
  assert.ok(r.missing.includes("public_url"));
});

test("Recruiter: link „Profil publiczny” po etykiecie, odrzucony gdy slug przeczy nazwisku", () => {
  const ok = parse(`<main><div class="topcard"><h1>Ewa Przykładowa</h1></div>
    <a href="https://www.linkedin.com/in/ewa-przykladowa/">Profil publiczny</a></main>`);
  assert.equal(readPage(ok, "https://www.linkedin.com/talent/profile/AEMA1").profile.public_url, "https://www.linkedin.com/in/ewa-przykladowa");

  const wrong = parse(`<main><div class="topcard"><h1>Ewa Przykładowa</h1></div>
    <a href="https://www.linkedin.com/in/marek-zupelnie-ktos/">Profil publiczny</a></main>`);
  assert.equal(readPage(wrong, "https://www.linkedin.com/talent/profile/AEMA1").profile.public_url, null);
});

test("wyniki wyszukiwania: osoby, linki publiczne, bez „Członka LinkedIn” i bez duplikatów", () => {
  const r = read("search-results.html", "https://www.linkedin.com/search/results/people/?keywords=java");
  assert.equal(r.kind, "search_results");
  assert.equal(r.source, "search");
  assert.equal(r.skipped, 1);
  assert.deepEqual(
    r.people.map((p) => [p.full_name, p.public_url, p.headline, p.current_company, p.location]),
    [
      ["Marta Fikcyjna", "https://www.linkedin.com/in/marta-fikcyjna", "Frontend Developer at Wymyślone Studio", "Wymyślone Studio", "Poznań"],
      ["Tomasz Testowy", "https://www.linkedin.com/in/tomasz-testowy-77", "Backend Engineer | Go", null, "Łódź"],
    ],
  );
  assert.deepEqual(r.people[1].missing, ["current_company"]);
});

test("wyszukiwanie w Recruiterze w nieznanym układzie: heurystyka po linkach do profili", () => {
  const r = read("recruiter-search-unknown-layout.html", "https://www.linkedin.com/talent/hire/555/discover/recruiterSearch?searchContextId=1");
  assert.equal(r.source, "recruiter_search");
  assert.deepEqual(r.people.map((p) => p.full_name), ["Karol Nieprawdziwy", "Olga Testerska"]);
  assert.equal(r.people[0].headline, "Python Developer · Wymyślona Fintech");
  assert.equal(r.people[1].current_company, "Fikcyjne Ubezpieczenia");
  assert.equal(r.people[0].public_url, null);
});

test("lista: najwyżej 50 osób", () => {
  const items = Array.from({ length: 60 }, (_, i) => `<li class="reusable-search__result-container"><span class="entity-result__title-text"><a href="https://www.linkedin.com/in/osoba-fikcyjna-${i}/"><span aria-hidden="true">Osoba Fikcyjna ${i}</span></a></span><div class="entity-result__primary-subtitle">Tester</div></li>`).join("");
  const r = readPage(parse(`<main><ul>${items}</ul></main>`), "https://www.linkedin.com/search/results/people/?keywords=x");
  assert.equal(r.people.length, 50);
  assert.equal(r.truncated, true);
});

test("parseDateRange: polskie i angielskie zakresy, sam rok, „obecnie”", () => {
  assert.deepEqual(parseDateRange("mar 2022 – obecnie · 2 lata 8 mies."), { start: "2022-03", end: null, current: true });
  assert.deepEqual(parseDateRange("Jan 2018 - Dec 2021 · 4 yrs"), { start: "2018-01", end: "2021-12", current: false });
  assert.deepEqual(parseDateRange("paź 2020 – lis 2021"), { start: "2020-10", end: "2021-11", current: false });
  assert.deepEqual(parseDateRange("2015 - 2019"), { start: "2015-01", end: "2019-12", current: false });
  assert.deepEqual(parseDateRange("Sep 2023 - Present"), { start: "2023-09", end: null, current: true });
  assert.equal(parseDateRange("Kraków, Polska · Hybrydowo"), null);
  assert.equal(parseDateRange("Pełny etat · 5 lat"), null);
});

test("splitTitleCompany i slugContradictsName", () => {
  assert.deepEqual(splitTitleCompany("Senior Dev at Fikcyjna Firma | Java"), { title: "Senior Dev", company: "Fikcyjna Firma" });
  assert.deepEqual(splitTitleCompany("Tester w Wymyślonej Firmie"), { title: "Tester", company: "Wymyślonej Firmie" });
  assert.deepEqual(splitTitleCompany("Backend Engineer | Go"), { title: null, company: null });
  assert.equal(slugContradictsName("ewa-przykladowa-42", "Ewa Przykładowa"), false);
  assert.equal(slugContradictsName("marek-ktos", "Ewa Przykładowa"), true);
  assert.equal(slugContradictsName("ACoAAABcdef", "Ewa Przykładowa"), false);
  assert.equal(slugContradictsName("12345", "Ewa Przykładowa"), false);
});
