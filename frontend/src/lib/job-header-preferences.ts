/**
 * Preferencja „zwinięty nagłówek rekrutacji" (panel „Zespół i priorytet").
 *
 * Wyniesione ze `app/jobs/[id]/page.tsx` do osobnego modułu, żeby test wiązał
 * się z TĄ SAMĄ wartością, której używa strona — asercja na literał wpisany
 * ponownie w teście sprawdzałaby własną kopię.
 */

export const JOB_HEADER_COLLAPSED_STORAGE_KEY = "nexus:jobHeaderCollapsed:v3";

/**
 * Bez zapisanej preferencji panel jest **ZWINIĘTY**.
 *
 * Rozwinięty zabiera ~40 % ekranu 1440×840 na KAŻDEJ zakładce rekrutacji,
 * a jego treść (właściciel, hiring manager, Priority Work) jest albo
 * w podtytule jobbara, albo o jedno kliknięcie dalej. Krok, po który przyszedł
 * użytkownik — pipeline, screening, CV — jest wtedy pod ekranem.
 *
 * Klucz podbity do `:v3` RAZ, razem z falą 3 „parytet z makietami" (8.09.2026):
 * makiety nie mają rozwiniętego panelu na żadnym kroku, a preferencja `:v2`
 * została zapisana w czasach, gdy panel był JEDYNYM miejscem właściciela
 * i hiring managera — dziś są w podtytule jobbara i w doku. Po podbiciu każdy
 * startuje zwinięty; kto panel rozwinie, ma to zapamiętane pod nowym kluczem.
 * Kolejne zmiany domyślnej wartości NIE podbijają klucza — zapisana
 * preferencja użytkownika wygrywa z domyślną.
 */
export const JOB_HEADER_COLLAPSED_DEFAULT = true;
