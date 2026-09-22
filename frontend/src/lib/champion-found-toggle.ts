/**
 * Przełącznik „Mamy championa” w nagłówku rekrutacji (audyt 22.09 r2, REC-05).
 *
 * Do tej poprawki handler miał tylko `finally` — odmowa serwera (403, 409,
 * awaria sieci) kończyła się cicho: przycisk wracał do stanu sprzed kliknięcia
 * i nikt nie wiedział, że nic się nie zapisało. Błąd idzie teraz do toastu
 * przez `apiErrorMessage` (backend bywa, że zwraca `detail` jako obiekt).
 */

import { apiErrorMessage } from "@/lib/api-error";

export async function toggleChampionFound(args: {
  jobId: number;
  found: boolean;
  save: (jobId: number, found: boolean) => Promise<unknown>;
  refresh: () => Promise<unknown> | void;
  onError: (message: string) => void;
}): Promise<boolean> {
  try {
    await args.save(args.jobId, args.found);
  } catch (error) {
    args.onError(
      apiErrorMessage(
        error,
        args.found
          ? "Nie udało się oznaczyć, że mamy championa."
          : "Nie udało się cofnąć oznaczenia championa.",
      ),
    );
    return false;
  }
  await args.refresh();
  return true;
}
