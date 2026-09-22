import { headers } from "next/headers";

import {
  careerBase,
  careerHosts,
  isCareerHost,
  requestDisplayHost,
  requestHost,
  requestOrigin,
  type CareerBase,
} from "@/lib/career/host";

/**
 * Kontekst żądania strony kariery: czy jesteśmy na hoście kariery (linki bez
 * prefiksu `/kariera`), host widoczny dla odwiedzającego (stopka) i pochodzenie
 * żądania. Host bierzemy z nagłówków — nigdy stała domena: na hoście aplikacji
 * strona działa pod `<host>/kariera/...` i taki adres ma widzieć kandydat.
 */
export async function careerRequestContext(): Promise<{
  base: CareerBase;
  host: string;
  origin: string | null;
}> {
  const h = await headers();
  const onCareerHost = isCareerHost(requestHost(h), careerHosts());
  return {
    base: careerBase(onCareerHost),
    host: requestDisplayHost(h),
    origin: requestOrigin(h),
  };
}
