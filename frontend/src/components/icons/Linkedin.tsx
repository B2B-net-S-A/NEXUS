import { createLucideIcon } from "lucide-react";

// lucide-react 1.0 usunął ikony marek (Linkedin, Github…). Ten sam rysunek
// co w lucide-react 0.469 (licencja ISC), zbudowany tą samą funkcją, więc
// propsy (`className`, `size`, `aria-hidden`) działają jak w pozostałych ikonach.
export const Linkedin = createLucideIcon("Linkedin", [
  [
    "path",
    {
      d: "M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z",
      key: "c2jq9f",
    },
  ],
  ["rect", { width: "4", height: "12", x: "2", y: "9", key: "mk3on5" }],
  ["circle", { cx: "4", cy: "4", r: "2", key: "bt5ra8" }],
]);
