"use client";

/**
 * "Find your district" — the address box, the map, and the three seats.
 *
 * The address never leaves this component except in the body of a POST to our
 * own server (P4 decision D). It is not put in the URL, not stored, and not
 * sent anywhere else.
 *
 * EVERY OUTCOME IS SPOKEN. Boundaries load a slice at a time, so an address in
 * an unloaded state has a real district that this site cannot draw yet, and
 * that is a different thing from an address that does not exist. Neither is
 * allowed to render as an empty panel (PRD FR-C4).
 */

import { useCallback, useState } from "react";

import {
  RepresentativeCard,
  VacantSeatCard,
} from "@/components/representative-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type {
  DistrictResponse,
  DistrictSummary,
  LookupResponse,
  Representatives,
} from "@/lib/district-types";

import { DistrictMap } from "./district-map";

type Panel =
  | { kind: "idle" }
  | { kind: "busy" }
  | {
      kind: "seats";
      heading: string;
      note?: string;
      district: DistrictSummary;
      representatives: Representatives;
    }
  | { kind: "message"; heading: string; detail: string; candidates?: string[] };

/** "CA-11", "WY-AL" — how a seat is written, at-large included. */
function seatLabel(district: DistrictSummary): string {
  const state = district.state ?? "??";
  if (district.atLarge || district.cdNumber === 0) return `${state}-AL`;
  return `${state}-${String(district.cdNumber).padStart(2, "0")}`;
}

