import { TerminalChrome } from "./TerminalChrome";

/** Rekrutacja zamknięta (albo link odwołany) — odesłanie do stałego linku. */
export function ClosedNotice({
  jobHandle,
  recruiterFirstName,
  recruiterPageHref,
  recruiterSlug,
}: {
  jobHandle: string;
  recruiterFirstName: string;
  recruiterPageHref: string | null;
  recruiterSlug: string | null;
}) {
  const name = recruiterFirstName.trim() || "Nasz zespół";
  return (
    <>
      <TerminalChrome path={`~/dynaminds/kariera — zsh — ${jobHandle}`} state="closed" />
      <main className="kr-log">
        <span>
          <span className="kr-r" aria-hidden="true">
            ${" "}
          </span>
          ./aplikuj.sh
        </span>
        <span>
          <span className="kr-r">[err]</span> <span className="kr-g">{jobHandle}</span>{" "}
          <span className="kr-c">{"// rekrutacja została zamknięta"}</span>
        </span>
        <h1 className="kr-log-title">
          <span className="kr-title-a">Ten proces jest</span>{" "}
          <span className="kr-title-b">zakończony.</span>
        </h1>
        {recruiterPageHref ? (
          <>
            <span className="kr-log-text">
              {name} prowadzi kolejne rekrutacje. Zostaw CV — odezwie się, gdy pojawi się
              podobny projekt.
            </span>
            <span className="kr-c">
              {"// sugestia: cd ~/"}
              {recruiterSlug}
            </span>
            <a className="kr-btn" href={recruiterPageHref}>
              $ cd ~/{recruiterSlug} — zostaw CV w bazie
            </a>
          </>
        ) : (
          <span className="kr-log-text">
            Dziękujemy za zainteresowanie. Zajrzyj do innych ogłoszeń naszych rekruterów na
            LinkedInie.
          </span>
        )}
      </main>
    </>
  );
}
