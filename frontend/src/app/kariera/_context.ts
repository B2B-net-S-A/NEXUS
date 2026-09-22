import { headers } from "next/headers";

import {
  careerBase,
  careerHosts,
  isCareerHost,
  primaryCareerHost,
  requestHost,
  type CareerBase,
} from "@/lib/career/host";

/**
 * Kontekst żądania strony kariery: czy jesteśmy na hoście kariery (linki bez
 * prefiksu `/kariera`) i jaki host pokazać w stopce.
 */
export async function careerRequestContext(): Promise<{ base: CareerBase; host: string }> {
  const h = await headers();
  const host = requestHost(h);
  const onCareerHost = isCareerHost(host, careerHosts());
  return {
    base: careerBase(onCareerHost),
    host: onCareerHost ? host : primaryCareerHost(),
  };
}
