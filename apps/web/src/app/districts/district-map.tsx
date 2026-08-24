"use client";

/**
 * The district map: MapLibre over the TopoJSON published to R2.
 *
 * WHY NO BASEMAP. The style declares one background colour and our own
 * boundary layers, and no raster tile source at all. Every hosted basemap
 * worth using wants an API key, a billing account and a third-party request
 * per tile carrying the reader's IP; none of that buys anything here, because
 * the only thing this map has to answer is "which of these shapes am I in".
 * It also means the map has exactly one network dependency — the R2 object —
 * and no key to leak.
 *
 * WHY TOPOJSON AND NOT POSTGIS. The geometry is served straight from the CDN,
 * so drawing the map costs the database nothing (Deployment-Architecture-Report
 * §2c). The object key is read from `district.topojson_r2_key` rather than
 * built here, so a rebuilt map — the key carries a content fingerprint — is
 * picked up without a deploy.
 */

import {
  AttributionControl,
  setWorkerUrl,
  type LngLatBoundsLike,
  Map as MapLibreMap,
  type MapGeoJSONFeature,
  NavigationControl,
} from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";

import "maplibre-gl/dist/maplibre-gl.css";

/**
 * Load MapLibre's worker from a real same-origin URL.
 *
 * Without this the bundler's handling of MapLibre's own `new Worker(new URL(
 * ...))` leaves it constructing the worker from a blob, the blob worker dies
 * on creation, and every source stays unloaded forever. Nothing throws:
 * `addSource` and `addLayer` both succeed, no map `error` fires, and the only
 * symptom is a blank canvas. Measured in `next dev` and in a production build
 * alike, 2026-08-25.
 *
 * The file is copied out of node_modules at dev/build time by
 * `scripts/vendor-maplibre-worker.mjs`, so it tracks the installed version.
 */
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const SOURCE_ID = "districts";
const FILL_LAYER = "districts-fill";
const LINE_LAYER = "districts-line";
const SELECTED_LAYER = "districts-selected";

/** Fits the loaded states with a little air around them. */
const FIT_PADDING = 32;

const NO_MAP_PUBLISHED =
  "No published district map to load. The boundaries job has not published a " +
  "TopoJSON, or R2_PUBLIC_BASE_URL is not configured.";

export type DistrictMapProps = {
  /** Full public URL of the TopoJSON object, or null when unavailable. */
  topojsonUrl: string | null;
  /** GEOID to highlight, or null. */
  selectedGeoid: string | null;
  onSelect: (geoid: string) => void;
};

type LoadState =
  | { phase: "loading" }
  | { phase: "ready"; districts: number }
  | { phase: "error"; detail: string };

/** Bounding box of a GeoJSON geometry, as MapLibre wants it. */
function bboxOf(geometry: GeoJSON.Geometry): LngLatBoundsLike | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  const visitCoords = (coords: unknown): void => {
    if (!Array.isArray(coords)) return;
    if (typeof coords[0] === "number" && typeof coords[1] === "number") {
      const [x, y] = coords as [number, number];
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      return;
    }
    for (const child of coords) visitCoords(child);
  };

  // A GeometryCollection carries `geometries`, not `coordinates`. Handling it
  // is not tidiness: the initial fit passes every district as one collection,
  // and without this branch bboxOf returned null and the map opened at a
  // hardcoded continental view instead of framing the loaded states.
  const visit = (g: GeoJSON.Geometry): void => {
    if (g.type === "GeometryCollection") g.geometries.forEach(visit);
    else visitCoords(g.coordinates);
  };

  visit(geometry);
  return Number.isFinite(minX)
    ? [
        [minX, minY],
        [maxX, maxY],
      ]
    : null;
}

