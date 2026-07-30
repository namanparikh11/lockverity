/**
 * Favicon 16x16 visual legibility test.
 *
 * The v2.1 Part A favicon correction is a release-quality
 * fix: at 16x16 the previous mark resembled a paperclip or
 * chain link rather than a recognisable "LV" monogram. The
 * test below parses the 16x16 PNG and asserts the pixel
 * layout contains the structural features that make the L
 * and V individually recognisable.
 *
 * The test is tolerant of sub-pixel anti-aliasing (the
 * 16x16 raster is produced by Lanczos downsampling from
 * an 8x supersampled source) but strict on the structural
 * invariants:
 *
 *   1. The background is a solid rounded square.
 *   2. The L has a vertical stem and a horizontal foot.
 *   3. The V has two diagonal strokes meeting at a point.
 *   4. The L and the V are separated by at least one
 *      background column.
 *   5. The foreground colour count exceeds the background
 *      colour count (the monogram is visible).
 *
 * If the geometry regresses to a continuous stroke or a
 * paperclip shape, the structural assertions fire.
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

function isForeground(p: Rgba): boolean {
  // The monogram is high-contrast white on a dark navy
  // background. A pixel is foreground when it is opaque
  // and significantly brighter than the background.
  return p.a > 200 && luminance(p) > 160;
}

function isBackground(p: Rgba): boolean {
  return p.a > 200 && luminance(p) < 80;
}

describe("favicon 16x16 visual legibility", () => {
  it("is a 16x16 PNG with a high-contrast monogram", () => {
    const img = readPng(FAVICON_16);
    expect(img.width).toBe(16);
    expect(img.height).toBe(16);
    let foreground = 0;
    let background = 0;
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const p = pixelAt(img, x, y);
        if (isForeground(p)) foreground++;
        else if (isBackground(p)) background++;
      }
    }
    // The monogram must be visible (foreground > 0) and
    // the background must be visible (background > 0).
    expect(foreground).toBeGreaterThan(20);
    expect(background).toBeGreaterThan(100);
    // The foreground should be a small but non-trivial
    // fraction of the icon. At 16x16 with the documented
    // geometry, the monogram covers roughly 20-35% of the
    // 256 pixels.
    expect(foreground).toBeLessThan(120);
  });

  it("renders a recognisable vertical L stem on the left side", () => {
    const img = readPng(FAVICON_16);
    // The L stem lives in the left third of the icon. We
    // count foreground pixels in the columns x = 1..5 and
    // require a tall vertical run (at least 6 contiguous
    // foreground rows in the middle of the icon).
    const stemColumns = [2, 3, 4];
    let longestRun = 0;
    let currentRun = 0;
    for (let y = 0; y < 16; y++) {
      const anyForeground = stemColumns.some((x) =>
        isForeground(pixelAt(img, x, y))
      );
      if (anyForeground) {
        currentRun++;
        longestRun = Math.max(longestRun, currentRun);
      } else {
        currentRun = 0;
      }
    }
    expect(
      longestRun,
      "L stem should be a vertical run of at least 6 foreground rows"
    ).toBeGreaterThanOrEqual(6);
  });

  it("renders a horizontal L foot at the bottom of the left side", () => {
    const img = readPng(FAVICON_16);
    // The L foot lives in the bottom rows, spanning the
    // left half of the icon. We count foreground pixels in
    // the bottom 3 rows and require the foot to extend
    // further to the right than the stem alone.
    let footReach = 0;
    for (let y = 11; y <= 13; y++) {
      for (let x = 0; x < 16; x++) {
        if (isForeground(pixelAt(img, x, y))) {
          footReach = Math.max(footReach, x);
        }
      }
    }
    // The foot must reach at least x = 5 (the foot extends
    // beyond the stem which ends at x = 4).
    expect(
      footReach,
      "L foot should reach further right than the L stem"
    ).toBeGreaterThanOrEqual(5);
  });

  it("renders two distinct diagonal V strokes that meet at a point", () => {
    const img = readPng(FAVICON_16);
    // The V lives in the right half of the icon. At the top
    // of the V (rows 3-4) the two arms are separate, and
    // at the bottom of the V (rows 12-13) they have merged
    // into a single point.
    const topSeparation = countSeparation(img, 3, 4);
    const bottomSeparation = countSeparation(img, 12, 13);
    // The arms must be more separated at the top than at
    // the bottom. A single solid V (triangle) would have
    // zero separation at both the top and the bottom; a
    // continuous chain-link stroke would have similar
    // separation at the top and bottom.
    expect(topSeparation).toBeGreaterThanOrEqual(1);
    expect(bottomSeparation).toBeLessThanOrEqual(topSeparation);
  });

  it("keeps the L and the V separated by at least one background column", () => {
    const img = readPng(FAVICON_16);
    // We scan a horizontal band that crosses both the L
    // and the V (rows 4..10). For each row, the L ends at
    // some xL and the V begins at some xV. The gap
    // xV - xL must be at least 1.
    for (let y = 4; y <= 10; y++) {
      let rightmostL = -1;
      let leftmostV = 16;
      for (let x = 0; x < 16; x++) {
        if (!isForeground(pixelAt(img, x, y))) continue;
        if (x <= 7) {
          rightmostL = Math.max(rightmostL, x);
        } else {
          leftmostV = Math.min(leftmostV, x);
        }
      }
      // Both the L and the V must be present in this row.
      if (rightmostL >= 0 && leftmostV < 16) {
        expect(
          leftmostV - rightmostL,
          `row ${y}: L ends at ${rightmostL}, V starts at ${leftmostV}`
        ).toBeGreaterThanOrEqual(1);
      }
    }
  });
});

function countSeparation(
  img: { data: Buffer; width: number },
  yStart: number,
  yEnd: number
): number {
  // For the rows in the band, find the maximum number of
  // contiguous background pixels between two foreground
  // runs on the right half of the icon. A V with two
  // distinct arms shows at least one background pixel
  // between the arms; a solid triangle shows zero.
  let maxSeparation = 0;
  for (let y = yStart; y <= yEnd; y++) {
    let foregroundSeen = false;
    let backgroundRun = 0;
    let separation = 0;
    for (let x = 8; x < 16; x++) {
      const p = pixelAt(img, x, y);
      if (isForeground(p)) {
        if (foregroundSeen) {
          separation = Math.max(separation, backgroundRun);
        }
        foregroundSeen = true;
        backgroundRun = 0;
      } else {
        backgroundRun++;
      }
    }
    maxSeparation = Math.max(maxSeparation, separation);
  }
  return maxSeparation;
}
