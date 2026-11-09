import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { MyPeopleBuddyView } from "../MyPeopleLauncher";

// Przy 1280 × 720 dymek postaci „Moi ludzie” i ikona Jarvisa leżały na
// przyklejonej stopce `/jobs/new`: gdy zostaje jeden brak, przyciski
// „Dokończę później” i „Utwórz i opublikuj” przesuwają się w prawo i znikają
// pod dymkiem (staging, DL, 06.11.2026, rutyna Tester). Ta sama reguła co przy
// bocznym panelu szczegółów (29.10.2026): na czas przyklejonej stopki
// z przyciskami postać i ikona znikają. Selektor bierzemy z arkusza i puszczamy
// po DOM-ie — jsdom nie liczy stylów, ale `:has()` w `querySelectorAll` rozumie.
const css = readFileSync(path.resolve(__dirname, "../../../../app/globals.css"), "utf8");

function hidingSelector(): string {
  const line = css
    .split("\n")
    .find((l) => l.includes("[data-sticky-actions]") && l.includes(":has("));
  expect(line, "brak reguły chowającej róg przy przyklejonej stopce w globals.css").toBeDefined();
  expect(css.slice(css.indexOf(line!)).split("}")[0]).toMatch(/display:\s*none/);
  return line!.replace(/\{.*$/, "").trim();
}

function Screen({ footer }: { footer: boolean }) {
  return (
    <>
      <main>
        {footer && (
          <footer data-sticky-actions="">
            <button type="button">Utwórz i opublikuj</button>
          </footer>
        )}
      </main>
      <MyPeopleBuddyView onOpen={() => {}} />
      <div data-jarvis-mascot="" />
    </>
  );
}

describe("postać w rogu ustępuje przyklejonej stopce z przyciskami", () => {
  it("przy stopce reguła trafia w postać i w ikonę Jarvisa", () => {
    render(<Screen footer />);
    const hidden = Array.from(document.querySelectorAll(hidingSelector()));
    const buddy = document.querySelector("[data-floating-corner]");
    expect(buddy).not.toBeNull();
    expect(hidden).toContain(buddy);
    expect(hidden).toContain(document.querySelector("[data-jarvis-mascot]"));
  });

  it("bez stopki postać zostaje", () => {
    render(<Screen footer={false} />);
    expect(document.querySelectorAll(hidingSelector())).toHaveLength(0);
  });

  it("stopka nowej rekrutacji nosi atrybut, po którym reguła ją znajduje", () => {
    const page = readFileSync(
      path.resolve(__dirname, "../../jobs/new/NewJobPage.tsx"),
      "utf8",
    );
    expect(page).toMatch(/<footer[^>]*data-sticky-actions/);
  });
});
