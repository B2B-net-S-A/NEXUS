"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useRef } from "react";

import { Cmd } from "./CareerHero";
import { processSteps } from "./scenes/model";

// ScrollTrigger rejestruje się w efekcie: przy imporcie czyta `matchMedia`,
// którego nie ma w jsdom (testy).
gsap.registerPlugin(useGSAP);

/**
 * `./proces --kroki` — stałe cztery kroki procesu na pionowej osi (etap 7):
 * cztery wąskie kolumny łamały „rozmowa z / Martą”. Oś rysuje się razem ze
 * scrollem (ScrollTrigger scrub); przy „ograniczonym ruchu” stoi narysowana.
 */
export function ProcessSteps({
  recruiterFirstName,
  contract,
}: {
  recruiterFirstName: string;
  contract?: string | null;
}) {
  const steps = processSteps(recruiterFirstName, contract);
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      if (
        typeof window === "undefined" ||
        typeof window.matchMedia !== "function"
      )
        return;
      gsap.registerPlugin(ScrollTrigger);
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const scrub = {
          trigger: ".kr-steps",
          start: "top 75%",
          end: "bottom 55%",
          scrub: 0.6,
        };
        gsap.fromTo(
          ".kr-steps-line i",
          { scaleY: 0 },
          { scaleY: 1, ease: "none", scrollTrigger: scrub },
        );
        gsap.fromTo(
          ".kr-step",
          { opacity: 0.35 },
          { opacity: 1, stagger: 0.25, ease: "none", scrollTrigger: scrub },
        );
      });
      return () => mm.revert();
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label="Proces rekrutacji">
      <Cmd>./proces --kroki</Cmd>
      <div className="kr-steps">
        <span className="kr-steps-line" aria-hidden="true">
          <i />
        </span>
        <ol className="kr-steps-list">
          {steps.map((step, i) => (
            <li className="kr-step" key={step.title}>
              <span className="kr-r">krok {i + 1}</span>
              <span className="kr-step-title">{step.title}</span>
              <span className="kr-step-note">{step.note}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
