import { describe, expect, it } from "vitest";

import { greeting, skyColors, skyPhase } from "./sky";

const at = (h: number, m = 0) => new Date(2026, 9, 16, h, m);

describe("personal sky", () => {
  it("follows the local clock: morning, day, evening, night", () => {
    expect(skyPhase(at(4, 59))).toBe("night");
    expect(skyPhase(at(5))).toBe("morning");
    expect(skyPhase(at(10, 59))).toBe("morning");
    expect(skyPhase(at(11))).toBe("day");
    expect(skyPhase(at(17))).toBe("evening");
    expect(skyPhase(at(20, 59))).toBe("evening");
    expect(skyPhase(at(21))).toBe("night");
  });

  it("paints evening as a blue-to-green gradient", () => {
    const { top, bottom } = skyColors("evening");
    const channels = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    const [r1, g1, b1] = channels(top);
    const [r2, g2, b2] = channels(bottom);
    expect(b1).toBeGreaterThan(g1);
    expect(b1).toBeGreaterThan(r1);
    expect(g2).toBeGreaterThan(b2);
    expect(g2).toBeGreaterThan(r2);
  });

  it("greets by time of day", () => {
    expect(greeting(at(9))).toBe("Good morning");
    expect(greeting(at(20))).toBe("Good evening");
  });

  it("mutes the palette in bad weather", () => {
    expect(skyColors("day", "clear").top).toBe("#3f6fae");
    expect(skyColors("day", "wet").top).toContain("color-mix");
  });
});
