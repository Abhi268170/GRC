import { LOGO_HEIGHT, LOGO_WIDTH, MARK_SIZE, MARK_Y, TRUST_PATH, UP_PATH } from "./brand-paths";

/**
 * TrustUp brand. Colours follow the app tokens, so the logo adapts to light and dark mode:
 * - auto: first link + "trust" in foreground (ink / off-white), second link in lime,
 *         "up" in brand-strong (dark green on light, lime on dark)
 * - lime: for lime backgrounds (ink + off-white link, all-ink wordmark)
 * Static SVG files for other uses are in /public/brand/.
 */
type Tone = "auto" | "lime";

const TONES: Record<Tone, { link1: string; link2: string; trust: string; up: string }> = {
  auto: { link1: "var(--foreground)", link2: "var(--brand)", trust: "var(--foreground)", up: "var(--brand-strong)" },
  lime: { link1: "#0F0F0F", link2: "#F2F2F2", trust: "#0F0F0F", up: "#0F0F0F" },
};

function Links({ link1, link2 }: { link1: string; link2: string }) {
  return (
    <g transform="rotate(-45 32 32)">
      <rect x="5" y="23" width="32" height="18" rx="9" fill="none" stroke={link1} strokeWidth="5.5" />
      <rect x="27" y="23" width="32" height="18" rx="9" fill="none" stroke={link2} strokeWidth="5.5" />
    </g>
  );
}

/** The two-link mark on its own. */
export function LogoMark({ className = "size-8", tone = "auto" }: { className?: string; tone?: Tone }) {
  const c = TONES[tone];
  return (
    <svg viewBox="0 0 64 64" className={className} role="img" aria-label="TrustUp">
      <Links link1={c.link1} link2={c.link2} />
    </svg>
  );
}

/** Mark + "trustup" wordmark. Size it by height (e.g. h-7). */
export function Logo({ className = "h-7", tone = "auto" }: { className?: string; tone?: Tone }) {
  const c = TONES[tone];
  return (
    <svg viewBox={`0 0 ${LOGO_WIDTH} ${LOGO_HEIGHT}`} className={`w-auto ${className}`} role="img" aria-label="TrustUp">
      <svg x="0" y={MARK_Y} width={MARK_SIZE} height={MARK_SIZE} viewBox="0 0 64 64">
        <Links link1={c.link1} link2={c.link2} />
      </svg>
      <path d={TRUST_PATH} fill={c.trust} />
      <path d={UP_PATH} fill={c.up} />
    </svg>
  );
}
