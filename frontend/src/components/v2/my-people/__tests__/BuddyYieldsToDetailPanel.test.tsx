import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { ListDetailLayout } from "@/components/ds/ListDetailLayout";
import { MyPeopleBuddyView } from "../MyPeopleLauncher";

// Przy 1280 × 720 dymek postaci „Moi ludzie” leżał na stopce bocznego panelu
// kontraktu i „Zakończ współpracę…” nie dało się kliknąć (staging, DL,
// 29.10.2026). Panel żyje w kontekście warstw treści strony (`animate-fadeIn`
// z wypełnieniem `both`), więc jego `z-40` nie wygra z postacią `z-30` poza
// `<main>`. Decyzja Artura: na czas otwartego panelu postać i ikona Jarvisa
// znikają regułą CSS w globals.css. Selektor bierzemy z arkusza i puszczamy
// po prawdziwym DOM-ie komponentów — jsdom nie liczy stylów, ale `:has()`
// w `querySelectorAll` rozumie.
const css = readFileSync(path.resolve(__dirname, "../../../../app/globals.css"), "utf8");

function hidingSelector(): string {
  const line = css
    .split("\n")
    .find((l) => l.includes("[data-list-detail-panel]") && l.includes(":has("));
  expect(line, "brak reguły chowającej róg przy panelu w globals.css").toBeDefined();
  expect(css.slice(css.indexOf(line!)).split("}")[0]).toMatch(/display:\s*none/);
  return line!.replace(/\{.*$/, "").trim();
}

function Screen({ panelOpen }: { panelOpen: boolean }) {
  return (
    <>
      <ListDetailLayout
        list={<table />}
        panel={panelOpen ? <div>Zakończ współpracę…</div> : null}
        onClose={() => {}}
        panelLabel="Szczegóły kontraktu"
      />
      <MyPeopleBuddyView
        count={3}
        sentences={["3 nowe rekrutacje pasują do Twoich ludzi."]}
        showBubble
        onOpen={() => {}}
        onDismissBubble={() => {}}
        onHide={() => {}}
        animate={false}
      />
      <div data-jarvis-mascot="" />
    </>
  );
}

describe("postać w rogu ustępuje bocznemu panelowi szczegółów", () => {
  it("przy otwartym panelu reguła trafia w postać z dymkiem i w ikonę Jarvisa", () => {
    render(<Screen panelOpen />);
    const hidden = Array.from(document.querySelectorAll(hidingSelector()));
    const buddy = document.querySelector("[data-floating-corner]");
    expect(buddy).not.toBeNull();
    expect(buddy!.querySelector('[role="status"]')).not.toBeNull();
    expect(hidden).toContain(buddy);
    expect(hidden).toContain(document.querySelector("[data-jarvis-mascot]"));
  });

  it("bez panelu postać zostaje", () => {
    render(<Screen panelOpen={false} />);
    expect(document.querySelectorAll(hidingSelector())).toHaveLength(0);
    expect(document.querySelector("[data-floating-corner]")).not.toBeNull();
  });

  it("ikona Jarvisa nosi atrybut, po którym reguła ją znajduje", () => {
    const mascot = readFileSync(
      path.resolve(__dirname, "../../../jarvis/JarvisMascot.tsx"),
      "utf8",
    );
    expect(mascot).toContain("data-jarvis-mascot");
  });
});
