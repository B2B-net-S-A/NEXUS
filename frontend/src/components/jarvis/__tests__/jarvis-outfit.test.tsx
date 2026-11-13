import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JarvisCharacter } from "@/components/jarvis/characters/JarvisCharacter";
import { hasOutfit } from "@/components/jarvis/characters/JarvisOutfit";

describe("robot w stroju świata", () => {
  it("ubiera tylko robota i tylko w światach ze strojem", () => {
    expect(hasOutfit("robot", "winter")).toBe(true);
    expect(hasOutfit("robot_gold", "pitstop")).toBe(true);
    expect(hasOutfit("owl", "winter")).toBe(false);
    expect(hasOutfit("robot", "zen")).toBe(false);
    expect(hasOutfit("robot", null)).toBe(false);
  });

  it("rysuje czapkę w Zimie i nic bez świata", () => {
    const { container, rerender } = render(<JarvisCharacter id="robot" outfit="winter" />);
    expect(container.querySelector('[data-outfit="winter"]')).not.toBeNull();
    rerender(<JarvisCharacter id="robot" outfit={null} />);
    expect(container.querySelector("[data-outfit]")).toBeNull();
  });
});
