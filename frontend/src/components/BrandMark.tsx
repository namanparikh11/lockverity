/**
 * Lockverity brand mark component.
 *
 * Renders the original Lockverity mark defined in
 * ``frontend/public/brand/lockverity-mark.svg`` and the
 * app-icon variant in
 * ``frontend/public/brand/lockverity-app-icon.svg``.
 *
 * The geometry is hand-authored: an interlocking L and V that
 * suggests an evidence link. The mark is not generated from
 * a raster concept and is not derived from any third-party
 * logo asset. See ``docs/brand-assets.md`` for the full
 * ownership and originality note.
 *
 * Two visual variants are exposed:
 *
 * - ``variant="mark"``: the bare L+V glyph, sized to fit the
 *   parent. Foreground uses ``currentColor`` so it inherits
 *   the surrounding text colour. Use this inline next to the
 *   product name in the header and footer.
 * - ``variant="app-icon"``: the rounded-square mark used as
 *   the application icon. Always uses the deep ink
 *   background and the light foreground, regardless of the
 *   surrounding colour scheme.
 *
 * Both variants honour the ``prefers-reduced-motion``
 * setting and are inert to animation: there is no animated
 * decoration, no transitions, and no transforms applied at
 * render time.
 */
export type BrandMarkVariant = "mark" | "app-icon";

export interface BrandMarkProps {
  variant?: BrandMarkVariant;
  size?: number;
  className?: string;
  /**
   * Accessible label for screen readers. The mark is
   * decorative by default; supply a label when the mark is
   * the only element that conveys the product identity
   * (for example, in the application icon spot).
   */
  ariaLabel?: string;
  /**
   * When ``true`` the mark is announced as a decorative
   * image and is hidden from the accessibility tree. Use
   * this when the product name is rendered adjacent to the
   * mark, so screen readers do not announce the glyph twice.
   */
  decorative?: boolean;
}

const MARK_PATH_D =
  "M 22 16 L 22 78 L 56 78 M 40 16 L 56 78 L 78 16";

const APP_ICON_L_PATH = "M 22 26 L 22 74 L 50 74";
const APP_ICON_V_PATH = "M 38 26 L 50 74 L 78 26";

export function BrandMark({
  variant = "mark",
  size = 28,
  className,
  ariaLabel,
  decorative = false,
}: BrandMarkProps) {
  const ariaProps = decorative
    ? { "aria-hidden": true as const, role: "img" as const }
    : { role: "img" as const, "aria-label": ariaLabel ?? "Lockverity" };

  if (variant === "app-icon") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 100 100"
        width={size}
        height={size}
        className={className}
        data-testid="brand-mark-app-icon"
        {...ariaProps}
      >
        <rect
          x="0"
          y="0"
          width="100"
          height="100"
          rx="18"
          ry="18"
          fill="#0f172a"
        />
        <g
          fill="none"
          stroke="#f8fafc"
          strokeWidth="12"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d={APP_ICON_L_PATH} />
          <path d={APP_ICON_V_PATH} />
        </g>
      </svg>
    );
  }

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      data-testid="brand-mark"
      fill="none"
      stroke="currentColor"
      strokeWidth="12"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...ariaProps}
    >
      <path d={MARK_PATH_D} />
    </svg>
  );
}
