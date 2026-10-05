import { describe, expect, it } from "vitest";

import { blockPosition, formatRange, hourLabels, isoToLocalParts, localToIso, shiftDay } from "./time";

const INDIA = 330; // UTC+5:30

describe("localToIso", () => {
  it("converts a local wall-clock time to UTC using the viewer offset", () => {
    expect(localToIso("2026-10-06", "09:00", INDIA)).toBe("2026-10-06T03:30:00.000Z");
  });

  it("crosses midnight correctly for viewers ahead of UTC", () => {
    expect(localToIso("2026-10-07", "01:00", INDIA)).toBe("2026-10-06T19:30:00.000Z");
  });

  it("is the identity for a UTC viewer", () => {
    expect(localToIso("2026-10-06", "14:15", 0)).toBe("2026-10-06T14:15:00.000Z");
  });
});

describe("isoToLocalParts", () => {
  it("round-trips with localToIso", () => {
    const iso = localToIso("2026-10-06", "17:45", INDIA);
    expect(isoToLocalParts(iso, INDIA)).toEqual({ date: "2026-10-06", time: "17:45" });
  });

  it("reports the next local day when UTC is still the previous one", () => {
    expect(isoToLocalParts("2026-10-06T22:00:00Z", INDIA)).toEqual({ date: "2026-10-07", time: "03:30" });
  });
});

describe("shiftDay", () => {
  it("moves across month and year boundaries", () => {
    expect(shiftDay("2026-10-31", 1)).toBe("2026-11-01");
    expect(shiftDay("2026-01-01", -1)).toBe("2025-12-31");
  });
});

describe("blockPosition", () => {
  const booking = (start, end) => ({ start_time: start, end_time: end });

  it("places a booking proportionally inside the 08:00 to 20:00 window", () => {
    // 10:00 to 12:00 UTC on a 12 hour window starting at 08:00.
    const position = blockPosition(booking("2026-10-06T10:00:00Z", "2026-10-06T12:00:00Z"), "2026-10-06", 8, 20, 0);
    expect(position.leftPct).toBeCloseTo((2 / 12) * 100);
    expect(position.widthPct).toBeCloseTo((2 / 12) * 100);
    expect(position.clippedStart).toBe(false);
    expect(position.clippedEnd).toBe(false);
  });

  it("clips a booking that starts before opening time", () => {
    const position = blockPosition(booking("2026-10-06T07:00:00Z", "2026-10-06T09:00:00Z"), "2026-10-06", 8, 20, 0);
    expect(position.leftPct).toBe(0);
    expect(position.widthPct).toBeCloseTo((1 / 12) * 100);
    expect(position.clippedStart).toBe(true);
  });

  it("returns null for a booking entirely outside the window", () => {
    expect(blockPosition(booking("2026-10-06T05:00:00Z", "2026-10-06T07:00:00Z"), "2026-10-06", 8, 20, 0)).toBeNull();
  });

  it("applies the viewer offset when deciding which hours a booking occupies", () => {
    // 03:30 UTC is 09:00 in India, so it sits one hour into an 08:00 window.
    const position = blockPosition(booking("2026-10-06T03:30:00Z", "2026-10-06T04:30:00Z"), "2026-10-06", 8, 20, INDIA);
    expect(position.leftPct).toBeCloseTo((1 / 12) * 100);
  });
});

describe("labels", () => {
  it("lists one label per opening hour", () => {
    expect(hourLabels(8, 12)).toEqual(["08:00", "09:00", "10:00", "11:00"]);
  });

  it("formats a booking range in local time", () => {
    expect(formatRange("2026-10-06T03:30:00Z", "2026-10-06T05:00:00Z", INDIA)).toBe("09:00 to 10:30");
  });
});
