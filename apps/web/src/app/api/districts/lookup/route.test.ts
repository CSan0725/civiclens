/**
 * The lookup route's decision-making.
 *
 * The geocoder and the database are both mocked here on purpose. What this
 * route contributes is the JOIN between a geocoded GEOID and what CivicLens
 * actually holds, plus the honesty rules around it — which failures are real
 * answers, which are HTTP errors, and what a reader is told when boundaries
 * for their state are not loaded. Those decisions are what the tests pin.
 *
 * Parsing of real Census payloads is covered separately, against captured
 * fixtures, in `lib/census-geocoder.test.ts`.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GeocodeResult } from "@/lib/census-geocoder";

const geocodeAddress = vi.fn<(address: string) => Promise<GeocodeResult>>();
const getDistrictByGeoid = vi.fn();
const getSittingSenators = vi.fn();
const getStatesWithBoundaries = vi.fn();

vi.mock("@/lib/census-geocoder", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/census-geocoder")>()),
  geocodeAddress: (address: string) => geocodeAddress(address),
}));

vi.mock("@/db/queries", () => ({
  getDistrictByGeoid: (...a: unknown[]) => getDistrictByGeoid(...a),
  getSittingSenators: (...a: unknown[]) => getSittingSenators(...a),
  getStatesWithBoundaries: (...a: unknown[]) => getStatesWithBoundaries(...a),
}));

const { POST } = await import("./route");

/** Two sitting Senators, the shape `getSittingSenators` returns. */
const SENATORS = {
  CA: [
    { bioguideId: "S001150", name: "Adam B. Schiff", party: "Democratic", state: "CA" },
    { bioguideId: "P000145", name: "Alex Padilla", party: "Democratic", state: "CA" },
  ],
  WY: [
    { bioguideId: "L000571", name: "Cynthia M. Lummis", party: "Republican", state: "WY" },
    { bioguideId: "B001261", name: "John Barrasso", party: "Republican", state: "WY" },
  ],
  NC: [
    { bioguideId: "B001305", name: "Ted Budd", party: "Republican", state: "NC" },
    { bioguideId: "T000476", name: "Thom Tillis", party: "Republican", state: "NC" },
  ],
  TX: [
    { bioguideId: "C001056", name: "John Cornyn", party: "Republican", state: "TX" },
    { bioguideId: "C001098", name: "Ted Cruz", party: "Republican", state: "TX" },
  ],
};

function geocoded(
  over: Partial<{
    geoid: string;
    stateFips: string;
    cdNumber: number;
    congressNo: number;
    districtName: string;
    matchedAddress: string;
  }> = {},
): GeocodeResult {
  return {
    status: "ok",
    district: {
      geoid: "0611",
      stateFips: "06",
      cdNumber: 11,
      congressNo: 119,
      districtName: "Congressional District 11",
      matchedAddress: "1 DR CARLTON P GOODLETT PL, SAN FRANCISCO, CA, 94102",
      longitude: -122.418,
      latitude: 37.778,
      ...over,
    },
  };
}

function storedDistrict(over: Record<string, unknown> = {}) {
  return {
    geoid: "0611",
    congressNo: 119,
    state: "CA",
    stateFips: "06",
    cdNumber: 11,
    atLarge: false,
    topojsonR2Key: "districts/congress-119.aaad7416d0af.topojson",
    sourceUrl: "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_cd119_500k.zip",
    retrievedAt: "2026-08-24T22:21:35.096Z",
    representative: {
      bioguideId: "P000197",
      name: "Nancy Pelosi",
      party: "Democratic",
      state: "CA",
      photoUrl: null,
      officialUrl: null,
    },
    ...over,
  };
}

function post(body: unknown, raw?: string) {
  return POST(
    new Request("http://localhost/api/districts/lookup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: raw ?? JSON.stringify(body),
    }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getStatesWithBoundaries.mockResolvedValue(["CA", "NC", "WY"]);
});

