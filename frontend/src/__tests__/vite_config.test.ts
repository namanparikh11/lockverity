/**
 * Vite config integrity tests.
 *
 * The frontend dev server must proxy ``/api`` to the local
 * FastAPI on 127.0.0.1:8000, and it must use the ESM-safe form
 * of __dirname replacement (``fileURLToPath(new URL(...))``).
 * A regression in either of these would break local development
 * and integrated smoke tests.
 *
 * We test the config object directly; we do not start a real
 * Vite dev server, because spinning up two HTTP servers in a
 * Vitest worker is overkill for a structural check.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const configPath = resolve(__dirname, "..", "..", "vite.config.ts");
const source = readFileSync(configPath, "utf-8");

describe("vite.config.ts", () => {
  it("proxies /api to 127.0.0.1:8000", () => {
    expect(source).toMatch(/proxy\s*:\s*\{/);
    expect(source).toMatch(/["']\/api["']\s*:/);
    expect(source).toMatch(/127\.0\.0\.1:8000/);
  });

  it("uses the ESM-safe __dirname replacement (fileURLToPath)", () => {
    expect(source).toMatch(/fileURLToPath/);
    expect(source).toMatch(/import\.meta\.url/);
    // The legacy ``__dirname`` global is not available in pure ESM.
    expect(source).not.toMatch(/\b__dirname\b/);
  });

  it("declares the vitest config block (test runner is co-located)", () => {
    expect(source).toMatch(/test\s*:\s*\{/);
    expect(source).toMatch(/environment\s*:\s*["']jsdom["']/);
  });

  it("pins port 5173 with strictPort so the dev server and proxy match", () => {
    expect(source).toMatch(/port\s*:\s*5173/);
    expect(source).toMatch(/strictPort\s*:\s*true/);
  });
});
