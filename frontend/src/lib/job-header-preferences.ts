/**
 * Preferencja „zwinięty nagłówek rekrutacji" (panel „Zespół i priorytet").
 *
 * Wyniesione ze `app/jobs/[id]/page.tsx` do osobnego modułu, żeby test wiązał
 * się z TĄ SAMĄ wartością, której używa strona — asercja na literał wpisany
 * ponownie w teście sprawdzałaby własną kopię.
 */

export const JOB_HEADER_COLLAPSED_STORAGE_KEY = "nexus:jobHeaderCollapsed:v2";

/**
 * Bez zapisanej preferencji panel jest **ZWINIĘTY**.
 *
 * Rozwinięty zabiera ~40 % ekranu 1440×840 na KAŻDEJ zakładce rekrutacji,
 * a jego treść (właściciel, hiring manager, Priority Work) jest albo
 * w podtytule jobbara, albo o jedno kliknięcie dalej. Krok, po który przyszedł
 * użytkownik — pipeline, screening, CV — jest wtedy pod ekranem.
 *
 * Wersja klucza (`:v2`) NIE jest tu do podbijania przy zmianie tej wartości:
 * podbicie skasowałoby zapamiętany wybór wszystkim, którzy panel świadomie
 * rozwinęli. Zapisana preferencja użytkownika wygrywa z domyślną — zawsze.
 */
export const JOB_HEADER_COLLAPSED_DEFAULT = true;
