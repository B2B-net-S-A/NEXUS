// Poligon NEXUSA (decyzja Artura z 14.11.2026): nowa osoba uczy się na
// prawdziwych ekranach, ale na rekrutacji ćwiczebnej z wymyślonymi danymi.
// Tryb włącza się na tę jedną kartę przeglądarki (sessionStorage), więc druga
// karta z prawdziwą pracą działa normalnie. Wejście i wyjście przeładowują
// stronę, żeby pamięć zapytań nie mieszała danych ćwiczebnych z prawdziwymi.

//
// Ten sam tryb niesie poranną porcję nowości (18.11.2026): przeklikanie idzie
// po prawdziwych ekranach z wyłączonymi zapisami, a rekrutacja ćwiczebna ma
// elementy, których na pustej liście by nie było. Wtedy wartość to `novelty`
// i powłoka pokazuje warstwę przeklikania zamiast ćwiczeń Poligonu.

const KEY = "nexus.poligon";

export type PoligonPurpose = "exercises" | "novelty";

function stored(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function isPoligonActive(): boolean {
  const value = stored();
  return value === "1" || value === "novelty";
}

/** Tryb ćwiczebny włączony dla przeklikania nowości z porcji dnia. */
export function isNoveltyPractice(): boolean {
  return stored() === "novelty";
}

/** Włącza poligon i przechodzi na pierwszy ekran ćwiczenia. */
export function enterPoligon(href: string, purpose: PoligonPurpose = "exercises"): void {
  try {
    window.sessionStorage.setItem(KEY, purpose === "novelty" ? "novelty" : "1");
  } catch {
    // Bez sessionStorage poligon nie ruszy — zostajemy na mapie.
    return;
  }
  window.location.assign(href);
}

export function leavePoligon(href = "/poligon"): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // nic: i tak przeładowujemy
  }
  window.location.assign(href);
}
