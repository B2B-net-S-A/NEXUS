import { describe, expect, it, vi } from "vitest";

import { createNoteFillChannel } from "@/lib/note-fill-channel";

describe("createNoteFillChannel", () => {
  it("przekazuje notatkę formularzowi osoby i mówi, gdy nikt jej nie przyjął", async () => {
    const channel = createNoteFillChannel();
    const receiver = vi.fn().mockResolvedValue(undefined);
    expect(channel.has(7)).toBe(false);
    expect(await channel.send(7, { noteId: 1, text: "x" })).toBe(false);

    const off = channel.register(7, receiver);
    expect(channel.has(7)).toBe(true);
    expect(await channel.send(7, { noteId: 1, text: "Kafka 3 lata" })).toBe(true);
    expect(receiver).toHaveBeenCalledWith({ noteId: 1, text: "Kafka 3 lata" });

    off();
    expect(channel.has(7)).toBe(false);
  });

  it("wyrejestrowanie starego formularza nie zdejmuje nowego i budzi słuchaczy", () => {
    const channel = createNoteFillChannel();
    const listener = vi.fn();
    channel.subscribe(listener);
    const offOld = channel.register(7, vi.fn());
    channel.register(7, vi.fn());
    offOld();
    expect(channel.has(7)).toBe(true);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
