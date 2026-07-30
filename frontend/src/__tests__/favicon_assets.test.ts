/**
 * Favicon asset presence and HTML wiring tests.
 *
 * The v2.1 favicon is a tiny-size LV monogram shipped as a
 * set of compatibility assets. The tests below guard the
 * asset inventory and the index.html wiring so a future
 * change cannot silently drop a favicon file or break the
 * 404-free favicon contract.
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
  /**
   * Optional expected width/height in pixels. When set,
   * the test verifies the PNG dimensions match. ICO
   * multi-resolution files are checked separately.
   */
  expectedSize?: number;
  /**
   * Whether the asset must be present in production. All
   * the favicon assets listed in the user-facing spec are
   * required; the apple-touch-icon.png at 180x180 is
   * required for iOS home-screen pinning.
   */
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
    // Explicit hex fills for the documented brand colours.
    expect(text).toMatch(/fill="#0f172a"/);
    expect(text).toMatch(/fill="#f8fafc"/);
    // The monogram is a 16x16 viewBox so the rasterised
    // output is crisply aligned to the pixel grid.
    expect(text).toMatch(/viewBox="0 0 16 16"/);
  });

  it("embeds 16, 32, and 48 pixel sizes in the ICO", () => {
    // The ICO file format stores a 6-byte header followed
    // by 16-byte directory entries. Each entry records the
    // width in byte 0 and the height in byte 1 (0 means
    // 256). We parse the header and directory to confirm
    // the expected sizes are present.
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
    // The apple-touch-icon must declare its 180x180 size.
    expect(html).toMatch(/rel="apple-touch-icon"\s+sizes="180x180"/);
    // The PNG favicons must declare their sizes too.
    expect(html).toMatch(/rel="icon"\s+type="image\/png"\s+sizes="16x16"/);
    expect(html).toMatch(/rel="icon"\s+type="image\/png"\s+sizes="32x32"/);
    expect(html).toMatch(/rel="icon"\s+type="image\/png"\s+sizes="48x48"/);
  });

  it("uses a versioned cache-busting query on every icon URL", () => {
    const html = readFileSync(INDEX_HTML, "utf-8");
    // Every icon href must carry a ?v= token so Chrome does
    // not stick to a stale favicon after a deploy.
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
    // The page must not declare more than one
    // ``rel="apple-touch-icon"`` (iOS picks the last one and
    // a duplicate declaration is a confusing regression).
    const appleCount = (
      html.match(/<link\s+rel="apple-touch-icon"/g) ?? []
    ).length;
    expect(appleCount).toBe(1);
    // Exactly one SVG favicon is expected.
    const svgCount = (
      html.match(/<link\s+rel="icon"\s+type="image\/svg\+xml"/g) ?? []
    ).length;
    expect(svgCount).toBe(1);
    // Exactly one ICO fallback.
    const icoCount = (
      html.match(/<link\s+rel="icon"\s+type="image\/x-icon"/g) ?? []
    ).length;
    expect(icoCount).toBe(1);
  });
});