describe("an address in a loaded state", () => {
  it("returns the Representative and both Senators", async () => {
    geocodeAddress.mockResolvedValue(geocoded());
    getDistrictByGeoid.mockResolvedValue(storedDistrict());
    getSittingSenators.mockResolvedValue(SENATORS.CA);

    const response = await post({ address: "1 Dr Carlton B Goodlett Pl, SF, CA" });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.status).toBe("ok");
    expect(body.district.geoid).toBe("0611");
    expect(body.representatives.house.name).toBe("Nancy Pelosi");
    expect(body.representatives.senate).toHaveLength(2);
    expect(body.representatives.senate.map((s: { name: string }) => s.name)).toEqual([
      "Adam B. Schiff",
      "Alex Padilla",
    ]);
  });

  it("carries the R2 key the map needs to draw the district", async () => {
    geocodeAddress.mockResolvedValue(geocoded());
    getDistrictByGeoid.mockResolvedValue(storedDistrict());
    getSittingSenators.mockResolvedValue(SENATORS.CA);

    const body = await (await post({ address: "anywhere" })).json();
    expect(body.district.topojsonR2Key).toContain("districts/congress-119.");
  });

  it("handles an at-large seat, where the district number is 0", async () => {
    geocodeAddress.mockResolvedValue(
      geocoded({
        geoid: "5600",
        stateFips: "56",
        cdNumber: 0,
        districtName: "Congressional District (at Large)",
        matchedAddress: "2020 CAREY AVE, CHEYENNE, WY, 82001",
      }),
    );
    getDistrictByGeoid.mockResolvedValue(
      storedDistrict({
        geoid: "5600",
        state: "WY",
        stateFips: "56",
        cdNumber: 0,
        atLarge: true,
        representative: {
          bioguideId: "H001096",
          name: "Harriet M. Hageman",
          party: "Republican",
          state: "WY",
        },
      }),
    );
    getSittingSenators.mockResolvedValue(SENATORS.WY);

    const body = await (await post({ address: "2020 Carey Ave, Cheyenne, WY" })).json();

    expect(body.status).toBe("ok");
    expect(body.district.atLarge).toBe(true);
    expect(body.district.cdNumber).toBe(0);
    expect(body.representatives.house.name).toBe("Harriet M. Hageman");
    expect(body.representatives.senate).toHaveLength(2);
  });

  it("reports a vacant seat as a null House member, not as a failure", async () => {
    geocodeAddress.mockResolvedValue(
      geocoded({ geoid: "3702", stateFips: "37", cdNumber: 2 }),
    );
    getDistrictByGeoid.mockResolvedValue(
      storedDistrict({ geoid: "3702", state: "NC", cdNumber: 2, representative: null }),
    );
    getSittingSenators.mockResolvedValue(SENATORS.NC);

    const body = await (await post({ address: "1 E Edenton St, Raleigh, NC" })).json();

    expect(body.status).toBe("ok");
    expect(body.representatives.house).toBeNull();
    expect(body.representatives.senate).toHaveLength(2);
  });

  it("looks the district up for the Congress the app stores", async () => {
    geocodeAddress.mockResolvedValue(geocoded());
    getDistrictByGeoid.mockResolvedValue(storedDistrict());
    getSittingSenators.mockResolvedValue(SENATORS.CA);

    await post({ address: "anywhere" });

    expect(getDistrictByGeoid).toHaveBeenCalledWith("0611", 119);
    expect(getSittingSenators).toHaveBeenCalledWith("CA", 119);
  });
});

describe("an address outside the loaded slice (FR-C4)", () => {
  it("says so, names the loaded states, and still returns the Senators", async () => {
    geocodeAddress.mockResolvedValue(
      geocoded({
        geoid: "4837",
        stateFips: "48",
        cdNumber: 37,
        matchedAddress: "1100 CONGRESS AVE, AUSTIN, TX, 78701",
      }),
    );
    getDistrictByGeoid.mockResolvedValue(undefined);
    getSittingSenators.mockResolvedValue(SENATORS.TX);

    const response = await post({ address: "1100 Congress Ave, Austin, TX" });
    const body = await response.json();

    // A coverage gap is a truthful answer, so it is a 200 and not an error.
    expect(response.status).toBe(200);
    expect(body.status).toBe("not_covered");
    expect(body.coverage.boundariesLoadedFor).toEqual(["CA", "NC", "WY"]);
    expect(body.detail).toContain("CA, NC, WY");
    expect(body.district.geoid).toBe("4837");
    expect(body.representatives.house).toBeNull();
    // The whole point: not an empty result.
    expect(body.representatives.senate).toHaveLength(2);
  });
});

