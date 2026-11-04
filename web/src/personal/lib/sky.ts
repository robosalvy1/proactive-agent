/** Time-of-day backdrop, so the home feels like the user's own moment rather than a fixed theme. */
export type SkyPhase = "morning" | "day" | "evening" | "night";
export type SkyMood = "clear" | "cloudy" | "wet";

export function skyPhase(now: Date): SkyPhase {
  const hour = now.getHours();
  if (hour < 5 || hour >= 21) return "night";
  if (hour < 11) return "morning";
  if (hour < 17) return "day";
  return "evening";
}

export function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 5) return "Up late";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

const SKIES: Record<SkyPhase, { top: string; middle: string; bottom: string; glow: string }> = {
  // Sunrise: soft blue overhead warming through rose into gold at the horizon.
  morning: { top: "#7fa7dc", middle: "#f2b8b4", bottom: "#ffd79e", glow: "rgba(255,222,165,0.6)" },
  day: { top: "#3f6fae", middle: "#79a5d6", bottom: "#c4d9ee", glow: "rgba(255,255,255,0.55)" },
  // Evening: deep blue settling into sea green.
  evening: { top: "#123a6b", middle: "#1d6a8c", bottom: "#3daa8a", glow: "rgba(120,230,190,0.3)" },
  night: { top: "#0d1530", middle: "#1f2d57", bottom: "#3a4a78", glow: "rgba(150,170,255,0.18)" },
};

/** Clouds and rain mute the palette instead of switching themes. */
export function skyColors(phase: SkyPhase, mood: SkyMood = "clear") {
  const sky = SKIES[phase];
  const mute = mood === "clear" ? 0 : mood === "cloudy" ? 28 : 45;
  const mix = (c: string) => (mute ? `color-mix(in srgb, ${c} ${100 - mute}%, #8e99a8)` : c);
  return { top: mix(sky.top), middle: mix(sky.middle), bottom: mix(sky.bottom), glow: sky.glow };
}
