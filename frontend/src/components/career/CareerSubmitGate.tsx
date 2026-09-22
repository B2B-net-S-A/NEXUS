"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import type { CareerApplySuccess } from "./CareerApplyForm";
import { ThanksLog, type ThanksContext } from "./ThanksLog";

/**
 * Po wysłaniu formularza CAŁA strona zamienia się w podziękowanie (makieta
 * „Thanks"), a nie tylko pudełko formularza. Strona renderuje się na serwerze,
 * więc bramka trzyma stan po stronie klienta; formularz zgłasza sukces przez
 * kontekst (funkcji nie da się przekazać z komponentu serwerowego).
 */
const SubmitContext = createContext<((r: CareerApplySuccess) => void) | null>(null);

export function useCareerSubmitted(): ((r: CareerApplySuccess) => void) | null {
  return useContext(SubmitContext);
}

export function CareerSubmitGate({
  children,
  thanks,
}: {
  children: ReactNode;
  thanks: ThanksContext;
}) {
  const [result, setResult] = useState<CareerApplySuccess | null>(null);
  if (result) return <ThanksLog {...thanks} firstName={result.firstName} email={result.email} />;
  return (
    <SubmitContext.Provider
      value={(r) => {
        setResult(r);
        if (typeof window !== "undefined" && typeof window.scrollTo === "function") {
          try {
            window.scrollTo({ top: 0 });
          } catch {
            // jsdom nie implementuje scrollTo — bez znaczenia dla treści.
          }
        }
      }}
    >
      {children}
    </SubmitContext.Provider>
  );
}
