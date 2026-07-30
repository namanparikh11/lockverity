/**
 * Lockverity standalone product symbol.
 *
 * Renders the approved standalone brand symbol from
 * ``frontend/public/brand/lockverity-symbol.png``. The
 * symbol is the exact raster supplied by the brand board;
 * the component never re-derives, traces, or reinterprets
 * the geometry. The source PNG is the single source of truth.
 *
 * Two visual modes are exposed:
 *
 * - default: the symbol on a transparent background, sized
 *   to fit the parent. Use this inline next to the product
 *   name in the header, sidebar footer, and About hero.
 *
 * Both modes honour the source PNG's aspect ratio and
 * transparency. The component is inert to animation: no
 * transitions or transforms are applied at render time.
 */
export interface LockveritySymbolProps {
  size?: number;
  className?: string;
  /**
   * Accessible label for screen readers. The symbol is
   * decorative by default; supply a label when the symbol
   * is the only element that conveys the product identity
   * (for example, in a marketing surface).
   */
  ariaLabel?: string;
  /**
   * When ``true`` the symbol is announced as a decorative
   * image and is hidden from the accessibility tree. Use
   * this when the product name is rendered adjacent to
   * the symbol.
   */
  decorative?: boolean;
}

const SYMBOL_SRC = "/brand/lockverity-symbol.png";

export function LockveritySymbol({
  size = 28,
  className,
  ariaLabel,
  decorative = false,
}: LockveritySymbolProps) {
  const ariaProps = decorative
    ? { "aria-hidden": true as const }
    : { "aria-label": ariaLabel ?? "Lockverity" };
  return (
    <img
      src={SYMBOL_SRC}
      width={size}
      height={size}
      alt=""
      className={className}
      data-testid="lockverity-symbol"
      {...ariaProps}
    />
  );
}