describe("jurisdictions that are not a voting district", () => {
  it("names DC's Delegate and reports no Senators", async () => {
    geocodeAddress.mockResolvedValue(
      geocoded({
        geoid: "1198",
        stateFips: "11",
        cdNumber: 98,
        districtName: "Delegate District (at Large)",
        matchedAddress: "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
      }),
    );

    const response = await post({ address: "1600 Pennsylvania Ave NW" });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.status).toBe("non_voting_delegate");
    expect(body.detail).toContain("DC");
    expect(body.representatives.senate).toEqual([]);
    // No district row can hold CD 98, so the database is never asked.
    expect(getDistrictByGeoid).not.toHaveBeenCalled();
  });
});

describe("answers that are not a district", () => {
  it("returns not_found with guidance rather than an empty body", async () => {
    geocodeAddress.mockResolvedValue({ status: "not_found" });

    const response = await post({ address: "asdfqwerzxcv 99999" });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.status).toBe("not_found");
    expect(body.detail).toBeTruthy();
  });

  it("passes the candidate list through when the address is ambiguous", async () => {
    geocodeAddress.mockResolvedValue({
      status: "ambiguous",
      candidates: ["1 CENTER ST, TARBORO, NC, 27886", "1 CENTER ST, CANTON, NC, 28716"],
    });

    const body = await (await post({ address: "1 Center St, NC" })).json();

    expect(body.status).toBe("ambiguous");
    expect(body.candidates).toHaveLength(2);
  });

  it("refuses to join a different Congress onto stored boundaries", async () => {
    geocodeAddress.mockResolvedValue(geocoded({ congressNo: 120 }));

    const body = await (await post({ address: "anywhere" })).json();

    expect(body.status).toBe("congress_mismatch");
    expect(getDistrictByGeoid).not.toHaveBeenCalled();
  });

  it("reports a match that carried no district layer", async () => {
    geocodeAddress.mockResolvedValue({
      status: "no_district_layer",
      matchedAddress: "1 NOWHERE ST",
    });

    const body = await (await post({ address: "1 Nowhere St" })).json();
    expect(body.status).toBe("no_district_layer");
  });
});

describe("upstream failure maps to an HTTP error", () => {
  it("answers 504 when Census did not respond in time", async () => {
    geocodeAddress.mockResolvedValue({
      status: "upstream_error",
      detail: "no response within 8000ms",
      timedOut: true,
    });

    const response = await post({ address: "anywhere" });
    expect(response.status).toBe(504);
    expect((await response.json()).status).toBe("upstream_error");
  });

  it("answers 502 when Census failed for any other reason", async () => {
    geocodeAddress.mockResolvedValue({
      status: "upstream_error",
      detail: "Census Geocoder returned HTTP 503",
      timedOut: false,
    });

    const response = await post({ address: "anywhere" });
    expect(response.status).toBe(502);
  });
});

describe("a malformed request is a 400, not an answer", () => {
  it("rejects a body that is not JSON", async () => {
    const response = await post(undefined, "not json");
    expect(response.status).toBe(400);
    expect(geocodeAddress).not.toHaveBeenCalled();
  });

  it("rejects a missing address", async () => {
    expect((await post({})).status).toBe(400);
  });

  it("rejects a blank address", async () => {
    expect((await post({ address: "   " })).status).toBe(400);
  });

  it("rejects an address longer than the cap", async () => {
    const response = await post({ address: "a".repeat(400) });
    expect(response.status).toBe(400);
    expect(geocodeAddress).not.toHaveBeenCalled();
  });

  it("trims the address before sending it upstream", async () => {
    geocodeAddress.mockResolvedValue({ status: "not_found" });
    await post({ address: "  1 Main St  " });
    expect(geocodeAddress).toHaveBeenCalledWith("1 Main St");
  });
});
