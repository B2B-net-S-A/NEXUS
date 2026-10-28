// Czytniki zrzutu tekstu (główna ścieżka) na syntetycznych zrzutach, które
// odtwarzają sekwencje linii zmierzone na LinkedInie 28.10.2026 — z wymyślonymi
// osobami i firmami (repo jest publiczne).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { readPage, mergeProfiles } from "../src/readers/index.js";
import { isDurationOrTypeLine, isNoiseLine, parseExperienceFlat, parseExperienceItem, parseListItem, parseTopCard } from "../src/readers/text.js";
import { loadFixture } from "./helpers.mjs";

const snap = (name) => JSON.parse(readFileSync(new URL(`./fixtures/text/${name}`, import.meta.url), "utf8"));
const read = (name, doc = null) => {
  const s = snap(name);
  return readPage({ url: s.url, snapshot: s, doc });
};

test("karta górna: imię z h2, nagłówek po zaimkach i „· 2nd”, miasto przed „Contact info”", () => {
  const top = parseTopCard(snap("profile-other.json"));
  assert.deepEqual(top, {
    name: "Zofia Testowa",
    headline: "Senior Java Developer · Spring | Kotlin",
    location: "Kraków, Małopolskie, Poland",
    companyAfterContact: "Fikcyjna Software",
  });
});

test("karta górna własnego profilu: „Enhance cover image” przed imieniem, „Dane kontaktowe” po polsku", () => {
  const top = parseTopCard(snap("profile-own-pl-flat.json"));
  assert.equal(top.name, "Ewa Przykładowa");
  assert.equal(top.headline, "Analityczka biznesowa w Fikcyjnej Firmie");
  assert.equal(top.location, "Wrocław, Dolnośląskie, Polska");
});

test("profil: komplet pól, doświadczenie z pozycją grupową, umiejętności bez „Endorsed by…”", () => {
  const r = read("profile-other.json");
  const p = r.profile;
  assert.equal(r.kind, "profile");
  assert.deepEqual(r.missing, []);
  assert.equal(p.public_url, "https://www.linkedin.com/in/zofia-testowa-123");
  assert.equal(p.current_company, "Fikcyjna Software");
  assert.equal(p.current_title, "Senior Java Developer");
  assert.deepEqual(p.experience, [
    { title: "Senior Java Developer", company: "Fikcyjna Software", start: "2023-05", end: null, current: true },
    { title: "Java Developer", company: "Przykładowy Bank SA", start: "2019-05", end: "2023-04", current: false },
    { title: "Junior Java Developer", company: "Przykładowy Bank SA", start: "2017-10", end: "2019-05", current: false },
    { title: "Stażystka", company: "Wymyślony Software House", start: "2017-01", end: "2017-09", current: false },
  ]);
  assert.deepEqual(p.skills, ["Java", "Spring Boot"]);
  assert.equal(p.about, "Buduję systemy płatności w Javie od 2016 roku.\nLubię porządne testy.");
});

test("profil nieprzewinięty (bez sekcji): karta górna jest, doświadczenie i umiejętności zgłoszone jako brakujące", () => {
  const r = read("profile-not-scrolled.json");
  assert.equal(r.profile.full_name, "Adam Wymyślony");
  assert.equal(r.profile.headline, "Data Engineer at Nieistniejąca Analityka");
  assert.equal(r.profile.location, "Gdańsk, Pomorskie, Poland");
  assert.equal(r.profile.current_company, "Nieistniejąca Analityka"); // pierwsza linia po „Contact info”
  assert.equal(r.profile.current_title, "Data Engineer"); // z nagłówka „… at …”
  assert.deepEqual(r.profile.experience, []);
  assert.deepEqual(r.missing, ["experience", "skills"]);
});

test("doświadczenie bez <hr> (zapas): podział po liniach dat, także grupa po polsku", () => {
  const r = read("profile-own-pl-flat.json");
  assert.deepEqual(
    r.profile.experience.map((e) => [e.title, e.company, e.start, e.end, e.current]),
    [
      ["Analityczka biznesowa", "Fikcyjna Firma", "2023-05", null, true],
      ["Starsza analityczka", "Testowe Usługi", "2020-01", "2023-04", false],
      ["Młodsza analityczka", "Testowe Usługi", "2018-03", "2019-12", false],
    ],
  );
  assert.deepEqual(r.profile.skills, ["SQL", "Power BI"]);
});

test("pozycja doświadczenia: zwykła, grupowa, sama data", () => {
  assert.deepEqual(parseExperienceItem(["Tester", "Fikcyjna Firma", "Jan 2020 - Dec 2021 · 2 yrs", "Opis projektu.", "zrzut.jpg"]), [
    { title: "Tester", company: "Fikcyjna Firma", start: "2020-01", end: "2021-12", current: false },
  ]);
  assert.deepEqual(
    parseExperienceItem(["Grupa Testowa", "3 yrs 2 mos", "Lead", "Full-time", "Jan 2023 - Present · 1 yr", "Dev", "Sep 2020 - Dec 2022 · 2 yrs 4 mos"]).map((e) => [e.title, e.company, e.start]),
    [
      ["Lead", "Grupa Testowa", "2023-01"],
      ["Dev", "Grupa Testowa", "2020-09"],
    ],
  );
  assert.deepEqual(parseExperienceItem(["Właścicielka", "Jednoosobowa Fikcja"]), [{ title: "Właścicielka", company: "Jednoosobowa Fikcja", start: null, end: null, current: false }]);
  assert.deepEqual(parseExperienceFlat(["Experience"], "Experience"), []);
});

