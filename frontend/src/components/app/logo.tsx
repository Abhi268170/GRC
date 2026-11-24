import { LOGO_HEIGHT, LOGO_WIDTH, MARK_PATHS, MARK_TRANSFORM, WORDMARK_PATHS, WORDMARK_TRANSFORM } from "./brand-paths";

/**
 * The TrustUp logo: the mark with the "trustup" wordmark to its right. Size it by height (e.g. h-7).
 *
 * The mark's colours never change. The wordmark follows the theme: the logo's dark green on light
 * backgrounds, its pale green on dark ones (the pale green is too faint on white).
 * Static SVG files for other uses (stacked logo, mark only, app icon) are in /public/brand/.
 */
export function Logo({ className = "h-7" }: { className?: string }) {
  return (
    <svg viewBox={`0 0 ${LOGO_WIDTH} ${LOGO_HEIGHT}`} className={`w-auto ${className}`} role="img" aria-label="TrustUp">
      <g transform={MARK_TRANSFORM}>
        {MARK_PATHS.map((p, i) => <path key={i} d={p.d} fill={p.fill} />)}
      </g>
      <g transform={WORDMARK_TRANSFORM} className="fill-[#288253] dark:fill-[#A9D4A2]">
        {WORDMARK_PATHS.map((d, i) => <path key={i} d={d} />)}
      </g>
    </svg>
  );
}
