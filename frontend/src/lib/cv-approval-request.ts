import { withCvGenerationRequest } from "./cv-generation-request";

export type CvReviewState = {
  review_id: number | null;
  status: "queued" | "running" | "verified" | "rejected" | "failed" | "interrupted" | "cancelled" | "stale";
  error_code: string | null;
};

function abortCheck(signal?: AbortSignal) {
  if (signal?.aborted) throw new Error("Przerwano oczekiwanie. Kontrolę możesz sprawdzić ponownie.");
}

function pause(signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const finish = () => { signal?.removeEventListener("abort", cancel); resolve(); };
    const timer = setTimeout(finish, 1000);
    const cancel = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
      reject(new Error("Przerwano oczekiwanie. Kontrolę możesz sprawdzić ponownie."));
    };
    signal?.addEventListener("abort", cancel, {once: true});
    if (signal?.aborted) cancel();
  });
}

/** Keep the same receipt through enqueue, polling and uncertain responses. */
export async function reviewBeforeFinalize<T>(path: string,
  payload: {content_html: string; expected_revision: number},
  transport: {
    start: (key: string) => Promise<CvReviewState>;
    get: (id: number) => Promise<CvReviewState>;
    finalize: () => Promise<T>;
  }, signal?: AbortSignal): Promise<T> {
  const outcome = await withCvGenerationRequest(path, payload, async key => {
    abortCheck(signal);
    let state = await transport.start(key);
    const deadline = Date.now() + 120_000;
    while (state.status === "queued" || state.status === "running") {
      abortCheck(signal);
      if (state.review_id == null) throw new Error("Brak identyfikatora kontroli CV.");
      if (Date.now() >= deadline) throw new Error("Kontrola nadal trwa. Kliknij ponownie, aby sprawdzić tę samą próbę.");
      await pause(signal);
      state = await transport.get(state.review_id);
    }
    abortCheck(signal);
    if (state.status !== "verified") {
      const messages = {
        rejected: "Treść CV nie została potwierdzona w źródłach. Popraw zmienione informacje.",
        stale: "Szkic zmienił się podczas kontroli. Wczytaj aktualną wersję CV.",
        interrupted: "Kontrola została przerwana. Sprawdź dokument przed ponowną próbą.",
        cancelled: "Kontrola została anulowana.",
        failed: "Kontrola CV nie powiodła się. Dokument nie został zatwierdzony.",
      };
      // A known terminal result clears the receipt, but never retries itself.
      return {error: messages[state.status]} as const;
    }
    return {value: await transport.finalize()} as const;
  });
  if ("error" in outcome) throw new Error(outcome.error);
  return outcome.value;
}
