import { describe, it, expect } from "vitest";
import { formatDate, formatDuration } from "../src/format.js";

describe("formatDate", () => {
  it("renders an ISO date as a readable locale string", () => {
    expect(formatDate("2026-07-25")).toMatch(/2026/);
  });

  it("returns a fallback for empty input", () => {
    expect(formatDate(null)).toBe("unknown date");
  });

  it("returns the raw value when it cannot be parsed", () => {
    expect(formatDate("garbage")).toBe("garbage");
  });
});

describe("formatDuration", () => {
  it("formats seconds as M:SS", () => {
    expect(formatDuration(225)).toBe("3:45");
    expect(formatDuration(65)).toBe("1:05");
  });

  it("returns an empty string for falsy input", () => {
    expect(formatDuration(0)).toBe("");
    expect(formatDuration(null)).toBe("");
  });
});