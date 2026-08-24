/**
 * Census Geocoder parsing, driven by real captured responses.
 *
 * Every fixture under `__fixtures__/` is a live response captured on
 * 2026-08-25 and then trimmed: the congressional-district layer is kept in
 * all of them, `sf-ca-11.json` also keeps States and Counties so that picking
 * the right layer out of several is actually exercised, and the rest of the
 * layers are dropped to keep the files readable.
 *
 * No network. `fetch` is replaced per test.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import ambiguousNc from "./__fixtures__/ambiguous-nc.json";
import austinTx37 from "./__fixtures__/austin-tx-37.json";
import cheyenneWyAtLarge from "./__fixtures__/cheyenne-wy-at-large.json";
import dcDelegate from "./__fixtures__/dc-delegate.json";
import noMatch from "./__fixtures__/no-match.json";
import sfCa11 from "./__fixtures__/sf-ca-11.json";
import { geocodeAddress } from "./census-geocoder";

function respondWith(payload: unknown, init?: { status?: number }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(payload), {
        status: init?.status ?? 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a district that parses cleanly", () => {
  it("reads the district out of a response carrying several layers", async () => {
    respondWith(sfCa11);
    const result = await geocodeAddress("1 Dr Carlton B Goodlett Pl");

    expect(result.status).toBe("ok");
    if (result.status !== "ok") return;
    expect(result.district.geoid).toBe("0611");
    expect(result.district.stateFips).toBe("06");
    expect(result.district.cdNumber).toBe(11);
    expect(result.district.congressNo).toBe(119);
    expect(result.district.matchedAddress).toContain("SAN FRANCISCO");
    expect(result.district.longitude).toBeCloseTo(-122.418, 2);
    expect(result.district.latitude).toBeCloseTo(37.778, 2);
  });

  it("sends the address to the single-address endpoint, not the batch one", async () => {
    let url = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        url = String(input);
        return new Response(JSON.stringify(sfCa11), {
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    await geocodeAddress("1 Dr Carlton B Goodlett Pl");

    expect(url).toContain("/geographies/onelineaddress");
    expect(url).toContain("benchmark=Public_AR_Current");
    expect(url).toContain("vintage=Current_Current");
  });
});

describe("districts whose number cannot be read off the name", () => {
  /**
   * Wyoming's BASENAME is "Congressional District (at Large)" — not a number.
   * Reading the CD off the GEOID is what makes this work, and is why the
   * parser does not touch BASENAME or the Congress-numbered CD119 field.
   */
  it("gives an at-large seat district 0", async () => {
    respondWith(cheyenneWyAtLarge);
    const result = await geocodeAddress("2020 Carey Ave, Cheyenne, WY");

    expect(result.status).toBe("ok");
    if (result.status !== "ok") return;
    expect(result.district.geoid).toBe("5600");
    expect(result.district.stateFips).toBe("56");
    expect(result.district.cdNumber).toBe(0);
    expect(result.district.districtName).toContain("at Large");
  });

  /** DC's delegate district is CD 98, which no `district` row can hold. */
  it("reports a delegate district as 98 rather than failing", async () => {
    respondWith(dcDelegate);
    const result = await geocodeAddress("1600 Pennsylvania Ave NW");

    expect(result.status).toBe("ok");
    if (result.status !== "ok") return;
    expect(result.district.geoid).toBe("1198");
    expect(result.district.cdNumber).toBe(98);
  });

  it("reads a state whose boundaries are not loaded just like any other", async () => {
    respondWith(austinTx37);
    const result = await geocodeAddress("1100 Congress Ave, Austin, TX");

    expect(result.status).toBe("ok");
    if (result.status !== "ok") return;
    // Coverage is the route's decision, not the parser's.
    expect(result.district.geoid).toBe("4837");
    expect(result.district.stateFips).toBe("48");
    expect(result.district.cdNumber).toBe(37);
  });
});

describe("the layer key is Congress-numbered", () => {
  /**
   * Census names the layer "119th Congressional Districts" and will rename it
   * for the 120th. A literal key would return nothing the morning that
   * happens; this pins the pattern match instead.
   */
  it("still finds the layer when Census renumbers it", async () => {
    respondWith({
      result: {
        addressMatches: [
          {
            matchedAddress: "1 SOMEWHERE ST, CASPER, WY, 82601",
            coordinates: { x: -106.3, y: 42.85 },
            geographies: {
              "120th Congressional Districts": [
                { GEOID: "5600", CDSESSN: "120", NAME: "Congressional District (at Large)" },
              ],
            },
          },
        ],
      },
    });
    const result = await geocodeAddress("1 Somewhere St, Casper, WY");

    expect(result.status).toBe("ok");
    if (result.status !== "ok") return;
    // Reported honestly as the 120th; the route is what refuses to join it
    // onto 119th boundaries.
    expect(result.district.congressNo).toBe(120);
  });

  it("reports no district layer when none came back", async () => {
    respondWith({
      result: {
        addressMatches: [
          {
            matchedAddress: "1 NOWHERE ST",
            coordinates: { x: 0, y: 0 },
            geographies: { States: [{ GEOID: "06" }] },
          },
        ],
      },
    });
    const result = await geocodeAddress("1 Nowhere St");
    expect(result.status).toBe("no_district_layer");
  });
});

describe("answers that are not a district", () => {
  it("treats zero matches as a real answer, not an error", async () => {
    respondWith(noMatch);
    expect((await geocodeAddress("asdfqwerzxcv 99999")).status).toBe("not_found");
  });

  it("returns every candidate when the address is ambiguous", async () => {
    respondWith(ambiguousNc);
    const result = await geocodeAddress("1 Center St, NC");

    expect(result.status).toBe("ambiguous");
    if (result.status !== "ambiguous") return;
    expect(result.candidates.length).toBeGreaterThan(1);
    expect(result.candidates[0]).toContain("CENTER ST");
  });
});

describe("upstream failure never throws", () => {
  it("reports a non-200 as an upstream error", async () => {
    respondWith({}, { status: 503 });
    const result = await geocodeAddress("1 Any St");

    expect(result.status).toBe("upstream_error");
    if (result.status !== "upstream_error") return;
    expect(result.detail).toContain("503");
    expect(result.timedOut).toBe(false);
  });

  it("reports a body that is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>maintenance</html>")));
    const result = await geocodeAddress("1 Any St");

    expect(result.status).toBe("upstream_error");
    if (result.status !== "upstream_error") return;
    expect(result.detail).toBe("response was not JSON");
  });

  it("reports a response whose shape is unexpected", async () => {
    respondWith({ result: {} });
    expect((await geocodeAddress("1 Any St")).status).toBe("upstream_error");
  });

  it("flags a timeout distinctly so the caller can answer 504", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        const error = new Error("The operation was aborted due to timeout");
        error.name = "TimeoutError";
        throw error;
      }),
    );
    const result = await geocodeAddress("1 Any St");

    expect(result.status).toBe("upstream_error");
    if (result.status !== "upstream_error") return;
    expect(result.timedOut).toBe(true);
  });

  it("flags a connection failure as not-a-timeout", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    const result = await geocodeAddress("1 Any St");

    expect(result.status).toBe("upstream_error");
    if (result.status !== "upstream_error") return;
    expect(result.timedOut).toBe(false);
    expect(result.detail).toBe("fetch failed");
  });
});
