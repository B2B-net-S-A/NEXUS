/**
 * MAKIETA (28.10.2026, feedback zespołu do ogłoszeń na stronie kariery):
 * `/kariera/r/<slug>?uklad=<id>` renderuje wariant zamiast dzisiejszego widoku.
 * Tylko na gałęzi makiet — nie scalać w tej postaci.
 */
import "./fonts.css";

import type { CareerJobResponse } from "@/lib/career/api";
import type { CareerBase } from "@/lib/career/host";

import { B2BCiemny } from "./B2BCiemny";
import { B2BJasny } from "./B2BJasny";
import { Karta } from "./Karta";
import { Redakcja } from "./Redakcja";
import { TerminalPlus } from "./TerminalPlus";

export interface MockupProps {
  data: CareerJobResponse;
  base: CareerBase;
  host: string;
}

export const CAREER_MOCKUPS = {
  "terminal-plus": TerminalPlus,
  "b2b-jasny": B2BJasny,
  "b2b-ciemny": B2BCiemny,
  redakcja: Redakcja,
  karta: Karta,
} as const;

export type CareerMockupId = keyof typeof CAREER_MOCKUPS;

export function isCareerMockupId(value: unknown): value is CareerMockupId {
  return typeof value === "string" && value in CAREER_MOCKUPS;
}

export function CareerMockup({ id, ...props }: MockupProps & { id: CareerMockupId }) {
  const View = CAREER_MOCKUPS[id];
  return <View {...props} />;
}
