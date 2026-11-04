import { useId } from "react";

import { cn } from "@/lib/utils";
import { resolvePalette, type AvatarChoice } from "./lib/avatar";

interface AgentAvatarProps {
  name: string;
  color?: AvatarChoice;
  size?: number;
  thinking?: boolean;
  className?: string;
}

/** A soft little companion, colored by the person's choice (or the agent's name); it breathes, blinks, and glances around while thinking. */
export function AgentAvatar({ name, color = "auto", size = 40, thinking = false, className }: AgentAvatarProps) {
  const id = useId().replace(/:/g, "");
  const palette = resolvePalette(name, color);
  return (
    <svg
      aria-hidden
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={cn("personal-avatar overflow-visible", thinking && "is-thinking", className)}
    >
      <defs>
        <radialGradient id={`${id}-body`} cx="34%" cy="26%" r="78%">
          <stop offset="0%" stopColor={palette.light} />
          <stop offset="58%" stopColor={palette.base} />
          <stop offset="100%" stopColor={palette.shade} />
        </radialGradient>
        <radialGradient id={`${id}-shine`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#fff" stopOpacity="0.85" />
          <stop offset="100%" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse className="personal-avatar-shadow" cx="32" cy="60" rx="17" ry="2.6" fill="#1b2a44" opacity="0.16" />
      <g className="personal-avatar-body">
        <path
          d="M32 5C47.5 5 56 17 56 33v15.5C56 54 52 58 46.5 58h-29C12 58 8 54 8 48.5V33C8 17 16.5 5 32 5Z"
          fill={`url(#${id}-body)`}
        />
        <ellipse cx="23" cy="16" rx="9" ry="5.5" fill={`url(#${id}-shine)`} transform="rotate(-24 23 16)" />
        <g className="personal-avatar-eyes">
          <g className="personal-avatar-eye">
            <ellipse cx="24.5" cy="31" rx="2.6" ry="3.4" fill="#2a2420" />
            <circle cx="25.4" cy="29.7" r="0.9" fill="#fff" />
          </g>
          <g className="personal-avatar-eye">
            <ellipse cx="39.5" cy="31" rx="2.6" ry="3.4" fill="#2a2420" />
            <circle cx="40.4" cy="29.7" r="0.9" fill="#fff" />
          </g>
        </g>
        <ellipse cx="19.5" cy="38" rx="3.4" ry="2" fill={palette.cheek} opacity="0.45" />
        <ellipse cx="44.5" cy="38" rx="3.4" ry="2" fill={palette.cheek} opacity="0.45" />
      </g>
    </svg>
  );
}
