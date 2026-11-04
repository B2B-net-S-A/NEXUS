/**
 * Wejście z maila przypomnienia o ogłoszeniu (27.10.2026) — parametry adresu
 * rekrutacji: `?ogloszenie=kariera|pracuj|jjit` (okno „Ogłoszenie” na kanale),
 * `?ogloszenie=pomin` (okno „Nie publikujemy”), `&przypomnij=rekruter`
 * (pytanie „Przypomnieć rekruterowi?”), `&wyslij=opiekun` przy Pracuj.pl (okno
 * maila do opiekuna Pracuj.pl). Przyciski maila tylko otwierają okno —
 * nic nie zapisuje się z linku, a parametry znikają z adresu po obsłużeniu
 * (`docs/claude/powiadomienia/maile-z-przyciskami-akcji.md`).
 */

import type { AdChannel } from "@/lib/api/jobAd";

export const AD_MAIL_PARAM = "ogloszenie";
export const AD_REMIND_PARAM = "przypomnij";
export const AD_SEND_PARAM = "wyslij";

export interface AdMailIntent {
  focus: AdChannel | null;
  skip: boolean;
  remind: boolean;
  /** Pracuj.pl: od razu okno maila do opiekuna. */
  send: boolean;
}

const CHANNELS: readonly AdChannel[] = ["kariera", "pracuj", "jjit"];

export function readAdMailIntent(
  params: Pick<URLSearchParams, "get"> | null,
): AdMailIntent | null {
  const raw = params?.get(AD_MAIL_PARAM) ?? null;
  const remind = params?.get(AD_REMIND_PARAM) === "rekruter";
  if (raw == null && !remind) return null;
  const focus = CHANNELS.find((channel) => channel === raw) ?? null;
  const skip = raw === "pomin";
  if (!focus && !skip && !remind) return null;
  const send = focus === "pracuj" && params?.get(AD_SEND_PARAM) === "opiekun";
  return { focus, skip, remind, send };
}

/**
 * Rekrutacja z oknem maila do opiekuna Pracuj.pl — przycisk po utworzeniu
 * rekrutacji w `/jobs/new` (ten sam adres co przycisk w codziennym mailu).
 */
export function pracujMailHref(jobId: number): string {
  return `/jobs/${jobId}?${AD_MAIL_PARAM}=pracuj&${AD_SEND_PARAM}=opiekun`;
}

/** Zapytanie bez parametrów maila (`?a=1&ogloszenie=jjit` → `?a=1`, sam → ``). */
export function withoutAdMailParams(search: string): string {
  const next = new URLSearchParams(search);
  next.delete(AD_MAIL_PARAM);
  next.delete(AD_REMIND_PARAM);
  next.delete(AD_SEND_PARAM);
  const query = next.toString();
  return query ? `?${query}` : "";
}
