import { describe, expect, it, vi } from "vitest";

import {
  APPROVAL_FAILED_HINT,
  describeApprovalSuccess,
  isBackgroundApprovalRunning,
  stageApprovalKey,
  startBackgroundApproval,
} from "@/lib/cv-background-approval";

/**
 * Zatwierdzenie CV w tle żyje dłużej niż okno edytora: zamknięcie okna nie
 * może go przerwać, a wynik wraca toastem (liczba uwag albo prośba o ponowny
 * zapis). Starsze zatwierdzenie tego samego dokumentu, które przegrało
 * z nowszym, nie zgłasza błędu.
 */

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function notifier() {
  return { success: vi.fn(), error: vi.fn() };
}

const response = (findings: number | null, status: string | null = "reviewed") => ({
  data: {
    edit_revision: 3,
    version: 2,
    document_version_id: 9,
    candidate_stage_id: 21,
    status: "finalized" as const,
    snapshot_filename: "CV.docx",
    snapshot_size_bytes: 10,
    content_review_status: status,
    content_review_findings: findings,
  },
});

describe("startBackgroundApproval", () => {
  it("zgłasza liczbę uwag kontroli treści po udanym zatwierdzeniu", async () => {
    const notify = notifier();
    const onSettled = vi.fn();
    const outcome = await startBackgroundApproval(
      { key: stageApprovalKey(1), label: "Jan Kowalski", run: async () => response(2), onSettled },
      notify,
    );
    expect(outcome).toEqual({ status: "approved", findings: 2, reviewStatus: "reviewed" });
    expect(notify.success).toHaveBeenCalledWith(
      "CV zatwierdzone (Jan Kowalski). Kontrola treści zgłosiła 2 uwagi — sprawdź przed wysyłką.",
    );
    expect(notify.error).not.toHaveBeenCalled();
    expect(onSettled).toHaveBeenCalledOnce();
  });

  it("czysty wynik i kontrola, która się nie wykonała, to dwa różne zdania", () => {
    expect(describeApprovalSuccess({ findings: 0, reviewStatus: "verified" })).toBe(
      "CV zatwierdzone. Kontrola treści bez uwag.",
    );
    expect(describeApprovalSuccess({ findings: 0, reviewStatus: "unverified" })).toContain(
      "nie wykonała się",
    );
    expect(describeApprovalSuccess({ findings: 1, reviewStatus: "reviewed" })).toContain("1 uwagę");
    expect(describeApprovalSuccess({ findings: 5, reviewStatus: "reviewed" })).toContain("5 uwag");
  });

  it("porażka mówi, co zrobić, i niesie powód serwera", async () => {
    const notify = notifier();
    const outcome = await startBackgroundApproval(
      {
        key: stageApprovalKey(2),
        run: async () => {
          throw { response: { status: 409, data: { detail: "CV zostało zmienione w innym oknie." } } };
        },
      },
      notify,
    );
    expect(outcome.status).toBe("failed");
    expect(notify.error).toHaveBeenCalledWith(
      `${APPROVAL_FAILED_HINT} (CV zostało zmienione w innym oknie.)`,
    );
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("bez odpowiedzi serwera zostaje sama wskazówka — bez „undefined” w treści", async () => {
    const notify = notifier();
    await startBackgroundApproval(
      { key: stageApprovalKey(3), run: async () => { throw new Error("Network Error"); } },
      notify,
    );
    expect(notify.error).toHaveBeenCalledWith(APPROVAL_FAILED_HINT);
  });

  it("nie zależy od okna: nie przyjmuje sygnału przerwania i trwa po zamknięciu edytora", async () => {
    const pending = deferred<ReturnType<typeof response>>();
    const notify = notifier();
    const run = vi.fn(() => pending.promise);
    const done = startBackgroundApproval({ key: stageApprovalKey(4), run }, notify);
    // `run` wołane bez argumentów — nie ma czego przerwać zamknięciem okna.
    expect(run).toHaveBeenCalledWith();
    expect(isBackgroundApprovalRunning(stageApprovalKey(4))).toBe(true);
    pending.resolve(response(0, "verified"));
    await done;
    expect(isBackgroundApprovalRunning(stageApprovalKey(4))).toBe(false);
    expect(notify.success).toHaveBeenCalledOnce();
  });

  it("starsze zatwierdzenie, które przegrało z nowszym, nie zgłasza błędu", async () => {
    const first = deferred<ReturnType<typeof response>>();
    const second = deferred<ReturnType<typeof response>>();
    const notify = notifier();
    const key = stageApprovalKey(5);
    const older = startBackgroundApproval({ key, run: () => first.promise }, notify);
    const newer = startBackgroundApproval({ key, run: () => second.promise }, notify);
    first.reject({ response: { status: 409, data: { detail: "Nieaktualna rewizja." } } });
    expect(await older).toEqual({ status: "superseded" });
    expect(notify.error).not.toHaveBeenCalled();
    // Nowsze nadal trwa — znacznik „w toku” należy do niego.
    expect(isBackgroundApprovalRunning(key)).toBe(true);
    second.resolve(response(0, "verified"));
    await newer;
    expect(notify.success).toHaveBeenCalledOnce();
    expect(isBackgroundApprovalRunning(key)).toBe(false);
  });
});
