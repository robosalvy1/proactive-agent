import { skyColors, type SkyMood, type SkyPhase } from "./lib/sky";

interface SkyProps {
  phase: SkyPhase;
  mood: SkyMood;
}

const CLOUDS = [
  { left: "-8%", top: "8%", size: 58, delay: "0s", duration: "95s", opacity: 0.55 },
  { left: "38%", top: "26%", size: 44, delay: "-30s", duration: "120s", opacity: 0.45 },
  { left: "62%", top: "-6%", size: 52, delay: "-60s", duration: "140s", opacity: 0.5 },
  { left: "10%", top: "62%", size: 64, delay: "-15s", duration: "110s", opacity: 0.6 },
  { left: "70%", top: "58%", size: 50, delay: "-80s", duration: "130s", opacity: 0.4 },
];

/** A soft, slowly drifting sky that follows the user's time of day and weather. */
export function Sky({ phase, mood }: SkyProps) {
  const colors = skyColors(phase, mood);
  const cloudTint = phase === "night" ? "rgba(190,200,240,0.16)" : phase === "evening" ? "rgba(205,240,230,0.2)" : "rgba(255,255,255,0.9)";
  const cloudBoost = mood === "clear" ? 1 : 1.35;

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0 transition-[background] duration-[2000ms]"
        style={{ background: `linear-gradient(180deg, ${colors.top} 0%, ${colors.middle} 55%, ${colors.bottom} 100%)` }}
      />
      <div
        className="absolute inset-0"
        style={{ background: `radial-gradient(60% 50% at 62% 48%, ${colors.glow}, transparent 70%)` }}
      />
      {CLOUDS.map((cloud, i) => (
        <div
          key={i}
          className="personal-cloud absolute rounded-full"
          style={{
            left: cloud.left,
            top: cloud.top,
            width: `${cloud.size}vw`,
            height: `${cloud.size * 0.55}vw`,
            opacity: Math.min(1, cloud.opacity * cloudBoost),
            background: `radial-gradient(closest-side, ${cloudTint}, transparent)`,
            animationDelay: cloud.delay,
            animationDuration: cloud.duration,
          }}
        />
      ))}
      {phase === "night" && <div className="personal-stars absolute inset-0" />}
    </div>
  );
}
