"use client";

/**
 * Ciężkie warsztaty panelu osoby — za granicą `next/dynamic`.
 *
 * `/jobs/[id]` to gorąca trasa, a „CV do klienta" wciąga cały
 * `CVGeneratorStandaloneV2` (~1800 linii: combobox, dropzone, modale podglądu
 * i udostępniania). Panel osoby jest teraz DOMYŚLNYM widokiem rekrutacji, więc
 * statyczny import warsztatu w `PersonPanel` przeniósłby ten koszt na każde
 * otwarcie rekrutacji — także wtedy, gdy nikt nie zajrzy do sekcji CV.
 * Pilnuje tego `heavy-bundle-boundaries.test.ts`.
 *
 * `loading` jest obowiązkowy: bez niego sekcja jest pusta, dopóki chunk się
 * nie pobierze, a pustka czyta się jak „brak danych".
 */

import dynamic from "next/dynamic";

function WorkbenchChunkLoading() {
  return <p className="p-3 text-sm text-muted-foreground">Ładowanie…</p>;
}

export const ScreeningWorkbench = dynamic(
  () =>
    import("@/components/v2/jobs/ScreeningWorkbench").then(
      (m) => m.ScreeningWorkbench,
    ),
  { ssr: false, loading: WorkbenchChunkLoading },
);

export const CvHandoffWorkbench = dynamic(
  () =>
    import("@/components/v2/jobs/CvHandoffWorkbench").then(
      (m) => m.CvHandoffWorkbench,
    ),
  { ssr: false, loading: WorkbenchChunkLoading },
);
