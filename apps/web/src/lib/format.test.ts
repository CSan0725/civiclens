/**
 * The formatting decisions that carry meaning.
 *
 * Not a test of `Intl` — a test of the three places where a formatting choice
 * would otherwise state something false: an at-large seat written as "CA-0",
 * a missing FEC figure rendered as "$0", and a candidate's party shown as a
 * bare code beside a member's spelled-out one.
 */

import { describe, expect, it } from "vitest";

import { fecParty, formatDistrictLabel, formatMoney } from "./format";

describe("formatDistrictLabel", () => {
  it("zero-pads a numbered district", () => {
    expect(formatDistrictLabel("CA", 11)).toBe("CA-11");
    expect(formatDistrictLabel("NC", 2)).toBe("NC-02");
  });

  it("writes an at-large seat as AL, not as district zero", () => {
    // Wyoming's district number IS 0 — it is a real district, and "WY-0" is
    // not how anyone writes it.
    expect(formatDistrictLabel("WY", 0, true)).toBe("WY-AL");
    expect(formatDistrictLabel("WY", 0)).toBe("WY-AL");
  });
});

describe("formatMoney", () => {
  it("rounds to whole dollars", () => {
    expect(formatMoney("2124082.47")).toBe("$2,124,082");
  });

  it("keeps a reported zero distinct from a missing figure", () => {
    // "This committee reported nothing" and "the FEC has no report" are
    // different facts. Collapsing them would invent a filing.
    expect(formatMoney("0")).toBe("$0");
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
    expect(formatMoney("")).toBe("—");
  });

  it("takes the string the numeric column arrives as", () => {
    // `numeric(16,2)` comes over as a string so it is not rounded through a
    // float on the way in; this is the only place it becomes a number.
    expect(formatMoney("14904163.00")).toBe("$14,904,163");
  });
});

describe("fecParty", () => {
  it("expands a code that has one unambiguous expansion", () => {
    expect(fecParty("DEM")).toEqual({ code: "D", name: "Democratic" });
    expect(fecParty("REP")).toEqual({ code: "R", name: "Republican" });
    expect(fecParty("LIB")).toEqual({ code: "L", name: "Libertarian" });
  });

  it("renders anything else verbatim rather than guessing", () => {
    // Measured in the loaded states, the FEC's party field also contains these.
    for (const code of ["GOP", "UNK", "NNE", "OTH", "18"]) {
      expect(fecParty(code)).toEqual({ code, name: null });
    }
  });

  it("passes through an absent party", () => {
    expect(fecParty(null)).toEqual({ code: null, name: null });
  });
});
