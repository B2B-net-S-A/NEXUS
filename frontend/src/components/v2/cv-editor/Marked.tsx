import { parseBoldMarkup } from "@/lib/cv-qc";

/**
 * Znacznik korzenia panelu obok kartki (asystent, historia wersji): Escape
 * w jego wnętrzu nie zamyka edytora CV.
 */
export const CV_PANEL_ATTR = "data-cv-panel";

/** Tekst z pogrubieniem `**x**` jako zwykłe węzły tekstu — nigdy jako HTML. */
export function Marked({ text }: { text: string }) {
  return (
    <>
      {parseBoldMarkup(text).map((run, index) =>
        run.b ? (
          <strong key={index} className="font-semibold">
            {run.t}
          </strong>
        ) : (
          <span key={index}>{run.t}</span>
        ),
      )}
    </>
  );
}
