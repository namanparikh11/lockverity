/**
 * Favicon asset presence and HTML wiring tests.
 *
 * The v2.1 favicon is the Rounded App Icon variant from the
 * brand design board, defined in ``frontend/public/favicon.svg``.
 * The tests below guard the asset inventory and the
 * index.html wiring so a future change cannot silently drop
 * a favicon file or break the 404-free favicon contract.
 *
 * The tests read the filesystem relative to the frontend
 * root (the working directory of the vitest runner). The
 * asset paths are the same paths used in
 * ``frontend/index.html`` so the tests are a direct check
 * of the production wiring.
 */

import { describe, expect, it } from "vitest";
import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const FRONTEND_ROOT = resolve(__dirname, "..", "..");
const PUBLIC_DIR = resolve(FRONTEND_ROOT, "public");
const INDEX_HTML = resolve(FRONTEND_ROOT, "index.html");

interface IconAsset {
  filename: string;
  expectedSize?: number;
  required: boolean;
}

const ICON_ASSETS: IconAsset[] = [
  { filename: "favicon.svg", required: true },
  { filename: "favicon.ico", required: true },
  { filename: "favicon-16x16.png", expectedSize: 16, required: true },
  { filename: "favicon-32x32.png", expectedSize: 32, required: true },
  { filename: "favicon-48x48.png", expectedSize: 48, required: true },
  { filename: "apple-touch-icon.png", expectedSize: 180, required: true },
];

describe("favicon assets", () => {
  it("ships every required favicon file in frontend/public", () => {
    for (const asset of ICON_ASSETS) {
      if (!asset.required) continue;
      const path = resolve(PUBLIC_DIR, asset.filename);
      expect(
        statSync(path).isFile(),
        `${asset.filename} should exist in frontend/public`
      ).toBe(true);
    }
  });

  it("uses the documented brand colours in the SVG favicon", () => {
    const text = readFileSync(resolve(PUBLIC_DIR, "favicon.svg"), "utf-8");
    // No implicit colour inheritance.
    expect(text).not.toMatch(/(?:fill|stroke)\s*=\s*"currentColor"/);
    // The background uses the documented Indigo 900.
    expect(text).toMatch(/fill="#0[Bb]1324"/);
    // The mark uses a vertical linear gradient with the
    // two documented stops (Teal 500 at the top, Blue 600
    // at the bottom). The palette section of the brand
    // board uses these exact hex values; the colour names
    // in the board's legend are unconventional but the
    // hex codes are the source of truth.
    expect(text).toMatch(/<linearGradient\b/);
    expect(text).toMatch(/stop-color="#2[Ee]8[Bb][Ff]0"/);
    expect(text).toMatch(/stop-color="#14[Bb]8[Aa]6"/);
    // The mark is sized in a 16x16 viewBox so the
    // rasterised output is crisply aligned to the pixel
    // grid.
    expect(text).toMatch(/viewBox="0 0 16 16"/);
    // The rounded-square background is present and the
    // mark strokes use round caps (the chain-link ends
    // must not be flat or square at 16x16).
    expect(text).toMatch(/<rect\b[^>]*\brx="3\.5"/);
    expect(text).toMatch(/stroke-linecap="round"/);
  });

  it("embeds 16, 32, and 48 pixel sizes in the ICO", () => {
    const buffer = readFileSync(resolve(PUBLIC_DIR, "favicon.ico"));
    expect(buffer.length).toBeGreaterThan(6);
    const reserved = buffer.readUInt16LE(0);
    const icoType = buffer.readUInt16LE(2);
    const count = buffer.readUInt16LE(4);
    expect(reserved).toBe(0);
    expect(icoType).toBe(1);
    expect(count).toBeGreaterThanOrEqual(3);
    const found = new Set<number>();
    for (let i = 0; i < count; i++) {
      const offset = 6 + i * 16;
      let w = buffer.readUInt8(offset);
      let h = buffer.readUInt8(offset + 1);
      if (w === 0) w = 256;
      if (h === 0) h = 256;
      expect(w).toBe(h);
      found.add(w);
    }
    expect(found.has(16)).toBe(true);
    expect(found.has(32)).toBe(true);
    expect(found.has(48)).toBe(true);
  });

  it("matches the index.html icon references", () => {
    const html = readFileSync(INDEX_HTML, "utf-8");
    const expectedRefs = [
      "/favicon.svg",
      "/favicon.ico",
      "/favicon-16x16.png",
      "/favicon-32x32.png",
      "/favicon-48x48.png",
      "/apple-touch-icon.png",
    ];
    for (const ref of expectedRefs) {
      expect(
        html.includes(ref),
        `index.html should reference ${ref}`
      ).toBe(true);
    }
    expect(html).toMatch(/rel="apple-touch-icon"\s+sizes="180x180"/);
    expect(html).toMatch(/rel="icon"\s+type="image\/png"\s+sizes="16x16"/);
    expect(html).toMatch(/rel="icon"\s+type="image\/png"\s+sizes="32x32"/);
    expect(html).toMatch(/rel="icon"\s+type="image\/png"\s+sizes="48x48"/);
  });

  it("uses a versioned cache-busting query on every icon URL", () => {
    const html = readFileSync(INDEX_HTML, "utf-8");
    const iconHrefs = Array.from(
      html.matchAll(/<link\s+rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"/g)
    ).map((m) => m[1]);
    expect(iconHrefs.length).toBeGreaterThanOrEqual(6);
    for (const href of iconHrefs) {
      expect(
        href,
        `icon href ${href} should carry a ?v= cache-busting query`
      ).toMatch(/\?v=\d+/);
    }
  });

  it("does not declare duplicate or contradictory icon rels", () => {
    const html = readFileSync(INDEX_HTML, "utf-8");
    const appleCount = (
      html.match(/<link\s+rel="apple-touch-icon"/g) ?? []
    ).length;
    expect(appleCount).toBe(1);
    const svgCount = (
      html.match(/<link\s+rel="icon"\s+type="image\/svg\+xml"/g) ?? []
    ).length;
    expect(svgCount).toBe(1);
    const icoCount = (
      html.match(/<link\s+rel="icon"\s+type="image\/x-icon"/g) ?? []
    ).length;
    expect(icoCount).toBe(1);
  });
});
