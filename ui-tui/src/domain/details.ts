import type { DetailsMode, SectionName, SectionVisibility } from '../types.js'

const MODES = ['hidden', 'collapsed', 'expanded'] as const

export const SECTION_NAMES = ['thinking', 'tools', 'subagents', 'activity'] as const

// Explicit section settings and in-session /details commands take precedence.
// Routine activity stays out of the transcript; thinking and tools remain expandable.
const SECTION_DEFAULTS: SectionVisibility = {
  activity: 'hidden'
}

const THINKING_FALLBACK: Record<string, DetailsMode> = {
  collapsed: 'collapsed',
  full: 'expanded',
  truncated: 'collapsed'
}

const norm = (v: unknown) =>
  String(v ?? '')
    .trim()
    .toLowerCase()

export const parseDetailsMode = (v: unknown): DetailsMode | null => MODES.find(m => m === norm(v)) ?? null

export const isSectionName = (v: unknown): v is SectionName =>
  typeof v === 'string' && (SECTION_NAMES as readonly string[]).includes(v)

export const resolveDetailsMode = (d?: { details_mode?: unknown; thinking_mode?: unknown } | null): DetailsMode =>
  parseDetailsMode(d?.details_mode) ?? THINKING_FALLBACK[norm(d?.thinking_mode)] ?? 'collapsed'

// Build SectionVisibility from a free-form blob.  Unknown section names and
// invalid modes are dropped silently — partial overrides are intentional, so
// missing keys fall through to SECTION_DEFAULTS / global at lookup time.
export const resolveSections = (raw: unknown): SectionVisibility =>
  raw && typeof raw === 'object' && !Array.isArray(raw)
    ? (Object.fromEntries(
        Object.entries(raw as Record<string, unknown>)
          .map(([k, v]) => [k, parseDetailsMode(v)] as const)
          .filter(([k, m]) => !!m && isSectionName(k))
      ) as SectionVisibility)
    : {}

// Explicit section settings win; /details applies its global mode immediately.
// Otherwise thinking/tools follow the persisted global mode (collapsed by default).
export const sectionMode = (
  name: SectionName,
  global: DetailsMode,
  sections?: SectionVisibility,
  commandOverride = false
): DetailsMode => sections?.[name] ?? (commandOverride ? global : (SECTION_DEFAULTS[name] ?? global))

export const nextDetailsMode = (m: DetailsMode): DetailsMode => MODES[(MODES.indexOf(m) + 1) % MODES.length]!
