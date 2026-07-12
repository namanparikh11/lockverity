import { describe, expect, it } from "vitest";

import { labelFor, scanStatusLabel, stageTypeLabel } from "@/utils/labels";

describe("labelFor", () => {
  it("returns the dash fallback for nullish values", () => {
    expect(labelFor(null)).toBe("—");
    expect(labelFor(undefined)).toBe("—");
    expect(labelFor("")).toBe("—");
  });

  it("title-cases snake_case", () => {
    expect(labelFor("rate_limited")).toBe("Rate Limited");
  });

  it("preserves the override for known provider names", () => {
    expect(labelFor("osv")).toBe("OSV");
    expect(labelFor("deps_dev")).toBe("deps.dev");
    expect(labelFor("openssf")).toBe("OpenSSF Scorecard");
  });
});

describe("scanStatusLabel", () => {
  it("maps every documented scan status to a label", () => {
    expect(scanStatusLabel.queued).toBe("Queued");
    expect(scanStatusLabel.running).toBe("Running");
    expect(scanStatusLabel.completed).toBe("Completed");
    expect(scanStatusLabel.partial).toBe("Partial");
    expect(scanStatusLabel.failed).toBe("Failed");
    expect(scanStatusLabel.cancelled).toBe("Cancelled");
  });
});

describe("stageTypeLabel", () => {
  it("maps every documented stage type to a human label", () => {
    expect(stageTypeLabel.repository_intake).toBe("Repository intake");
    expect(stageTypeLabel.vulnerability_query).toBe("Vulnerability query");
    expect(stageTypeLabel.workflow_analysis).toBe("Workflow analysis");
  });
});
