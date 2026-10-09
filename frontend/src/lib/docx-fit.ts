/**
 * Dopasowanie stron `docx-preview` do szerokości hosta. Bez zależności od
 * pdf.js ani `docx-preview` — korzysta z tego podgląd plików i CV firmowe
 * w panelu osoby, które nie mogą wciągać ciężkich bibliotek do chunku Tablicy.
 */

/** Skaluje strony `docx-preview` (`section.docx`) do szerokości hosta, gdy są
 *  od niego szersze — na telefonie CV w DOCX czytało się tylko przewijając w bok.
 *  Na wąskim ekranie zmniejsza też szary margines wokół stron. */
export function fitDocxSectionsToWidth(host: HTMLElement): void {
  const wrapper = host.querySelector<HTMLElement>(".docx-wrapper");
  const sections = host.querySelectorAll<HTMLElement>("section.docx");
  if (!wrapper || sections.length === 0) return;
  wrapper.style.padding = host.clientWidth < 640 ? "8px" : "";
  const wrapperStyle = window.getComputedStyle(wrapper);
  const available =
    wrapper.clientWidth -
    (parseFloat(wrapperStyle.paddingLeft) || 0) -
    (parseFloat(wrapperStyle.paddingRight) || 0);
  sections.forEach((section) => {
    section.style.removeProperty("zoom");
    const natural = section.offsetWidth;
    if (available > 0 && natural > available) {
      section.style.setProperty("zoom", String(available / natural));
    }
  });
}

/** Dopasowuje od razu i przy każdej zmianie szerokości hosta; zwraca sprzątanie. */
export function observeDocxFit(host: HTMLElement): () => void {
  fitDocxSectionsToWidth(host);
  if (typeof ResizeObserver === "undefined") return () => undefined;
  const observer = new ResizeObserver(() => fitDocxSectionsToWidth(host));
  observer.observe(host);
  return () => observer.disconnect();
}
