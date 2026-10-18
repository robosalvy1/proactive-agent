import { describe, expect, it } from "vitest";

import { AVATAR_PALETTES, isAvatarChoice, paletteFor, paletteFromHex, resolvePalette } from "./avatar";

describe("agent avatar palette", () => {
  it("is stable per name, ignoring case and spacing", () => {
    expect(paletteFor("Muse")).toBe(paletteFor(" muse "));
  });

  it("spreads different names across the palette", () => {
    const names = ["Muse", "Juniper", "Hermes", "Atlas", "Pip", "Nova", "Sage", "Echo"];
    expect(new Set(names.map(paletteFor)).size).toBeGreaterThan(2);
    for (const name of names) expect(Object.values(AVATAR_PALETTES)).toContain(paletteFor(name));
  });

  it("uses the color picked in settings over the name's default", () => {
    expect(resolvePalette("Muse", "auto")).toBe(paletteFor("Muse"));
    expect(resolvePalette("Muse", "lilac")).toBe(AVATAR_PALETTES.lilac);
    expect(resolvePalette("Muse", "#ff0000")).toEqual(paletteFromHex("#ff0000"));
  });

  it("softens any custom color into a light-to-shade body", () => {
    const palette = paletteFromHex("#0000ff");
    for (const stop of [palette.light, palette.base, palette.shade]) expect(stop).toMatch(/^#[0-9a-f]{6}$/);
    const lightness = (hex: string) => [1, 3, 5].reduce((sum, i) => sum + parseInt(hex.slice(i, i + 2), 16), 0);
    expect(lightness(palette.light)).toBeGreaterThan(lightness(palette.base));
    expect(lightness(palette.base)).toBeGreaterThan(lightness(palette.shade));
    expect(paletteFromHex("#000000").base).not.toBe("#000000");
  });

  it("accepts only known choices", () => {
    for (const ok of ["auto", "sage", "#a1b2c3"]) expect(isAvatarChoice(ok)).toBe(true);
    for (const bad of ["teal", "#abc", "url(x)", 3, null]) expect(isAvatarChoice(bad)).toBe(false);
  });
});
