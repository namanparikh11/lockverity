import { describe, expect, it } from "vitest";

import { formatRelative, formatTimestamp } from "@/utils/time";

describe("formatRelative", () => {
  it("returns the dash placeholder for null and undefined", () => {
    expect(formatRelative(null)).toBe("—");
    expect(formatRelative(undefined)).toBe("—");
  });

  it("returns the dash placeholder for an unparseable string", () => {
    expect(formatRelative("not a date")).toBe("—");
  });

  it("renders seconds-ago as just now", () => {
    const now = new Date();
    const five = new Date(now.getTime() - 5_000);
    expect(formatRelative(five.toISOString())).toBe("just now");
  });

  it("renders minutes-ago", () => {
    const now = new Date();
    const tenMin = new Date(now.getTime() - 10 * 60_000);
    expect(formatRelative(tenMin.toISOString())).toBe("10m ago");
  });

  it("renders hours-ago", () => {
    const now = new Date();
    const threeHours = new Date(now.getTime() - 3 * 60 * 60_000);
    expect(formatRelative(threeHours.toISOString())).toBe("3h ago");
  });

  it("renders days-ago", () => {
    const now = new Date();
    const twoDays = new Date(now.getTime() - 2 * 24 * 60 * 60_000);
    expect(formatRelative(twoDays.toISOString())).toBe("2d ago");
  });

  it("renders future dates with 'in'", () => {
    const now = new Date();
    const future = new Date(now.getTime() + 30 * 60_000);
    expect(formatRelative(future.toISOString())).toBe("in 30m");
  });
});

describe("formatTimestamp", () => {
  it("returns the dash placeholder for null and undefined", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp(undefined)).toBe("—");
  });

  it("formats as UTC ISO date with time", () => {
    const result = formatTimestamp("2024-01-15T10:30:00.000Z");
    expect(result).toBe("2024-01-15 10:30:00 UTC");
  });
});
