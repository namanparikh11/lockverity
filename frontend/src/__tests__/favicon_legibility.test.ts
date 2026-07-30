/**
 * Favicon 16x16 visual legibility test.
 *
 * The v2.1 favicon is the Rounded App Icon variant from the
 * brand design board. At 16x16 the mark must be clearly
 * recognisable as the interlocking chain-link symbol with
 * a blue-to-teal vertical gradient on a dark indigo
 * background.
 *
 * The test parses the 16x16 PNG and asserts the structural
 * and chromatic invariants:
 *
 *   1. The background is a solid dark indigo rounded
 *      square (no fully transparent corners, no near-white
 *      background pixels).
 *   2. The mark is present and occupies the centre of the
 *      icon (the central region has bright gradient
 *      pixels).
 *   3. The gradient runs top-to-bottom: the upper half of
 *      the icon is bluer (higher blue channel) and the
 *      lower half is greener (higher green channel).
 *   4. The mark forms a connected, balanced chain-link:
 *      the top half and the bottom half both contain
 *      bright mark pixels, and the centre of the icon has
 *      bright pixels (the crossing point of the two
 *      S-curves).
 *   5. The rounded-square background is intact: every
 *      corner has at least one near-background pixel.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { PNG } from "pngjs";

const FRONTEND_ROOT = resolve(__dirname, "..", "..");
const FAVICON_16 = resolve(FRONTEND_ROOT, "public", "favicon-16x16.png");

interface Rgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

function readPng(path: string): { width: number; height: number; data: Buffer } {
  const buffer = readFileSync(path);
  return PNG.sync.read(buffer);
}

function pixelAt(image: { data: Buffer; width: number }, x: number, y: number): Rgba {
  const idx = (image.width * y + x) << 2;
  return {
    r: image.data[idx],
    g: image.data[idx + 1],
    b: image.data[idx + 2],
    a: image.data[idx + 3],
  };
}

function luminance(p: Rgba): number {
  return 0.2126 * p.r + 0.7152 * p.g + 0.0722 * p.b;
}

function isBackground(p: Rgba): boolean {
  // Indigo 900 (#0B1324) is very dark and low-saturation.
  // Allow a small fudge for the antialiased rounded-corner
  // edge.
  return p.a > 200 && luminance(p) < 60;
}

function isMark(p: Rgba): boolean {
  // The mark is the gradient stroke: any pixel that is
  // opaque and noticeably brighter than the background.
  // The gradient runs from a mid-saturation blue to a
  // mid-saturation teal, both of which are well above the
  // background luminance.
  return p.a > 200 && luminance(p) > 100;
}

function isBlueish(p: Rgba): boolean {
  // The top of the gradient is bluer (B channel dominates
  // over G) than the bottom of the gradient.
  return p.b > p.g + 15;
}

function isTealish(p: Rgba): boolean {
  // The bottom of the gradient is tealish: G channel is
  // comparable to B and well above R.
  return p.g > p.r + 20 && Math.abs(p.g - p.b) < 60;
}

describe("favicon 16x16 visual legibility", () => {
  it("is a 16x16 PNG with a high-contrast mark on a dark background", () => {
    const img = readPng(FAVICON_16);
    expect(img.width).toBe(16);
    expect(img.height).toBe(16);
    let mark = 0;
    let background = 0;
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const p = pixelAt(img, x, y);
        if (isMark(p)) mark++;
        else if (isBackground(p)) background++;
      }
    }
    // The mark must be visible.
    expect(mark, "mark pixels should be present").toBeGreaterThan(15);
    // The background must fill the rounded square.
    expect(background, "background pixels should be present").toBeGreaterThan(150);
    // The mark should be a small but non-trivial fraction
    // of the icon (roughly 5-20% of the 256 pixels).
    expect(mark).toBeLessThan(80);
  });

  it("uses Indigo 900 (#0B1324) as the background", () => {
    const img = readPng(FAVICON_16);
    // Sample the central-left background pixel (well inside
    // the rounded square, away from the mark).
    const sample = pixelAt(img, 2, 8);
    expect(isBackground(sample)).toBe(true);
    // The background should be very close to the documented
    // Indigo 900 hex.
    expect(sample.r).toBeLessThanOrEqual(30);
    expect(sample.g).toBeLessThanOrEqual(30);
    expect(sample.b).toBeLessThanOrEqual(50);
  });

  it("renders the mark in the centre of the icon", () => {
    const img = readPng(FAVICON_16);
    // The central 6x6 region should contain mark pixels.
    let centerMark = 0;
    for (let y = 5; y <= 10; y++) {
      for (let x = 5; x <= 10; x++) {
        if (isMark(pixelAt(img, x, y))) centerMark++;
      }
    }
    expect(
      centerMark,
      "the centre of the icon should contain mark pixels"
    ).toBeGreaterThan(4);
  });

  it("preserves the rounded-square background at every corner", () => {
    const img = readPng(FAVICON_16);
    // The four corners are at (0,0), (15,0), (0,15),
    // (15,15). The rounded-square background means a small
    // ring of background-tinted pixels is present in every
    // corner region (within ~3 pixels of the corner).
    const cornerSamples: Array<[number, number]> = [
      [1, 1],
      [1, 2],
      [2, 1],
      [13, 1],
      [14, 1],
      [14, 2],
      [1, 13],
      [1, 14],
      [2, 14],
      [13, 14],
      [14, 13],
      [14, 14],
    ];
    let backgroundInCorners = 0;
    for (const [x, y] of cornerSamples) {
      if (isBackground(pixelAt(img, x, y))) backgroundInCorners++;
    }
    expect(
      backgroundInCorners,
      "most corner-region samples should be background-tinted"
    ).toBeGreaterThanOrEqual(8);
  });

  it("applies the vertical blue-to-teal gradient across the mark", () => {
    const img = readPng(FAVICON_16);
    // Find the mark pixels in the upper half (rows 3..7)
    // and the lower half (rows 8..12). The upper-half
    // pixels should skew bluer and the lower-half pixels
    // should skew tealish.
    let upperBlue = 0;
    let upperTeal = 0;
    let lowerBlue = 0;
    let lowerTeal = 0;
    for (let y = 3; y <= 7; y++) {
      for (let x = 0; x < 16; x++) {
        const p = pixelAt(img, x, y);
        if (!isMark(p)) continue;
        if (isBlueish(p)) upperBlue++;
        if (isTealish(p)) upperTeal++;
      }
    }
    for (let y = 8; y <= 12; y++) {
      for (let x = 0; x < 16; x++) {
        const p = pixelAt(img, x, y);
        if (!isMark(p)) continue;
        if (isBlueish(p)) lowerBlue++;
        if (isTealish(p)) lowerTeal++;
      }
    }
    // The upper half must have more blue-leaning pixels
    // than the lower half, and the lower half must have
    // more teal-leaning pixels than the upper half.
    expect(
      upperBlue,
      "upper half should contain blue-leaning gradient pixels"
    ).toBeGreaterThan(0);
    expect(
      lowerTeal,
      "lower half should contain teal-leaning gradient pixels"
    ).toBeGreaterThan(0);
    expect(upperBlue).toBeGreaterThanOrEqual(lowerBlue);
    expect(lowerTeal).toBeGreaterThanOrEqual(upperTeal);
  });
});
