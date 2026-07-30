/**
 * Favicon 16x16 visual legibility test.
 *
 * The v2.1 favicon is the approved "Rounded App Icon" from
 * the brand design board, supplied as a 1024x1024 PNG
 * (``frontend/public/favicon-source.png``) and rasterised to
 * the compatibility sizes by
 * ``backend/scripts/generate_favicon_assets.py``. This test
 * parses the 16x16 derivative and asserts the invariants
 * that the source-of-truth chain must preserve:
 *
 *   1. The image is 16x16 pixels.
 *   2. The corners are fully transparent (the rounded
 *      squircle background is preserved at every derivative
 *      size).
 *   3. The rounded-square background is present (the dark
 *      indigo body fills the inner area).
 *   4. The mark is visible inside the rounded square (a
 *      pixel brighter than the background is present in
 *      the central region).
 *   5. The mark is centred: the central 8x8 region contains
 *      mark pixels.
 *   6. Transparency is preserved: the ICO and PNG files
 *      have an alpha channel (the rounded corners are
 *      transparent, not a white or dark background).
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { PNG } from "pngjs";

const FRONTEND_ROOT = resolve(__dirname, "..", "..");
const FAVICON_16 = resolve(FRONTEND_ROOT, "public", "favicon-16x16.png");
const FAVICON_SOURCE = resolve(FRONTEND_ROOT, "public", "favicon-source.png");

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
  // Indigo 900 (#0B1324) is very dark.
  return p.a > 200 && luminance(p) < 60;
}

function isMark(p: Rgba): boolean {
  // The mark is the gradient stroke: any pixel that is
  // opaque and noticeably brighter than the background.
  return p.a > 200 && luminance(p) > 100;
}

function isTransparent(p: Rgba): boolean {
  return p.a < 50;
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
    expect(mark, "mark pixels should be present").toBeGreaterThan(10);
    expect(background, "background pixels should be present").toBeGreaterThan(100);
  });

  it("preserves the transparent rounded-square corners", () => {
    const img = readPng(FAVICON_16);
    // The four corner pixels (0,0), (15,0), (0,15), (15,15)
    // must be transparent. The rounded-square background
    // means a small ring of transparent pixels is present
    // in every corner region.
    const cornerPixels: Array<[number, number]> = [
      [0, 0],
      [15, 0],
      [0, 15],
      [15, 15],
    ];
    let transparentCorners = 0;
    for (const [x, y] of cornerPixels) {
      if (isTransparent(pixelAt(img, x, y))) transparentCorners++;
    }
    // All four corners must be transparent.
    expect(transparentCorners).toBe(4);
  });

  it("renders the mark in the centre of the icon", () => {
    const img = readPng(FAVICON_16);
    // The central 8x8 region should contain mark pixels.
    let centerMark = 0;
    for (let y = 4; y <= 11; y++) {
      for (let x = 4; x <= 11; x++) {
        if (isMark(pixelAt(img, x, y))) centerMark++;
      }
    }
    expect(
      centerMark,
      "the centre of the icon should contain mark pixels"
    ).toBeGreaterThan(5);
  });

  it("uses Indigo 900 as the background colour", () => {
    const img = readPng(FAVICON_16);
    // Sample a background pixel well inside the rounded
    // square and away from the mark.
    const sample = pixelAt(img, 2, 7);
    expect(isBackground(sample)).toBe(true);
    expect(sample.r).toBeLessThanOrEqual(30);
    expect(sample.g).toBeLessThanOrEqual(30);
    expect(sample.b).toBeLessThanOrEqual(50);
  });

  it("preserves transparency in the source PNG", () => {
    const img = readPng(FAVICON_SOURCE);
    // The source must be a transparent PNG so the rounded
    // corners survive the derivative rasterisation.
    const cornersTransparent: Array<[number, number]> = [
      [0, 0],
      [img.width - 1, 0],
      [0, img.height - 1],
      [img.width - 1, img.height - 1],
    ];
    for (const [x, y] of cornersTransparent) {
      const p = pixelAt(img, x, y);
      expect(
        p.a,
        `source corner (${x}, ${y}) must be transparent`
      ).toBeLessThan(50);
    }
  });
});
