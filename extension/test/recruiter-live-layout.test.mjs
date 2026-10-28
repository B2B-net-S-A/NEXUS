// Regressions from live Recruiter DOM structure; every fixture value is fictional.
import { test } from "node:test";
import assert from "node:assert/strict";
import { loadFixture } from "./helpers.mjs";
import { readPage, readPageDom } from "../src/readers/index.js";

const SEARCH = "https://www.linkedin.com/talent/hire/555/discover/recruiterSearch";
const PROFILE = `${SEARCH}/profile/AEMAFAKE3`;
const load = () => loadFixture("recruiter-slidein.html");

test("Recruiter list: data-test fields win over a capture starting with Select control", () => {
  const result = readPage({ url: SEARCH, doc: load(), snapshot: {
    listItems: [{ lines: ["Select Marta Fikcyjna", "Marta Fikcyjna", "Third degree connection", "· 3rd", "Frontend Engineer at Wymyślone Studio", "Poznań, Poland"], links: [] }],
  } });
  assert.deepEqual(result.people.map((p) => p.full_name), ["Marta Fikcyjna", "Tomasz Testowy"]);
  assert.equal(result.people[0].headline, "Frontend Engineer at Wymyślone Studio");
  assert.equal(result.people[0].location, "Poznań, Poland");
});

test("Recruiter slide-in outside main: selected person, employer, grouped roles and skills", () => {
  const result = readPageDom(load(), PROFILE);
  const p = result.profile;
  assert.equal(p.full_name, "Zofia Testowa");
  assert.equal(p.headline, "Java, Kotlin i systemy rozproszone");
  assert.equal(p.location, "Kraków, Poland");
  assert.equal(p.public_url, "https://www.linkedin.com/in/zofia-testowa-synthetic");
  assert.equal(p.current_company, "Fikcyjna Software");
  assert.equal(p.current_title, "Senior Java Developer");
  assert.deepEqual(p.skills, ["Java", "Kotlin"]);
  assert.deepEqual(p.experience, [
    { title: "Senior Java Developer", company: "Fikcyjna Software", start: "2023-05", end: null, current: true },
    { title: "Java Developer", company: "Przykładowy Bank SA", start: "2019-05", end: "2023-04", current: false },
    { title: "Junior Java Developer", company: "Przykładowy Bank SA", start: "2017-10", end: "2019-05", current: false },
  ]);
  assert.match(p.about, /Fikcyjny opis/);
  assert.deepEqual(result.missing, []);
});

test("Recruiter: global unbound tooltip and background links never supply public URL", () => {
  const doc = load();
  doc.getElementById("selected-public-profile").remove();
  assert.equal(readPageDom(doc, PROFILE).profile.public_url, null);
});

test("Recruiter: conflicting profile-controlled public links are ambiguous", () => {
  const doc = load();
  doc.querySelector('.profile__topcard-wrapper button').setAttribute('aria-describedby', 'unrelated-public-profile');
  assert.equal(readPageDom(doc, PROFILE).profile.public_url, null);
});

test("Recruiter: multiple active profile roots fail closed even with a plausible text snapshot", () => {
  const doc = load();
  doc.body.appendChild(doc.querySelector('.profile__container').cloneNode(true));
  const result = readPage({ url: PROFILE, doc, snapshot: { heading: { text: "Marta Fikcyjna" }, top: { lines: ["Marta Fikcyjna", "Developer"] } } });
  assert.equal(result.profile.full_name, null);
  assert.equal(result.profile.public_url, null);
  assert.ok(result.missing.includes("full_name"));
});

test("Recruiter: hidden stale profile root is excluded, unloaded profile never reads background person", () => {
  const doc = load();
  const stale = doc.querySelector('.profile__container').cloneNode(true);
  stale.setAttribute('hidden', '');
  doc.body.appendChild(stale);
  assert.equal(readPageDom(doc, PROFILE).profile.full_name, "Zofia Testowa");
  doc.querySelector('.profile-slidein__container').remove();
  assert.equal(readPageDom(doc, PROFILE).profile.full_name, null);
});
