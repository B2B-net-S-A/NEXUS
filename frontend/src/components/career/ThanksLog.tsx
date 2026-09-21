import { genitiveName, recruiterLogin } from "@/lib/career/format";

import { TwoToneTitle } from "./CareerHero";
import { TerminalChrome } from "./TerminalChrome";

/** Podziękowanie po wysłaniu (log `./aplikuj.sh --wyslij`). */
export interface ThanksContext {
  variant: "job" | "general";
  recruiterFirstName: string;
  jobHandle?: string;
  chromePath: string;
  recruiterPageHref?: string | null;
  recruiterPageSlug?: string | null;
}

export function ThanksLog({
  variant,
  firstName,
  email,
  recruiterFirstName,
  jobHandle,
  chromePath,
  recruiterPageHref,
  recruiterPageSlug,
}: {
  variant: "job" | "general";
  firstName: string;
  email: string;
  recruiterFirstName: string;
  jobHandle?: string;
  chromePath: string;
  recruiterPageHref?: string | null;
  recruiterPageSlug?: string | null;
}) {
  const recruiter = genitiveName(recruiterFirstName);
  return (
    <>
      <TerminalChrome path={chromePath} />
      <main className="kr-log" aria-live="polite">
        <span>
          <span className="kr-r" aria-hidden="true">
            ${" "}
          </span>
          {variant === "job" ? "./aplikuj.sh --wyslij" : "./dolacz-do-bazy.sh --wyslij"}
        </span>
        <span>
          <span className="kr-r">[ok]</span> <span className="kr-g">cv</span>{" "}
          <span className="kr-c">{"// przesłane"}</span>
        </span>
        <span>
          <span className="kr-r">[ok]</span> <span className="kr-g">zgłoszenie</span>{" "}
          <span className="kr-c">{"// zapisane"}</span>
        </span>
        <span>
          <span className="kr-r">[ok]</span>{" "}
          <span className="kr-g">{recruiterLogin(recruiterFirstName)}</span>{" "}
          <span className="kr-c">{"// powiadomienie wysłane"}</span>
        </span>
        <TwoToneTitle
          className="kr-log-title kr-log-title-lg"
          first={firstName.trim() ? "Dziękujemy," : ""}
          second={firstName.trim() ? `${firstName.trim()}.` : "Dziękujemy."}
          inline
        />
        <span className="kr-log-text">
          {variant === "job" && jobHandle
            ? `Twoja aplikacja na ${jobHandle} trafiła do ${recruiter}. Odezwie się po przejrzeniu CV.`
            : `Twoje CV trafiło do ${recruiter}. Odezwie się, gdy pojawi się projekt dla Ciebie.`}
        </span>
        <span className="kr-c">
          {"// odpowiedź przyjdzie na "}
          {email}
        </span>
        <span className="kr-c">
          {"// Twoje CV zostaje w bazie — dostaniesz też propozycje innych projektów"}
        </span>
        {recruiterPageHref ? (
          <a className="kr-btn-outline" href={recruiterPageHref}>
            $ ls ~/{recruiterPageSlug ?? "rekrutacje"}/rekrutacje →
          </a>
        ) : null}
      </main>
    </>
  );
}