export function DistrictExplorer({
  topojsonUrl,
  coveredStates,
}: {
  topojsonUrl: string | null;
  coveredStates: string[];
}) {
  const [address, setAddress] = useState("");
  const [panel, setPanel] = useState<Panel>({ kind: "idle" });
  const [selectedGeoid, setSelectedGeoid] = useState<string | null>(null);

  const showDistrict = useCallback(
    (
      district: DistrictSummary,
      representatives: Representatives,
      heading: string,
      note?: string,
    ) => {
      setPanel({ kind: "seats", heading, note, district, representatives });
    },
    [],
  );

  /** Clicking a district on the map. No address involved, so a plain GET. */
  const handleSelect = useCallback(
    async (geoid: string) => {
      setSelectedGeoid(geoid);
      setPanel({ kind: "busy" });
      try {
        const response = await fetch(`/api/districts/${geoid}`);
        const body = (await response.json()) as DistrictResponse;
        if (body.status !== "ok") {
          setPanel({
            kind: "message",
            heading: "District not available",
            detail: body.detail,
          });
          return;
        }
        showDistrict(
          body.district,
          body.representatives,
          seatLabel(body.district),
        );
      } catch {
        setPanel({
          kind: "message",
          heading: "Could not load that district",
          detail: "The request failed. Try again.",
        });
      }
    },
    [showDistrict],
  );

  const handleSubmit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      const value = address.trim();
      if (!value) return;

      setPanel({ kind: "busy" });
      let body: LookupResponse;
      try {
        const response = await fetch("/api/districts/lookup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: value }),
        });
        body = (await response.json()) as LookupResponse;
      } catch {
        setPanel({
          kind: "message",
          heading: "Lookup failed",
          detail: "The request did not complete. Check your connection.",
        });
        return;
      }

      switch (body.status) {
        case "ok":
          setSelectedGeoid(body.district.geoid);
          showDistrict(
            body.district,
            body.representatives,
            seatLabel(body.district),
            body.match.matchedAddress,
          );
          return;

        case "not_covered":
          // A real district this site cannot draw yet. The Senators are
          // complete, so they are shown rather than withheld.
          setSelectedGeoid(null);
          showDistrict(
            body.district,
            body.representatives,
            seatLabel(body.district),
            body.detail,
          );
          return;

        case "non_voting_delegate":
          setSelectedGeoid(null);
          setPanel({
            kind: "message",
            heading: "Non-voting delegate district",
            detail: body.detail,
          });
          return;

        case "ambiguous":
          setSelectedGeoid(null);
          setPanel({
            kind: "message",
            heading: "More than one address matched",
            detail: body.detail,
            candidates: body.candidates,
          });
          return;

        case "not_found":
        case "congress_mismatch":
        case "no_district_layer":
        case "upstream_error":
        case "bad_request":
          setSelectedGeoid(null);
          setPanel({
            kind: "message",
            heading:
              body.status === "not_found"
                ? "No matching address"
                : body.status === "upstream_error"
                  ? "The Census Geocoder is unavailable"
                  : "Could not determine a district",
            detail: body.detail,
          });
          return;
      }
    },
    [address, showDistrict],
  );

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor="address" className="sr-only">
          Street address
        </label>
        <input
          id="address"
          name="address"
          type="text"
          autoComplete="street-address"
          maxLength={250}
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          placeholder="1 Dr Carlton B Goodlett Pl, San Francisco, CA 94102"
          className="flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <Button type="submit" disabled={panel.kind === "busy" || !address.trim()}>
          {panel.kind === "busy" ? "Looking up…" : "Find my district"}
        </Button>
      </form>

      <p className="text-xs text-muted-foreground">
        The address is sent to our server, which asks the U.S. Census Geocoder.
        It is never stored, and never sent from your browser to anyone else.
      </p>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <DistrictMap
          topojsonUrl={topojsonUrl}
          selectedGeoid={selectedGeoid}
          onSelect={handleSelect}
        />

        <div className="space-y-3">
          {panel.kind === "idle" ? (
            <Card>
              <CardContent className="py-5 text-sm text-muted-foreground">
                <p>
                  Enter an address, or click a district on the map, to see the
                  three seats that represent it — one House member and both of
                  the state&rsquo;s Senators.
                </p>
                <p className="mt-3">
                  Boundaries are loaded for{" "}
                  <span className="font-medium text-foreground">
                    {coveredStates.length > 0 ? coveredStates.join(", ") : "no states yet"}
                  </span>
                  . Other states are being added.
                </p>
              </CardContent>
            </Card>
          ) : null}

          {panel.kind === "busy" ? (
            <Card>
              <CardContent className="py-5 text-sm text-muted-foreground">
                Looking up…
              </CardContent>
            </Card>
          ) : null}

          {panel.kind === "message" ? (
            <Card>
              <CardContent className="space-y-3 py-5">
                <p className="text-sm font-semibold">{panel.heading}</p>
                <p className="text-sm text-muted-foreground">{panel.detail}</p>
                {panel.candidates?.length ? (
                  <ul className="space-y-1 border-t pt-3 text-sm">
                    {panel.candidates.map((candidate) => (
                      <li key={candidate}>
                        <button
                          type="button"
                          className="text-left hover:underline"
                          onClick={() => {
                            setAddress(candidate);
                          }}
                        >
                          {candidate}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          {panel.kind === "seats" ? (
            <>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  District
                </p>
                <h2 className="text-lg font-semibold tracking-tight">
                  {panel.heading}
                </h2>
                {panel.note ? (
                  <p className="mt-1 text-xs text-muted-foreground">{panel.note}</p>
                ) : null}
              </div>

              {panel.representatives.house ? (
                <RepresentativeCard
                  representative={panel.representatives.house}
                  seat={`House · ${seatLabel(panel.district)}`}
                />
              ) : (
                <VacantSeatCard seat={`House · ${seatLabel(panel.district)}`} />
              )}

              {panel.representatives.senate.map((senator) => (
                <RepresentativeCard
                  key={senator.bioguideId}
                  representative={senator}
                  // FR-G5: the Senate has no districts, so the seat is the state.
                  seat={`Senate · ${panel.district.state ?? senator.state ?? ""}`}
                />
              ))}

              {panel.representatives.senate.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  This jurisdiction elects no Senators.
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
