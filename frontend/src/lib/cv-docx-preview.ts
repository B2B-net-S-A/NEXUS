/** Correct docx-preview's missing page-origin support for our B2B letterhead.
 * Only call for generated B2B CVs: their full-width header is page-anchored.
 * Native DOCX retains page coordinates so repeated headers work in Office.
 */
export function alignB2bLetterheadPreview(host: HTMLElement): void {
  for (const page of host.querySelectorAll<HTMLElement>("section.docx")) {
    const pageStyle = getComputedStyle(page);
    const pageWidth = parseFloat(pageStyle.width);
    const marginLeft = parseFloat(pageStyle.paddingLeft);
    if (!Number.isFinite(pageWidth) || !Number.isFinite(marginLeft)) continue;
    for (const drawing of page.querySelectorAll<HTMLElement>("header div")) {
      const style = getComputedStyle(drawing);
      // wrapNone is represented as a zero-size positioned drawing wrapper.
      if (style.position !== "relative" || parseFloat(style.width) !== 0 || parseFloat(style.height) !== 0) continue;
      const image = drawing.querySelector("img");
      if (!image || parseFloat(getComputedStyle(image).width) < pageWidth * 0.8) continue;
      if (!Number.isFinite(parseFloat(getComputedStyle(image).width))) continue;
      // The renderer forces drawings inline-block; centered header paragraphs
      // otherwise add half a text column to the page-relative offset.
      drawing.style.display = "block";
      drawing.style.transform = `translateX(${-marginLeft}px)`;
    }
  }
}
