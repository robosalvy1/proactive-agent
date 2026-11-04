/** A small, warm palette so every agent name lands on a color that looks intentional. */
export interface AvatarPalette {
  light: string;
  base: string;
  shade: string;
  cheek: string;
}

export const AVATAR_COLORS = ["oat", "peach", "sage", "lilac", "sky", "rose"] as const;
export type AvatarColorId = (typeof AVATAR_COLORS)[number];
/** What the person picked in settings: automatic (from the name), a named swatch, or any #rrggbb. */
export type AvatarChoice = "auto" | AvatarColorId | `#${string}`;

export const AVATAR_PALETTES: Record<AvatarColorId, AvatarPalette> = {
  oat: { light: "#fbf1e4", base: "#ecd3b4", shade: "#c9a57f", cheek: "#f2a99a" },
  peach: { light: "#ffe9de", base: "#f7c2a6", shade: "#d98f6c", cheek: "#ef8f86" },
  sage: { light: "#eaf4e4", base: "#c4dcb4", shade: "#8fb27a", cheek: "#efa2a0" },
  lilac: { light: "#efe9fb", base: "#d3c6f1", shade: "#9f8cd4", cheek: "#f0a3c4" },
  sky: { light: "#e5f1fb", base: "#b9d7f0", shade: "#7fa8d2", cheek: "#f2a7b4" },
  rose: { light: "#fde8ee", base: "#f5c3d1", shade: "#d68ea3", cheek: "#ee8fa6" },
};

const HEX = /^#[0-9a-f]{6}$/i;

/** Stable per name: the same agent always looks the same, across devices. */
export function colorFor(name: string): AvatarColorId {
  let hash = 0;
  for (const char of name.trim().toLowerCase()) hash = (hash * 31 + char.codePointAt(0)!) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

export function paletteFor(name: string): AvatarPalette {
  return AVATAR_PALETTES[colorFor(name)];
}

export function isAvatarChoice(value: unknown): value is AvatarChoice {
  return value === "auto" || AVATAR_COLORS.includes(value as AvatarColorId) || (typeof value === "string" && HEX.test(value));
}

function toHsl(hex: string): [number, number, number] {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l * 100];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s * 100, l * 100];
}

/** Hex out, so the value works in any SVG stop-color. */
function hsl(h: number, s: number, l: number): string {
  const sat = s / 100;
  const light = l / 100;
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const value = light - sat * Math.min(light, 1 - light) * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(value * 255).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

/** Any picked color becomes a soft three-stop body like the built-in swatches, so it never looks pasted on. */
export function paletteFromHex(hex: string): AvatarPalette {
  const [h, s, l] = toHsl(hex);
  const sat = Math.min(s, 70);
  const base = Math.min(Math.max(l, 52), 80);
  return {
    light: hsl(h, sat * 0.7, Math.min(base + 14, 95)),
    base: hsl(h, sat, base),
    shade: hsl(h, Math.min(sat + 8, 75), Math.max(base - 18, 30)),
    cheek: hsl(350, 75, 74),
  };
}

export function resolvePalette(name: string, choice: AvatarChoice = "auto"): AvatarPalette {
  if (choice === "auto") return paletteFor(name);
  if (HEX.test(choice)) return paletteFromHex(choice);
  return AVATAR_PALETTES[choice as AvatarColorId] ?? paletteFor(name);
}
