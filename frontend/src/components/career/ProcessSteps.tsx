import { instrumentalName } from "@/lib/career/format";

import { Cmd } from "./CareerHero";

/** `./proces --kroki` — stałe cztery kroki procesu. */
export function ProcessSteps({
  recruiterFirstName,
  contract,
}: {
  recruiterFirstName: string;
  contract?: string | null;
}) {
  const contractNote = contract?.trim()
    ? `umowa ${contract.trim().toLocaleLowerCase("pl-PL")}`
    : "umowa i wdrożenie";
  const steps = [
    { title: `rozmowa z ${instrumentalName(recruiterFirstName)}`, note: "poznajemy się" },
    { title: "weryfikacja techniczna", note: "z ekspertem" },
    { title: "spotkanie z zespołem", note: "po stronie klienta" },
    { title: "decyzja i start", note: contractNote },
  ];
  return (
    <section aria-label="Proces rekrutacji">
      <Cmd>./proces --kroki</Cmd>
      <ol className="kr-steps" style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {steps.map((step, i) => (
          <li className="kr-step" key={step.title}>
            <span className="kr-r">{String(i + 1).padStart(2, "0")}</span>
            <span>{step.title}</span>
            <span className="kr-c">{"// "}{step.note}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