test("szum i linie czasu trwania", () => {
  for (const l of ["·", "· 2nd", "• 3rd+", "She/Her", "She/Her · 2nd", "Contact info".replace("Contact info", "Connect"), "Show all 24 skills", "Endorsed by Anna Fikcyjna and 3 others", "12 endorsements", "Jan Testowy is a mutual connection", "500+ connections", "Enhance cover image", "Open to", "Add section", "Resources", "More", "Edit", "Pokaż wszystkie umiejętności (12)"]) {
    assert.equal(isNoiseLine(l), true, l);
  }
  for (const l of ["Senior Java Developer", "Kraków, Poland", "Java", "Fikcyjna Software"]) assert.equal(isNoiseLine(l), false, l);
  assert.equal(isDurationOrTypeLine("Full-time · 3 yrs 2 mos"), true);
  assert.equal(isDurationOrTypeLine("Pełny etat · 5 lat"), true);
  assert.equal(isDurationOrTypeLine("May 2019 - Apr 2023 · 4 yrs"), false);
  assert.equal(isDurationOrTypeLine("Fikcyjna Software · Full-time"), false);
});

test("lista wyników: imię, nagłówek, miasto, firma z „Current: … at …”, bez „LinkedIn Member”", () => {
  const r = read("search-people.json");
  assert.equal(r.kind, "search_results");
  assert.equal(r.skipped, 1);
  assert.deepEqual(
    r.people.map((p) => [p.full_name, p.public_url, p.headline, p.location, p.current_company]),
    [
      ["Marta Fikcyjna", "https://www.linkedin.com/in/marta-fikcyjna", "Frontend Developer | React", "Poznań, Wielkopolskie, Poland", "Wymyślone Studio"],
      ["Tomasz Testowy", "https://www.linkedin.com/in/tomasz-testowy-77", "Backend Engineer at Nieistniejący Bank", "Łódź", "Nieistniejący Bank"],
      ["Olga Testerska", "https://www.linkedin.com/in/olga-testerska", "QA Engineer", null, null],
    ],
  );
  assert.equal(parseListItem({ lines: ["Członek LinkedIn", "Tester"], links: [] }), null);
  assert.equal(parseListItem({ lines: ["Kasia Testowa", "Testerka w Fikcyjnej Firmie", "Gdynia"], links: [] }).current_company, "Fikcyjnej Firmie");
});

test("lista wyników: pusty zrzut → zapas z HTML starszego układu", () => {
  const empty = { url: "https://www.linkedin.com/search/results/people/?keywords=java", listItems: [], sections: [], links: [] };
  const r = readPage({ url: empty.url, snapshot: empty, doc: loadFixture("search-results.html") });
  assert.deepEqual(r.people.map((p) => p.full_name), ["Marta Fikcyjna", "Tomasz Testowy"]);
});

test("Recruiter (niezmierzony): imię z h1, doświadczenie z pozycji listy, link „Public profile”, nie link z nawigacji", () => {
  const r = read("recruiter-profile.json");
  const p = r.profile;
  assert.equal(r.kind, "recruiter_profile");
  assert.equal(p.full_name, "Piotr Zmyślony");
  assert.equal(p.headline, "DevOps Engineer at Fikcyjna Chmura");
  assert.equal(p.location, "Katowice, Śląskie, Poland");
  assert.equal(p.public_url, "https://www.linkedin.com/in/piotr-zmyslony-9");
  assert.equal(p.current_company, "Fikcyjna Chmura");
  assert.equal(p.experience.length, 2);
});

test("Recruiter: atrybuty data-test z HTML mają pierwszeństwo, tekst uzupełnia braki", () => {
  const s = snap("recruiter-profile.json");
  const doc = loadFixture("recruiter-profile.html"); // Ewa Przykładowa — inna osoba niż w zrzucie
  const r = readPage({ url: s.url, snapshot: s, doc });
  assert.equal(r.profile.full_name, "Ewa Przykładowa");
  assert.equal(r.profile.public_url, "https://www.linkedin.com/in/ewa-przykladowa-42", "pola z innej osoby nie mieszają się");
});

test("profil: HTML starszego układu nie dokleja pól, gdy rozpoznał inną osobę albo żadnej", () => {
  const s = snap("profile-not-scrolled.json");
  const r = readPage({ url: s.url, snapshot: s, doc: loadFixture("profile-public.html") });
  assert.equal(r.profile.full_name, "Adam Wymyślony");
  assert.deepEqual(r.profile.experience, [], "doświadczenie Zofii nie trafia do profilu Adama");
  assert.deepEqual(mergeProfiles({ a: null, b: [] , c: "x" }, { a: 1, b: [2], c: "y" }), { a: 1, b: [2], c: "x" });
});
