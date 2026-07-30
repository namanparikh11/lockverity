/**
 * BrandMark component tests.
 *
 * The mark is the v2.1 original Lockverity brand mark:
 * hand-authored SVG geometry that renders as the L+V glyph
 * (mark variant) or as a rounded-square application icon
 * (app-icon variant).
 *
 * These tests guard the variant shape, the accessibility
 * defaults, and the size prop. They do not assert against
 * the rasterised output - the SVG geometry is checked by
 * the data-testid and aria-label inspection below, and the
 * ``docs/brand-assets.md`` document is the canonical
 * reference for the original vector coordinates.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { BrandMark } from "@/components/BrandMark";

describe("BrandMark", () => {
  it("renders the mark variant by default with the expected testid", () => {
    render(<BrandMark />);
    expect(screen.getByTestId("brand-mark")).toBeInTheDocument();
    expect(screen.queryByTestId("brand-mark-app-icon")).not.toBeInTheDocument();
  });

  it("renders the app-icon variant when requested", () => {
    render(<BrandMark variant="app-icon" />);
    expect(screen.getByTestId("brand-mark-app-icon")).toBeInTheDocument();
    expect(screen.queryByTestId("brand-mark")).not.toBeInTheDocument();
  });

  it("hides the mark from the accessibility tree when decorative", () => {
    render(<BrandMark decorative />);
    const svg = screen.getByTestId("brand-mark");
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });

  it("labels the mark when not decorative", () => {
    render(<BrandMark ariaLabel="Lockverity product mark" />);
    const svg = screen.getByTestId("brand-mark");
    expect(svg).toHaveAttribute("aria-label", "Lockverity product mark");
    expect(svg).not.toHaveAttribute("aria-hidden");
  });

  it("renders the configured size as width and height", () => {
    render(<BrandMark size={64} />);
    const svg = screen.getByTestId("brand-mark");
    expect(svg).toHaveAttribute("width", "64");
    expect(svg).toHaveAttribute("height", "64");
  });
});
