/**
 * v1.4 in-app demo home tests.
 *
 * The /demo page is a read-only reviewer walkthrough. It
 * must surface the documented sections, link to the five
 * reviewer pages, repeat the bounded "what not to claim"
 * wording, and be reachable through the AppShell primary
 * nav as a `Demo` entry.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { AppShell } from "@/layouts/AppShell";
import { DemoHomePage } from "@/pages/DemoHomePage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("v1.4 in-app demo home", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders the demo page at /demo with all five sections", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        name: "Lockverity",
        version: "1.4.0",
        tagline: "Evidence-first software supply-chain assurance",
        environment: "test",
        api_prefix: "/api/v1",
        archive_limits: {},
        pagination: {},
        provider_safety: {},
        intake: {},
      })
    );
    render(
      <MemoryRouter initialEntries={["/demo"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/demo" element={<DemoHomePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    // Page header.
    expect(screen.getByRole("heading", { name: /local demo/i })).toBeInTheDocument();

    // Five sections, anchored by their h2 IDs.
    const sectionIds = [
      "demo-dataset-status",
      "demo-flow",
      "demo-look-for",
      "demo-not-claim",
      "demo-commands",
    ];
    for (const id of sectionIds) {
      expect(
        document.getElementById(id),
        `expected section #${id} to be present`
      ).not.toBeNull();
    }

    // The bounded "not a verdict / not a certification / not a
    // compliance pass-or-fail" wording is present (the page
    // renders it across two JSX lines so we match each
    // substring separately).
    expect(
      screen.getByText(/not a security verdict/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a certification/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a compliance pass-or-fail/i)
    ).toBeInTheDocument();
  });

  it("links to the five reviewer pages from the reviewer flow section", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        name: "Lockverity",
        version: "1.4.0",
        tagline: "Evidence-first software supply-chain assurance",
        environment: "test",
        api_prefix: "/api/v1",
        archive_limits: {},
        pagination: {},
        provider_safety: {},
        intake: {},
      })
    );
    render(
      <MemoryRouter initialEntries={["/demo"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/demo" element={<DemoHomePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    for (const href of [
      "/",
      "/scans/1/dependencies",
      "/scans/1/exports",
      "/scans/3/exports",
      "/scans/4/exports",
      "/about",
    ]) {
      const link = screen.getByRole("link", { name: new RegExp(`${href}$`) });
      expect(link).toBeInTheDocument();
    }
  });

  it("exposes a Demo entry in the AppShell primary nav", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        name: "Lockverity",
        version: "1.4.0",
        tagline: "Evidence-first software supply-chain assurance",
        environment: "test",
        api_prefix: "/api/v1",
        archive_limits: {},
        pagination: {},
        provider_safety: {},
        intake: {},
      })
    );
    render(
      <MemoryRouter initialEntries={["/demo"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/demo" element={<DemoHomePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    // The Demo nav link must be present and point at /demo.
    const navLink = screen.getByRole("link", { name: /^Demo$/ });
    expect(navLink).toBeInTheDocument();
    expect(navLink.getAttribute("href")).toBe("/demo");
  });

  it("repeatedly surfaces the synthetic-dataset disclosure", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        name: "Lockverity",
        version: "1.4.0",
        tagline: "Evidence-first software supply-chain assurance",
        environment: "test",
        api_prefix: "/api/v1",
        archive_limits: {},
        pagination: {},
        provider_safety: {},
        intake: {},
      })
    );
    render(
      <MemoryRouter initialEntries={["/demo"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/demo" element={<DemoHomePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    // The page must repeat the synthetic-data disclosure so a
    // reviewer can never mistake the demo for a real provider
    // scan result.
    expect(
      screen.getByText(/synthetic persisted evidence/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no provider calls are made by the demo loader/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no analyzed repository code is executed/i)
    ).toBeInTheDocument();
  });

  it("renders the AppShell footer with the v1.4 version (sanity check)", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        name: "Lockverity",
        version: "1.4.0",
        tagline: "Evidence-first software supply-chain assurance",
        environment: "test",
        api_prefix: "/api/v1",
        archive_limits: {},
        pagination: {},
        provider_safety: {},
        intake: {},
      })
    );
    render(
      <MemoryRouter initialEntries={["/demo"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/demo" element={<DemoHomePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("v1.4.0")).toBeInTheDocument();
    });
  });
});
