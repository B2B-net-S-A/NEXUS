/** Pasek okna terminala: trzy kropki, ścieżka, znak po prawej. */
export type ChromeState = "brand" | "open" | "closed";

const RIGHT_LABEL: Record<ChromeState, string> = {
  brand: "ARCHITECTS OF THE UNSEEN",
  open: "REKRUTACJA OTWARTA",
  closed: "ZAMKNIĘTA",
};

export function TerminalChrome({
  path,
  state = "brand",
}: {
  /** Np. „~/dynaminds/kariera — zsh — senior-java-developer". */
  path: string;
  state?: ChromeState;
}) {
  const closed = state === "closed";
  return (
    <header className="kr-chrome">
      <span className="kr-chrome-left">
        <span className="kr-dots" aria-hidden="true">
          <span className="kr-dot" />
          <span className="kr-dot" />
          <span className={closed ? "kr-dot" : "kr-dot kr-dot-on"} />
        </span>
        <span className="kr-chrome-path">{path}</span>
      </span>
      <span className="kr-chrome-right">
        {closed ? (
          <span aria-hidden="true">○ </span>
        ) : (
          <span className="kr-bullet" aria-hidden="true">
            ●{" "}
          </span>
        )}
        {RIGHT_LABEL[state]}
      </span>
    </header>
  );
}
