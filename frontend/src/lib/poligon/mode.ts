// Poligon NEXUSA (decyzja Artura z 14.11.2026): nowa osoba uczy się na
// prawdziwych ekranach, ale na rekrutacji ćwiczebnej z wymyślonymi danymi.
// Tryb włącza się na tę jedną kartę przeglądarki (sessionStorage), więc druga
// karta z prawdziwą pracą działa normalnie. Wejście i wyjście przeładowują
// stronę, żeby pamięć zapytań nie mieszała danych ćwiczebnych z prawdziwymi.

const KEY = "nexus.poligon";

export function isPoligonActive(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/** Włącza poligon i przechodzi na pierwszy ekran ćwiczenia. */
export function enterPoligon(href: string): void {
  try {
    window.sessionStorage.setItem(KEY, "1");
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
