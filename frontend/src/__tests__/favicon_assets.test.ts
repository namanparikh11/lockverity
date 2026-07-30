/**
 * Favicon asset presence and HTML wiring tests.
 *
 * The v2.1 favicon is the approved "Rounded App Icon" from
 * the brand design board, supplied as a 1024x1024 PNG
 * (``frontend/public/favicon-source.png``). Every
 * compatibility asset is derived from the source by
 * ``backend/scripts/generate_favicon_assets.py``. The tests
 * below guard the asset inventory and the index.html wiring
 * so a future change cannot silently drop a favicon file,
 * regress the source-of-truth chain, or break the 404-free
 * favicon contract.
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

const SOURCE_PNG = "favicon-source.png";
const ICON_ASSETS: IconAsset[] = [
  { filename: SOURCE_PNG, required: true },
  { filename: "favicon.ico", required: true },
  { filename: "favicon-16x16.png", expectedSize: 16, required: true },
  { filename: "favicon-32x32.png", expectedSize: 32, required: true },
  { filename: "favicon-48x48.png", expectedSize: 48, required: true },
  { filename: "favicon-180x180.png", expectedSize: 180, required: true },
  { filename: "favicon-256x256.png", expectedSize: 256, required: true },
  { filename: "favicon-512x512.png", expectedSize: 512, required: true },
  { filename: "apple-touch-icon.png", expectedSize: 180, required: true },
  { filename: "brand/lockverity-symbol.png", required: true },
  { filename: "brand/lockverity-horizontal-logo.png", required: true },
];

describe("favicon assets", () => {
  it("ships every required favicon and brand asset", () => {
    for (const asset of ICON_ASSETS) {
      if (!asset.required) continue;
      const path = resolve(PUBLIC_DIR, asset.filename);
      expect(
        statSync(path).isFile(),
        `${asset.filename} should exist in frontend/public`
      ).toBe(true);
    }
  });

  it("uses the approved source PNG as the single source of truth", () => {
    const sourcePath = resolve(PUBLIC_DIR, SOURCE_PNG);
    expect(
      statSync(sourcePath).isFile(),
      "favicon-source.png must be the approved source"
    ).toBe(true);
    // The source must be a PNG with transparency so the
    // derivatives can preserve the rounded squircle's
    // background. Pillow identifies the mode from the
    // file header.
    const buffer = readFileSync(sourcePath);
    expect(buffer.length).toBeGreaterThan(8);
    // PNG signature: 89 50 4E 47 0D 0A 1A 0A
    expect(buffer[0]).toBe(0x89);
    expect(buffer[1]).toBe(0x50);
    expect(buffer[2]).toBe(0x4e);
    expect(buffer[3]).toBe(0x47);
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
      "/favicon.ico",
      "/favicon-16x16.png",
      "/favicon-32x32.png",
      "/favicon-48x48.png",
      "/favicon-180x180.png",
      "/favicon-256x256.png",
      "/favicon-512x512.png",
      "/apple-touch-icon.png",
    ];
    for (const ref of expectedRefs) {
      expect(
        html.includes(ref),
        `index.html should reference ${ref}`
      ).toBe(true);
    }
    expect(html).toMatch(/rel="apple-touch-icon"\s+sizes="180x180"/);
    for (const size of [
      "16x16",
      "32x32",
      "48x48",
      "180x180",
      "256x256",
      "512x512",
    ]) {
      expect(
        html.includes(`sizes="${size}"`),
        `index.html should declare sizes="${size}"`
      ).toBe(true);
    }
  });

  it("does not reference a favicon.svg (the v2.1 design is PNG-only)", () => {
    const html = readFileSync(INDEX_HTML, "utf-8");
    // The v2.1 favicon is the approved Rounded App Icon
    // raster. The source is a PNG; no SVG is in the chain.
    expect(html).not.toMatch(/href="\/favicon\.svg/);
    expect(html).not.toMatch(/type="image\/svg\+xml"/);
  });

  it("uses a versioned cache-busting query on every icon URL", () => {
    const html = readFileSync(INDEX_HTML, "utf-8");
    const iconHrefs = Array.from(
      html.matchAll(/<link\s+rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"/g)
    ).map((m) => m[1]);
    expect(iconHrefs.length).toBeGreaterThanOrEqual(8);
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
    const icoCount = (
      html.match(/<link\s+rel="icon"\s+type="image\/x-icon"/g) ?? []
    ).length;
    expect(icoCount).toBe(1);
  });
});
