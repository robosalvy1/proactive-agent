import { Check, LoaderCircle, Palette, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { errorMessage } from "@/lib/api-error";
import { fetchJSON } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AgentAvatar } from "./AgentAvatar";
import { usePersonalCopy } from "./copy";
import { AVATAR_COLORS, AVATAR_PALETTES, paletteFor, type AvatarChoice, type AvatarColorId } from "./lib/avatar";

interface SettingsPanelProps {
  profile: string;
  agentName: string;
  color: AvatarChoice;
  compact: boolean;
  onColor: (color: AvatarChoice) => void;
  onClose: () => void;
}

const LABELS = {
  oat: "colorOat",
  peach: "colorPeach",
  sage: "colorSage",
  lilac: "colorLilac",
  sky: "colorSky",
  rose: "colorRose",
} as const satisfies Record<AvatarColorId, string>;

const swatch =
  "relative flex h-12 w-12 items-center justify-center rounded-full ring-offset-2 ring-offset-white/80 transition active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900";

function saveAvatarColor(profile: string, color: AvatarChoice) {
  return fetchJSON(`/api/personal/preferences?profile=${encodeURIComponent(profile)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ avatar_color: color }),
  });
}

/** Home settings the person controls. The agent's look is theirs to pick; the agent never changes it. */
export function SettingsPanel({ profile, agentName, color, compact, onColor, onClose }: SettingsPanelProps) {
  const p = usePersonalCopy();
  const [preview, setPreview] = useState<AvatarChoice>(color);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const saved = useRef(color);
  const timer = useRef<number | undefined>(undefined);
  // A custom color still waiting out the picker's debounce; saved on close instead of dropped.
  const pendingColor = useRef<AvatarChoice | null>(null);
  const latest = useRef({ profile, onColor });
  useEffect(() => {
    latest.current = { profile, onColor };
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(
    () => () => {
      window.clearTimeout(timer.current);
      const next = pendingColor.current;
      if (!next) return;
      const { profile: owner, onColor: notify } = latest.current;
      saveAvatarColor(owner, next).then(
        () => notify(next),
        () => {},
      );
    },
    [],
  );

  const commit = async (next: AvatarChoice) => {
    setSaving(true);
    setError("");
    try {
      await saveAvatarColor(profile, next);
      saved.current = next;
      onColor(next);
    } catch (cause) {
      setPreview(saved.current);
      setError(`${p.settingsSaveError} ${errorMessage(cause)}`.trim());
    }
    setSaving(false);
  };

  const choose = (next: AvatarChoice) => {
    window.clearTimeout(timer.current);
    pendingColor.current = null;
    setPreview(next);
    void commit(next);
  };

  // The native picker fires continuously while dragging; preview live, save once it settles.
  const pickCustom = (hex: string) => {
    setPreview(hex as AvatarChoice);
    pendingColor.current = hex as AvatarChoice;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      pendingColor.current = null;
      void commit(hex as AvatarChoice);
    }, 400);
  };

  const custom = preview.startsWith("#") ? preview : null;
  const auto = paletteFor(agentName);

  return (
    <div className="fixed inset-0 z-50">
      <button type="button" aria-label={p.done} className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <div
        role="dialog"
        aria-modal
        aria-label={p.settingsTitle}
        className={cn(
          "absolute flex flex-col gap-5 border border-white/60 bg-white/85 p-5 shadow-[0_20px_60px_-20px_rgba(20,45,90,0.45)] backdrop-blur-2xl",
          compact
            ? "personal-sheet personal-safe-bottom inset-x-0 bottom-0 max-h-[88dvh] overflow-y-auto rounded-t-[32px] pt-3"
            : "personal-rise right-6 top-24 w-[23rem] rounded-[28px]",
        )}
      >
        {compact && <span aria-hidden className="mx-auto h-1.5 w-10 rounded-full bg-neutral-900/20" />}
        <div className="flex items-center justify-between">
          <h2 className="text-[18px] font-semibold text-neutral-900">{p.settingsTitle}</h2>
          <button type="button" onClick={onClose} aria-label={p.done} className="flex h-10 w-10 items-center justify-center rounded-full bg-white/80 text-neutral-800 hover:bg-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <section className="flex flex-col gap-4" aria-labelledby="personal-avatar-color">
          <div className="flex items-center gap-4 rounded-3xl bg-white/80 p-4">
            <AgentAvatar name={agentName} color={preview} className="h-16 w-16 shrink-0" />
            <div className="min-w-0">
              <h3 id="personal-avatar-color" className="flex items-center gap-2 text-[16px] font-medium text-neutral-900">
                {p.avatarColor.replace("{agent}", agentName)}
                {saving && <LoaderCircle className="h-4 w-4 animate-spin text-neutral-500" />}
              </h3>
              <p className="text-[13px] leading-5 text-neutral-500">{p.avatarColorHint.replace("{agent}", agentName)}</p>
            </div>
          </div>

          <div role="radiogroup" aria-labelledby="personal-avatar-color" className="grid grid-cols-4 justify-items-center gap-3">
            <button
              type="button"
              role="radio"
              aria-checked={preview === "auto"}
              aria-label={p.avatarAuto}
              title={p.avatarAuto}
              onClick={() => choose("auto")}
              className={cn(swatch, preview === "auto" && "ring-2 ring-neutral-900")}
              style={{ background: `conic-gradient(${AVATAR_COLORS.map((id) => AVATAR_PALETTES[id].base).join(",")},${AVATAR_PALETTES.oat.base})` }}
            >
              <span className="h-6 w-6 rounded-full border-2 border-white" style={{ background: auto.base }} />
            </button>
            {AVATAR_COLORS.map((id) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={preview === id}
                aria-label={p[LABELS[id]]}
                title={p[LABELS[id]]}
                onClick={() => choose(id)}
                className={cn(swatch, preview === id && "ring-2 ring-neutral-900")}
                style={{ background: `radial-gradient(circle at 34% 28%, ${AVATAR_PALETTES[id].light}, ${AVATAR_PALETTES[id].base} 60%, ${AVATAR_PALETTES[id].shade})` }}
              >
                {preview === id && <Check className="h-5 w-5 text-neutral-900/70" />}
              </button>
            ))}
            <label
              title={p.avatarCustom}
              className={cn(swatch, "cursor-pointer overflow-hidden bg-white focus-within:ring-2 focus-within:ring-neutral-900", custom && "ring-2 ring-neutral-900")}
              style={custom ? { background: custom } : undefined}
            >
              <Palette className={cn("h-5 w-5", custom ? "text-white drop-shadow" : "text-neutral-700")} />
              <input
                type="color"
                aria-label={p.avatarCustom}
                value={custom ?? auto.base}
                onChange={(e) => pickCustom(e.target.value)}
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
              />
            </label>
          </div>
          {error && <p role="alert" className="text-[13px] text-rose-700">{error}</p>}
        </section>
      </div>
    </div>
  );
}
