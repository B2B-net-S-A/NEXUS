import { describe, expect, it, vi } from "vitest";
import { CvDraftSession } from "../cv-draft-session";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("CV draft persistence", () => {
  it("immediate approval sends the current edit atomically", async () => {
    const finalize = vi.fn().mockResolvedValue({ edit_revision: 2 });
    const save = vi.fn();
    const session = new CvDraftSession("old", 1, false, { save, finalize }, vi.fn());
    session.edit("new");
    await session.finalize();
    expect(finalize).toHaveBeenCalledWith("new", 1);
    expect(save).not.toHaveBeenCalled();
    expect(session.state).toBe("finalized");
  });

  it("waits for the older save then approves the newer text with its returned revision", async () => {
    const pending = deferred<{ edit_revision: number }>();
    const save = vi.fn().mockReturnValue(pending.promise);
    const finalize = vi.fn().mockResolvedValue({ edit_revision: 3 });
    const session = new CvDraftSession("old", 1, false, { save, finalize }, vi.fn());
    session.edit("first");
    const saving = session.save();
    session.edit("second");
    const approval = session.finalize();
    expect(finalize).not.toHaveBeenCalled();
    pending.resolve({ edit_revision: 2 });
    await Promise.all([saving, approval]);
    expect(finalize).toHaveBeenCalledWith("second", 2);
    expect(session.html).toBe("second");
  });

  it("failed autosave keeps text and retries the same revision", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ edit_revision: 2 });
    const session = new CvDraftSession("old", 1, false, { save, finalize: vi.fn() }, vi.fn());
    session.edit("new");
    await expect(session.save()).rejects.toThrow("offline");
    expect(session.state).toBe("error");
    expect(session.html).toBe("new");
    await session.save();
    expect(save).toHaveBeenLastCalledWith("new", 1);
    expect(session.state).toBe("saved");
  });

  it("a save response never erases newer typing or marks it saved", async () => {
    const pending = deferred<{ edit_revision: number }>();
    const session = new CvDraftSession("old", 1, false, {
      save: () => pending.promise, finalize: vi.fn(),
    }, vi.fn());
    session.edit("first");
    const saving = session.save();
    session.edit("second");
    pending.resolve({ edit_revision: 2 });
    await saving;
    expect(session.html).toBe("second");
    expect(session.state).toBe("unsaved");
  });

  it("does not approve after an in-flight save fails", async () => {
    const pending = deferred<{ edit_revision: number }>();
    const finalize = vi.fn();
    const session = new CvDraftSession("old", 1, false, { save: () => pending.promise, finalize }, vi.fn());
    session.edit("new");
    const saving = session.save();
    const approval = session.finalize();
    pending.reject(new Error("conflict"));
    await expect(saving).rejects.toThrow("conflict");
    await expect(approval).rejects.toThrow("conflict");
    expect(finalize).not.toHaveBeenCalled();
    expect(session.html).toBe("new");
  });
});
