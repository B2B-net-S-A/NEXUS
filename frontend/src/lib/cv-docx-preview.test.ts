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
