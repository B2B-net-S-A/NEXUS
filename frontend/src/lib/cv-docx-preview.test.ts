import { describe, expect, it } from "vitest";
import { alignB2bLetterheadPreview } from "./cv-docx-preview";

describe("B2B letterhead preview", () => {
  it("corrects full-page headers on each page without accumulating shifts", () => {
    const host = document.createElement("div");
    host.innerHTML = [90, 120].map((margin) => `<section class="docx" style="width:800px;padding-left:${margin}px"><header><div style="position:relative;width:0px;height:0px;left:-5px"><img style="width:810px"></div><div style="position:relative;width:0px;height:0px"><img style="width:80px"></div></header><article><img style="width:810px"></article></section>`).join("");
    document.body.append(host);
    alignB2bLetterheadPreview(host);
    const drawings = host.querySelectorAll<HTMLElement>("header div");
    expect(drawings[0].style.transform).toBe("translateX(-90px)");
    expect(drawings[0].style.display).toBe("block");
    expect(drawings[0].style.left).toBe("-5px");
    expect(drawings[1].style.transform).toBe("");
    expect(drawings[2].style.transform).toBe("translateX(-120px)");
    expect(host.querySelector<HTMLElement>("article img")!.style.transform).toBe("");
    const first = host.innerHTML;
    alignB2bLetterheadPreview(host);
    expect(host.innerHTML).toBe(first);
    host.remove();
  });
});

it("preserves declared point widths despite the global responsive image rule and aligns the footer", () => {
  const host = document.createElement("div");
  host.innerHTML = `<section class="docx" style="width:794px;padding-left:94px">
    <header><div style="position:relative;width:0px;height:0px"><img style="width:598.95pt;max-width:100%"></div></header>
    <footer><div style="position:relative;width:793px;height:96px;float:left"><img style="width:594.6pt;max-width:100%"></div></footer>
    <article><img style="width:598.95pt;max-width:100%"></article>
  </section>`;
  document.body.append(host);
  alignB2bLetterheadPreview(host);
  const header = host.querySelector<HTMLElement>("header div")!;
  const footer = host.querySelector<HTMLElement>("footer div")!;
  expect(header.style.transform).toBe("translateX(-94px)");
  expect(footer.style.transform).toBe("translateX(-94px)");
  expect(header.querySelector("img")!.style.maxWidth).toBe("none");
  expect(footer.querySelector("img")!.style.maxWidth).toBe("none");
  expect(host.querySelector<HTMLElement>("article img")!.style.maxWidth).toBe("100%");
  const first = host.innerHTML;
  alignB2bLetterheadPreview(host);
  expect(host.innerHTML).toBe(first);
  host.remove();
});
