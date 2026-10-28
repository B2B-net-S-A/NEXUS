// Fixture'y w test/fixtures to SYNTETYCZNE strony: wymyślone osoby i firmy
// (repo jest publiczne). Gdy LinkedIn zmieni DOM, odtwórz w nowym pliku samą
// strukturę (tagi, klasy, atrybuty data-*) z wymyśloną treścią.
import { readFileSync } from "node:fs";
import { DOMParser } from "linkedom";

export function loadFixture(name) {
  const html = readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8");
  return new DOMParser().parseFromString(html, "text/html");
}

export function parse(html) {
  return new DOMParser().parseFromString(html, "text/html");
}