export function DistrictMap({
  topojsonUrl,
  selectedGeoid,
  onSelect,
}: DistrictMapProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const collection = useRef<GeoJSON.FeatureCollection | null>(null);
  // Derived from the prop rather than set from inside the effect: "there is
  // no map to load" is knowable at first render, and setting it in an effect
  // would be a cascading render for something already decided.
  const [state, setState] = useState<LoadState>(() =>
    topojsonUrl ? { phase: "loading" } : { phase: "error", detail: NO_MAP_PUBLISHED },
  );

  // `onSelect` is called from a MapLibre event handler registered once. Held
  // in a ref so a re-render with a new callback identity does not require
  // tearing down and re-registering the map's listeners.
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const fitTo = useCallback((geometry: GeoJSON.Geometry) => {
    const bounds = bboxOf(geometry);
    if (bounds && map.current) {
      map.current.fitBounds(bounds, { padding: FIT_PADDING, duration: 900 });
    }
  }, []);

  useEffect(() => {
    if (!container.current || map.current || !topojsonUrl) return;

    const instance = new MapLibreMap({
      container: container.current,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: { "background-color": "#f6f6f4" },
          },
        ],
      },
      center: [-98.5, 39.8],
      zoom: 3,
      attributionControl: false,
    });
    map.current = instance;

    instance.addControl(new NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(
      new AttributionControl({
        customAttribution:
          "Boundaries: U.S. Census Bureau cartographic boundary files",
      }),
    );

    let cancelled = false;

    const load = async () => {
      let topology: Topology;
      try {
        const response = await fetch(topojsonUrl, { mode: "cors" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        topology = (await response.json()) as Topology;
      } catch (error) {
        if (cancelled) return;
        setState({
          phase: "error",
          detail: `Could not load the district boundaries: ${
            error instanceof Error ? error.message : "request failed"
          }`,
        });
        return;
      }
      if (cancelled) return;

      const object = topology.objects?.districts;
      if (!object) {
        setState({
          phase: "error",
          detail: "The published map has no `districts` object.",
        });
        return;
      }

      const geojson = feature(topology, object) as unknown as GeoJSON.FeatureCollection;
      collection.current = geojson;

      const attach = () => {
        if (cancelled || instance.getSource(SOURCE_ID)) return;
        instance.addSource(SOURCE_ID, {
          type: "geojson",
          data: geojson,
          // `geoid` is what every lookup keys on; promoting it makes it usable
          // as the feature id for hover and selection state.
          promoteId: "geoid",
        });
        instance.addLayer({
          id: FILL_LAYER,
          type: "fill",
          source: SOURCE_ID,
          paint: {
            "fill-color": "#94a3b8",
            "fill-opacity": [
              "case",
              ["boolean", ["feature-state", "hover"], false],
              0.45,
              0.22,
            ],
          },
        });
        instance.addLayer({
          id: LINE_LAYER,
          type: "line",
          source: SOURCE_ID,
          paint: { "line-color": "#475569", "line-width": 0.6 },
        });
        // Drawn above the others and filtered to nothing until a district is
        // selected, so highlighting is a filter change rather than a restyle.
        instance.addLayer({
          id: SELECTED_LAYER,
          type: "line",
          source: SOURCE_ID,
          paint: { "line-color": "#0f172a", "line-width": 2.5 },
          filter: ["==", ["get", "geoid"], "__none__"],
        });

        let hovered: string | number | undefined;
        instance.on("mousemove", FILL_LAYER, (event) => {
          const hit = event.features?.[0] as MapGeoJSONFeature | undefined;
          if (!hit) return;
          instance.getCanvas().style.cursor = "pointer";
          if (hovered !== undefined) {
            instance.setFeatureState({ source: SOURCE_ID, id: hovered }, { hover: false });
          }
          hovered = hit.id;
          if (hovered !== undefined) {
            instance.setFeatureState({ source: SOURCE_ID, id: hovered }, { hover: true });
          }
        });
        instance.on("mouseleave", FILL_LAYER, () => {
          instance.getCanvas().style.cursor = "";
          if (hovered !== undefined) {
            instance.setFeatureState({ source: SOURCE_ID, id: hovered }, { hover: false });
          }
          hovered = undefined;
        });
        instance.on("click", FILL_LAYER, (event) => {
          const hit = event.features?.[0];
          const geoid = hit?.properties?.geoid;
          if (typeof geoid === "string") onSelectRef.current(geoid);
        });

        const whole = bboxOf({
          type: "GeometryCollection",
          geometries: geojson.features.map((f) => f.geometry),
        });
        if (whole) instance.fitBounds(whole, { padding: FIT_PADDING, duration: 0 });

        setState({ phase: "ready", districts: geojson.features.length });
      };

      if (instance.isStyleLoaded()) attach();
      else instance.once("load", attach);
    };

    void load();

    return () => {
      cancelled = true;
      instance.remove();
      map.current = null;
    };
  }, [topojsonUrl]);

  // Selection is driven from outside — an address lookup or a click — so the
  // highlight and the fly-to both follow the prop rather than local state.
  useEffect(() => {
    const instance = map.current;
    if (!instance || state.phase !== "ready") return;
    if (!instance.getLayer(SELECTED_LAYER)) return;

    instance.setFilter(SELECTED_LAYER, [
      "==",
      ["get", "geoid"],
      selectedGeoid ?? "__none__",
    ]);

    if (!selectedGeoid) return;
    const hit = collection.current?.features.find(
      (f) => (f.properties as { geoid?: string } | null)?.geoid === selectedGeoid,
    );
    if (hit) fitTo(hit.geometry);
  }, [selectedGeoid, state.phase, fitTo]);

  return (
    <div className="relative overflow-hidden rounded-lg border">
      <div
        ref={container}
        className="h-[420px] w-full sm:h-[520px]"
        role="application"
        aria-label="Map of congressional districts"
      />
      {state.phase !== "ready" ? (
        <div className="absolute inset-0 flex items-center justify-center bg-background/85 p-6 text-center">
          <p className="max-w-md text-sm text-muted-foreground">
            {state.phase === "loading"
              ? "Loading district boundaries…"
              : state.detail}
          </p>
        </div>
      ) : null}
      {/* Also update the R2 source note when the source of these files moves. */}
      {state.phase === "ready" ? (
        <p className="border-t bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          {state.districts} districts drawn. Click one to see who represents it.
        </p>
      ) : null}
    </div>
  );
}
