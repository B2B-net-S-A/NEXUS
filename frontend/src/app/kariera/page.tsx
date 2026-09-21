import type { Metadata } from "next";

import { TerminalChrome } from "@/components/career/TerminalChrome";
import { TwoToneTitle } from "@/components/career/CareerHero";
import { CareerFooter } from "@/components/career/CareerFooter";
import { careerHref } from "@/lib/career/host";

import { careerRequestContext } from "./_context";

export const metadata: Metadata = { title: "Kariera" };

/**
 * Strona startowa hosta kariery. Nie ma tu listy rekrutacji (każdy rekruter ma
 * własny link) — tylko kierunek, gdzie ich szukać.
 */
export default async function CareerHome() {
  const { base, host } = await careerRequestContext();
  return (
    <>
      <TerminalChrome path="~/dynaminds/kariera — zsh" />
      <main className="kr-log">
        <span>
          <span className="kr-r" aria-hidden="true">
            ${" "}
          </span>
          cat ~/dynaminds/kariera/README
        </span>
        <TwoToneTitle className="kr-log-title" first="Architects of" second="the unseen." />
        <span className="kr-log-text">
          Tu trafiają kandydaci z linków naszych rekruterów. Otwarte rekrutacje znajdziesz
          w postach zespołu Dynaminds na LinkedInie.
        </span>
        <span className="kr-c">{"// zajrzyj na LinkedIn rekruterów Dynaminds"}</span>
      </main>
      <CareerFooter rodoHref={careerHref(base, { to: "rodo" })} hostLabel={host} />
    </>
  );
}
