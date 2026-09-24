// Stan pracy nad requestem (0371, decyzje Artura 24.09.2026) — lustro
// `backend/app/services/request_work_state.py` na wspólnym pliku przypadków
// `lib/__fixtures__/request-work-state-cases.json`.
//
// „Mamy championa" nie jest wartością kolumny: to `champion_found_at` przy
// stanie „Szukamy kandydatów".

export const WORK_STATES = [
  "to_review",
  "searching",
  "client_silent",
  "finished",
] as const
export type WorkState = (typeof WORK_STATES)[number]

export const VISIBLE_STATES = [
  "to_review",
  "searching",
  "champion",
  "client_silent",
  "finished",
] as const
export type VisibleState = (typeof VISIBLE_STATES)[number]

export const STATE_LABEL: Record<VisibleState, string> = {
  to_review: "Do przejrzenia",
  searching: "Szukamy kandydatów",
  champion: "Mamy championa",
  client_silent: "Klient milczy",
  finished: "Zakończony",
}

/**
 * Stan pracy w WIERSZU listy `/jobs` — obok plakietki statusu requestu.
 * Sam „Do przejrzenia” czytał się jak propozycje do przejrzenia, a „Szukamy
 * kandydatów” dublował status „Szukamy” w innym znaczeniu (audyt 24.09.2026),
 * stąd przedrostek „Praca:” — jak nazwa grupy przycisków nad listą.
 */
export const ROW_STATE_LABEL: Record<VisibleState, string> = {
  to_review: "Praca: do przeglądu",
  searching: "Praca: w toku",
  champion: "Praca: mamy championa",
  client_silent: "Praca: klient milczy",
  finished: "Praca: zakończona",
}

/** Jedno zdanie: co ten stan znaczy dla zespołu (makieta „Porządek w requestach"). */
export const STATE_HINT: Record<VisibleState, string> = {
  to_review: "Nikt jeszcze nie zdecydował, czy nad tym pracujemy.",
  searching:
    "Ktoś musi dziś szukać i wysyłać ludzi. Tylko te requesty dostają osoby z przydziału i są na daily.",
  champion:
    "DL oznaczył championa. Nie szukamy dalej, ludzie są zwolnieni. Jeśli champion odpadnie, request wraca do „Szukamy”.",
  client_silent:
    "Request jest otwarty, ale klient nie odpowiada i nikt nad nim nie pracuje. Wraca sam, gdy klient przyśle termin albo feedback.",
  finished:
    "Klient zrezygnował albo obsadziliśmy stanowisko. Znika z list, historia zostaje.",
}

export function visibleState(
  workState: string | null | undefined,
  championFoundAt: unknown,
): VisibleState {
  const state = (WORK_STATES as readonly string[]).includes(workState ?? "")
    ? (workState as WorkState)
    : "to_review"
  if (state === "searching" && championFoundAt != null) return "champion"
  return state
}
