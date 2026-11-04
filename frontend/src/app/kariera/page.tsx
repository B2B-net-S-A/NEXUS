import type { Metadata } from "next";

import { CareerBoardView } from "@/components/career/CareerBoardView";
import { fetchCareerBoard } from "@/lib/career/server";

import { careerRequestContext } from "./_context";

export const metadata: Metadata = { title: "Kariera" };

export const dynamic = "force-dynamic";

/**
 * Strona startowa hosta kariery: tablica wszystkich otwartych rekrutacji
 * z opublikowanym opisem (etap 6, decyzja Artura D1 = A, 20.10.2026). Karta
 * prowadzi na link prowadzącego rekrutację (D2 = A); „Zostaw CV” idzie stałym
 * linkiem Head of Recruitment. Awaria API ma własny komunikat — nie pustą listę.
 */
export default async function CareerHome() {
  const [{ base, host }, result] = await Promise.all([careerRequestContext(), fetchCareerBoard()]);
  return <CareerBoardView data={result.ok ? result.data : null} base={base} host={host} />;
}
