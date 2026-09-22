import "./career.css";

import { careerDisplayFont, careerMonoFont } from "./fonts";

/** Korzeń motywu terminala: fonty, tło z siatką, zmienne kolorów. */
export function CareerTheme({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={`kr-root ${careerDisplayFont.variable} ${careerMonoFont.variable}`}
      lang="pl"
    >
      {children}
    </div>
  );
}
