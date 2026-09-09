export function HighlightedCvText({ text, runs }: {
  text: string;
  runs?: Array<{ text: string; bold: boolean }>;
}) {
  // Formatting metadata must never change document content, even on a stale
  // cached payload. React escapes every text run; no HTML enters this view.
  if (!Array.isArray(runs) || runs.map((run) => run.text).join("") !== text) return <>{text}</>;
  return <>{runs.map((run, index) => run.bold
    ? <strong key={index}>{run.text}</strong>
    : <span key={index}>{run.text}</span>)}</>;
}
