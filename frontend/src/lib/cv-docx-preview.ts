/** B2B page artwork uses page coordinates, while docx-preview nests it inside
 * the text margins. Only apply this helper to generated B2B CV previews.
 */
function declaredPixels(value: string): number | null {
  const match = /^([0-9]+(?:\.[0-9]+)?)(px|pt)$/.exec(value.trim());
  if (!match) return null;
  return Number(match[1]) * (match[2] === "pt" ? 4 / 3 : 1);
}

export function alignB2bLetterheadPreview(host: HTMLElement): void {
  for (const page of host.querySelectorAll<HTMLElement>("section.docx")) {
    const pageStyle = getComputedStyle(page);
    const pageWidth = parseFloat(pageStyle.width);
    const marginLeft = parseFloat(pageStyle.paddingLeft);
    if (!Number.isFinite(pageWidth) || !Number.isFinite(marginLeft)) continue;
    for (const drawing of page.querySelectorAll<HTMLElement>("header div, footer div")) {
      const style = getComputedStyle(drawing);
      if (style.position !== "relative") continue;
      const zeroSizeAnchor = parseFloat(style.width) === 0 && parseFloat(style.height) === 0;
      const fullWidthFooter = drawing.closest("footer") !== null && parseFloat(style.width) >= pageWidth * 0.8;
      if (!zeroSizeAnchor && !fullWidthFooter) continue;
      const image = drawing.querySelector("img");
      if (!image) continue;
      // Preflight's img { max-width: 100% } collapses an image inside a
      // zero-width anchor. Use the DOCX's declared size to identify artwork.
      const imageWidth = declaredPixels(image.style.width) ?? parseFloat(getComputedStyle(image).width);
      if (!Number.isFinite(imageWidth) || imageWidth < pageWidth * 0.8) continue;
      image.style.maxWidth = "none";
      drawing.style.display = "block";
      drawing.style.transform = `translateX(${-marginLeft}px)`;
    }
  }
}
