/**
 * Preferencja „zwinięta szyna Otwarte karty" (`JobTabsRail.tsx`, lewy pasek
 * na trasach szczegółów rekrutacji).
 *
 * Wyniesione z ręcznego `useState`/`localStorage` (dawny `COLLAPSE_KEY =
 * "nexus.jobTabsRail.collapsed"` w komponencie) do `useLocalStorageFlag` —
 * ten sam wzorzec co `job-header-preferences.ts`.
 *
 * Klucz podbity do `.v2`: domyślna wartość zmienia się z „rozwinięta" na
 * „zwinięta" (fala 3 „mniej scrolla, więcej edytora" — szyna 240 px + nav
 * 230 px + dok 360 px zostawiało na 1440 px zaledwie 251 px na sam edytor
 * Championa). Bez bumpu zapisane „0" sprzed tej zmiany trzymałoby wszystkich
 * przy starym, rozwiniętym domyślnym stanie.
 */
export const JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY = "nexus.jobTabsRail.collapsed.v2";

export const JOB_TABS_RAIL_COLLAPSED_DEFAULT = true;
