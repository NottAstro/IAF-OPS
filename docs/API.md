# API: Free Data Sources and How We Use Them

> **Update 2026-10-16:** the map engine is now **MapLibre GL** (flat map), the theme is navy + neon blue with the official IAF crest, and the tick simulator is switched off for Phase 1. See ARCHITECTURE §18 D19–D21. Where this document still describes CesiumJS, Cesium ion, the olive/amber theme or live simulation on the map, D19–D21 take precedence.


| | |
|---|---|
| Status | Draft v0.1. **Last verified 2026-10-16 (IST)** by live requests from the team's network |
| Purpose | Where to get each free data feed (live aircraft, weather, terrain, boundaries, infrastructure, bases), what it costs, how God's Eye View uses it, and how we use it |
| Related | [ARCHITECTURE §6–§9](ARCHITECTURE.md), [PRD §7](PRD.md) |

**How to read the tables:**
- **✔ verified** means a live request on 2026-10-16 succeeded, with the result noted.
- **(v)** means taken from provider docs or third parties and not exercised live. Re-check before relying on it.
- Terms change often. Whoever integrates a source re-checks its endpoint, limits and terms, and updates the "last verified" date.
- **Keys never go to the browser.** Every keyed source is proxied by the FastAPI backend. The only exception is the Cesium ion token, which is public by design and restricted by URL.

---

## 1. Live aircraft

| Provider | Gives | Endpoint(s) | Key | Free limits | India coverage (observed 00:28 IST) | Terms | God's Eye usage | Our usage |
|---|---|---|---|---|---|---|---|---|
| **adsb.lol** ✔ | Positions by point/radius, global military list, hex lookup, traces | `https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}` · `https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{nm}` (same result) · `https://api.adsb.lol/v2/mil` · `/v2/hex/{hex}` · docs `https://api.adsb.lol/docs` | none (README says feeder-linked keys may come later) | dynamic, load-based (v) | Delhi 250 NM: **29** · Bengaluru: **40** · Leh: **7** · `/mil` in region: **0** (395 worldwide) | ODbL 1.0, attribution | `server/providers/aircraft/adsb-lol.js` (`/v2/mil`, 12 s cache), `opensky.js` fallback `fetchAdsbLolPointFallback`, `src/data/adsbLolFallback.js`, traces in `tracks.js` | **Primary (merged)**: viewport point queries + `/mil` |
| **adsb.fi** ✔ | Same readsb-style JSON | `https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{nm}` · `https://opendata.adsb.fi/api/v2/mil` | none | ~1 req/s on public endpoints (v) | Delhi 250 NM: **71** · `/mil` in region: **2** (`VUBCF` C-295 and one A319) | personal, non-commercial; attribution + link (v) | — | **Primary (merged)**. Note: point response key is `aircraft`, `/mil` key is `ac` |
| **OpenSky Network** ✔ | State vectors for a bbox; track history | `https://opensky-network.org/api/states/all?lamin=0&lomin=60&lamax=42&lomax=105&extended=1` · tracks `/api/tracks/all?icao24={hex}&time=0` · token `https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token` | optional; **OAuth2 client credentials only** (basic auth no longer accepted) | Credits/day for `/states/*`: anonymous **400**, standard user **4,000**, active feeder 8,000. Our bbox (42° × 45° = 1,890 sq°) costs **4 credits/call**, so anonymous ≈ 100 calls/day, user ≈ 1,000/day. Anonymous resolution 10 s | Anonymous region bbox: **372** states | non-commercial / research | `server/providers/aircraft/opensky.js` (`openSkyProxy`, credit-aware cache, OAuth), `tracks.js` | Theatre snapshot every 60–90 s with credentials (every 15 min anonymous) + fallback |
| **airplanes.live** ✔ (blocked) | readsb-style JSON, `/mil`, point | `https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}` · `/v2/mil` | **now returns HTTP 403** asking you to email `contact@airplanes.live` with a project description | 1 req/s (v) | — | non-commercial | — | **Optional**: enable only if access is granted |
| ADS-B Exchange | Full feed | RapidAPI | paid | — | — | commercial | — | **Rejected** (paid) |
| Flightradar24 / FlightAware | Flight data | — | paid | — | — | commercial | — | **Rejected** (paid) |

**What the coverage tells us:**
- **Merge adsb.lol and adsb.fi.** They draw on different feeder networks, and over Delhi adsb.fi returned 2.4× the aircraft.
- **Indian military aircraft, UAVs and drones barely appear on public ADS-B.** This is why simulated IAF tracks exist (PRD FR-LIVE-07) and why empty toggles say "not broadcast".

### 1.1 Aircraft enrichment

Selected aircraft also use the authenticated local endpoint `GET /api/v1/live/aircraft/{hex}/trail`.
It returns up to 120 observed `{lat, lon, alt_m, ts}` positions (UTC epoch seconds), empty if unseen/expired.
History covers only the time since this server first saw the aircraft and expires with its live track.
It makes no upstream requests. adsbdb airport coordinates, when present, support a labelled scheduled route;
that route may differ from actual and is not a filed flight plan. No upstream trace service has been added.
| Provider | Gives | Endpoint | Key | Limits | Terms | God's Eye | Ours |
|---|---|---|---|---|---|---|---|
| **adsbdb** ✔ | Type, registration, operator for a hex; route for a callsign | `https://api.adsbdb.com/v0/aircraft/{hex}` · `https://api.adsbdb.com/v0/callsign/{callsign}` (✔ `AIC101` → Air India route) | none | none published (be gentle) | free; route data from public sources | `server/providers/aircraft/enrichment.js` (24 h disk cache incl. misses) | On track click only; 24 h LRU incl. misses |

### 1.2 Your own receiver (could)
An RTL-SDR dongle plus `readsb`/`dump1090` exposes `http://<pi>/data/aircraft.json` in the same readsb format. God's Eye supports this via `LOCAL_RECEIVER_FEEDS` (`server/providers/local-receivers.js`). It would add local low-altitude coverage at the demo venue.

---

## 2. Weather

| Provider | Gives | Endpoint(s) | Key | Free limits | India coverage | Terms | God's Eye usage | Our usage |
|---|---|---|---|---|---|---|---|---|
| **aviationweather.gov Data API** (NOAA AWC) ✔ | METAR, TAF, station info | `https://aviationweather.gov/api/data/metar?bbox=0,60,42,105&format=json` (✔ returned the region) · `.../metar?ids=VIDP,VILH&format=raw` · `.../taf?ids=VIDP&format=raw` (✔) · `.../stationinfo?bbox=...&format=json` (✔) · bulk cache `https://aviationweather.gov/data/cache/metars.cache.csv.gz` (updated every minute) · OpenAPI spec `/data/schema/openapi.yaml` | none; **set a custom User-Agent** | **100 requests/min**; most endpoints return at most 400 entries; last 30 days only | Civil and joint-use fields report (VIDP, VIAR, VILH, VIJP, VOBG ✔). **Air Force-only stations mostly do not** (VIAX Adampur ✘) | US Government public data | — | `GET /wx/metar` refresh every 5 min, `taf` every 30 min; nearest-station fallback ≤ 50 km (FR-WX-01) |
| **Open-Meteo** ✔ | Point forecast: current + hourly, pressure-level winds, cloud layers, visibility, freezing level | `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&current=..&hourly=..` (✔ Leh) | none | **< 10,000/day, 5,000/hour, 600/min** (~300,000/month), non-commercial | global | **CC BY 4.0**, attribution | `server/providers/regional/weather.js` (`/api/weather-effects`) | Click popover (FR-WX-02); METAR fallback. Cache 10 min, key = lat/lon rounded to 0.1° |
| **OpenWeatherMap Weather Maps 1.0** ✔ (endpoint up, needs key) | Raster tiles: `clouds_new`, `precipitation_new`, `pressure_new`, `wind_new`, `temp_new` | `https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={KEY}` (✔ returns 401 without key) | **free API key** (sign up at openweathermap.org) | Free plan ~60 calls/min, 1M/month (v) | global | CC BY-SA 4.0 data (v); attribution | — | Overlays via backend proxy `/wx/owm/{layer}/{z}/{x}/{y}.png` (FR-WX-03); 10 min tile cache |
| **NOAA GFS 0.25°** | Wind, temperature, pressure grids (GRIB2) | `https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{YYYYMMDD}/{HH}/atmos/gfs.t{HH}z.pgrb2.0p25.f{FFF}` + `.idx` (byte-range reads) | none | — | global | public domain | `server/providers/wind/gfs.js`, `catalog.js`, decoded with `@meri-imperiumi/eccodes-wasm` | Wind sidecar (FR-WX-04), default model |
| **ECMWF IFS open data** | Same, 0.25° | `https://data.ecmwf.int/forecasts/{date}/{hh}z/ifs/0p25/oper/...` | none | — | global | CC BY 4.0 + ECMWF terms | `server/providers/wind/ifs.js` | Wind sidecar, optional model toggle |
| **NOAA nowCOAST** ✔ | Global IR satellite cloud mosaic (WMS) | `https://nowcoast.noaa.gov/geoserver/observations/satellite/ows?service=WMS&request=GetCapabilities` (✔ lists `global_longwave_imagery_mosaic`) | none | — | **only the global longwave mosaic covers India**; radar and lightning are US/Americas only | NOAA disclaimer | `server/providers/weather.js` (`/api/weather/*`) | IR via proxy, re-coloured in the browser to white cloud cover (FR-WX-05, ARCHITECTURE D23) |
| **NASA GIBS** ✔ | Daily satellite imagery layers (WMTS) | `https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/1.0.0/WMTSCapabilities.xml` (✔) | none | — | global | NASA open data; attribution requested | `server/providers/weather.js` (recent imagery) | Could: true-colour / cloud layer |
| **RainViewer** ✔ | Radar composite tiles | `https://api.rainviewer.com/public/weather-maps.json` (✔) | none | Since Jan 2026: **max zoom 7, Universal Blue scheme only, no satellite or nowcast, 100 req/IP/min**; personal/educational use | radar coverage over India unclear (v) | attribution "Weather data by Rain Viewer" | — | **Not used** unless India coverage is verified |

---

## 3. Imagery and terrain

| Provider | Endpoint | Key | Terms | Network note | God's Eye usage | Our usage |
|---|---|---|---|---|---|---|
| **Esri World Imagery** ✔ | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` (✔ tile 200) | none | Esri terms; attribution "Esri, Maxar, Earthstar Geographics, and the GIS User Community" (v) | ok | `src/maps/imagery.js` `createEsriImagery` (default keyless basemap) | **Default basemap**, darkened per DESIGN_SYSTEM §8. No labels or borders in the imagery, which suits the GoI-boundary rule |
| **Cesium NaturalEarthII** | Bundled in the `cesium` npm package (`Assets/Textures/NaturalEarthII`) | none | public domain | offline | — | Offline / low-bandwidth basemap |
| **Cesium ion World Terrain** | ion asset 1 via `Cesium.createWorldTerrainAsync()` | **free ion token** (sign up at ion.cesium.com; restrict to your URLs) | free Community tier for personal/non-commercial use (v) | ok (v) | `src/maps/terrain.js` `createWorldTerrain` | **Primary terrain** (FR-TER-01). Never enable ion's Bing *labelled* imagery (its borders are not the GoI depiction) |
| **Re:Earth / Mapterhorn terrain** ✘ (blocked here) | `https://terrain.reearth.land/cesium-mesh/ellipsoid` | none | CC BY 4.0 | **Blocked by the team's campus firewall** (SVKM-NMIMS FortiGate: "Web Filter Violation"); works on open networks per God's Eye | `src/maps/terrain.js` `KEYLESS_TERRAIN_URL` + `terrainRetry.js` | Fallback terrain |
| Google Photorealistic 3D Tiles | Map Tiles API | paid key | Google terms | — | `src/maps/google3d.js` | **Rejected** (billing; not needed) |
| OSM standard tiles / OpenFreeMap | `tile.openstreetmap.org`, `tiles.openfreemap.org/planet` | none | ODbL / tile policy | — | OSM fallback basemap; OpenFreeMap roads and military land use | **Rejected for rendering**: they draw non-GoI international boundaries |

---

## 4. Boundaries, admin divisions and place names

| Source | Gives | Where to get it | Key | Licence | Notes |
|---|---|---|---|---|---|
| **DataMeet maps** ✔ | India outline per the official Survey of India depiction; states; districts | `https://github.com/datameet/maps`: `Country/india-soi.geojson` (SoI-derived), `Country/india-composite.geojson` (incl. PoK, Aksai Chin, Shaksgam; built from LSIB + Alhasan + Natural Earth), `Country/disputed/*.geojson`, `States/Admin2.shp`, `Districts/Census_2011/2011_Dist.shp` | none | Repo default **CC BY 4.0**; `india-composite` **CC-0**; Districts **CC BY 2.5 IN**; `india-soi` licence section not read (v) | Districts are Census-2011 vintage; check post-2019 J&K/Ladakh changes (PRD §14) |
| **Natural Earth, India point of view** ✔ | Admin-0 countries drawn per India's claims | `https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries_ind.zip` (✔ 200) · GeoJSON mirror `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries_ind.geojson` (✔ 200) | none | public domain | Neighbour outlines + cross-check of India's outline. (The 50m IND file is not published: 403) |
| **geoBoundaries** ✔ | ADM1/ADM2 for neighbours | `https://www.geoboundaries.org/api/current/gbOpen/{ISO3}/{ADM1\|ADM2}/` → `gjDownloadURL` / `simplifiedGeometryGeoJSON` (✔ PAK ADM2 → Public Domain, 2019) | none | per boundary (mostly CC BY 4.0 / public domain); read `boundaryLicense` | **Must be clipped**: `ST_Difference(unit, india_outline)` removes PoK/G-B/Aksai Chin/Shaksgam (ARCHITECTURE §9) |
| **GeoNames** | Populated places with population | `https://download.geonames.org/export/dump/cities1000.zip` | none | CC BY 4.0 | Label LOD tiers |
| **Survey of India** | Official maps | `https://onlinemaps.surveyofindia.gov.in` | registration (v) | GoI terms (v) | Reference/authority for disputes; not a direct data source in Phase 1 |

---

## 5. Infrastructure (roads, rail, telecom towers)

| Source | Gives | Where | Key | Licence | Our usage |
|---|---|---|---|---|---|
| **Geofabrik OSM extracts** | Raw OSM for each country | `https://download.geofabrik.de/asia/{india,pakistan,nepal,bhutan,bangladesh,sri-lanka,myanmar,china}-latest.osm.pbf` (China is large; extract the bbox first) | none | **ODbL 1.0** (attribution "© OpenStreetMap contributors"; share-alike if the DB is distributed) | Offline pipeline: `osmium extract --bbox 60,0,105,42` → `osmium tags-filter` for `highway=motorway,trunk,primary`, `railway=rail`, `man_made=mast,tower` + `tower:type=communication` → PostGIS |
| OpenRailwayMap tiles | Rendered rail overlay | `https://{a,b,c}.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png` | none | CC BY-SA; tile usage policy (v) | Could: visual rail overlay (no borders in the tiles) |
| Overpass API | Ad-hoc OSM queries | public servers | none | ODbL | **Not used.** Public servers refused God's Eye's traffic (it now needs self-hosted `OVERPASS_UPSTREAMS`); the offline pipeline replaces it |

---

## 6. Airports and air bases

| Source | Gives | Where | Key | Licence | Our usage |
|---|---|---|---|---|---|
| **OurAirports** ✔ | All airports, heliports, runways, ICAO/IATA, coordinates | `https://davidmegginson.github.io/ourairports-data/airports.csv` (✔ 12.7 MB; 653 India rows, 63 with "Air Force" in the name) · `runways.csv` | none | **public domain** | Coordinates/ICAO for `iaf_bases.csv`; runway dimensions; civil airports layer; neighbour military fields (by name keywords + curation) |
| **Wikipedia** | IAF station list (by command), squadron/unit articles, active aircraft inventory, PAF/PLAAF base lists | `List_of_Indian_Air_Force_stations`, `List_of_active_Indian_military_aircraft` (✔ read 2026-10-16) | none | CC BY-SA (text); we take facts only, with a URL per row | Curated CSVs (DATA_MODEL §8.1, Appendix A). The stations article notes its unit data dates from 2009, so verify |
| God's Eye `osm_military_names/names.json` | 36,466 OSM-tagged military area names (119 airfields in the India bbox) | `../gods-eye-view/src/data/local_data/osm_military_names/names.json` | — | ODbL | **Cross-check only**; never a placement source for synthetic sites |

---

### 6.1 Public-road routing (Infra connectivity focus)

- **Provider:** [Valhalla / FOSSGIS](https://valhalla.openstreetmap.de/), fixed upstream `POST https://valhalla1.openstreetmap.de/route`; verified 2026-10-18 with public Jodhpur and Uttarlai locations. No key or new dependency.
- **Local API:** authenticated `GET /api/v1/bases/{id}/connections` returns public source identity/coordinates and four nearby public IAF bases, ordered by exact geographic distance. `GET /api/v1/bases/{id}/connections/{destination}` returns an available road geometry/distance/retrieval time or an unavailable message. The destination must be one of that source's four nearby own-force bases. No arbitrary URL or coordinate proxy. No inventory or synthetic site coordinates are sent upstream.
- **Routing:** auto profile, `shortest=true`, `disable_hierarchy_pruning=true`, OSRM JSON with GeoJSON geometry, no turn-by-turn instructions. [Valhalla documentation](https://valhalla.github.io/valhalla/api/route/api-reference/) states that distance costing alone can be suboptimal under hierarchy pruning, and the disable option is subject to server distance limits. Do not promise a globally optimal or fastest journey.
- **Limits:** one selected pair on demand; 1.1 s globally between request starts, one active request, identical requests coalesced, 24 h LRU cache of 512 pairs, 60 s backoff on 429; no bulk calculations. Follow the [FOSSGIS fair-use policy](https://routing.openstreetmap.de/about.html): identify the app, at most one request/second, attribution and a Fix the map link, no scraping/heavy use.
- **Safeguards:** fixed HTTPS host, no redirects, existing verified TLS client, 25 s HTTP/30 s total request timeout, 2 MiB response and 100,000-coordinate cap; reject non-finite/out-of-region geometry. Offline/errors show unavailable, never invented roads. Requests contain public base locations and are subject to provider logging.
- **Interpretation:** road distance is between snapped network endpoints, not verified base entrances. Draw estimated access connectors separately; direct distances remain geographic proximity, not validated flight routes. No live traffic or travel-time claim.
- **Attribution/data:** Valhalla / FOSSGIS; OpenStreetMap contributors (ODbL). A recorded response is in `data/fixtures/valhalla_route.json`; tests use fixtures/MockTransport, never live network.

---

## 7. Libraries and assets (licences)

| Item | Licence | Use |
|---|---|---|
| CesiumJS 1.138 | Apache-2.0 | 3D globe |
| God's Eye View (ported modules) | MIT, "Copyright (c) 2026 Bilawal Sidhu" | see ARCHITECTURE §11 |
| skylight (inside God's Eye `aircraftClass.js`) | MIT | aircraft classification tables |
| B612 / B612 Mono | SIL OFL 1.1 | UI fonts (self-hosted via @fontsource) |
| Lucide | ISC | UI icons |
| God's Eye `public/models/*.glb` | CC BY 4.0 (authors in `public/models/README.md`) | optional 3D track models |
| `@meri-imperiumi/eccodes-wasm` | Apache-2.0 (v) | GRIB2 decode in wind sidecar |

---

## 8. Getting keys (all free)

| Key | Needed for | How |
|---|---|---|
| `VITE_CESIUM_ION_TOKEN` | Primary 3D terrain | Sign up at `https://ion.cesium.com` → Access Tokens → create one with `assets:read`, and **restrict allowed URLs** to your demo origins |
| `OWM_API_KEY` | Weather overlays | Sign up at `https://openweathermap.org` → API keys. New keys can take up to ~2 h to activate (v) |
| `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` | 10× more OpenSky credits | Create an OpenSky account → Account page → API client (OAuth2 client credentials) |
| airplanes.live access | Optional 3rd ADS-B feed | Email `contact@airplanes.live` with the project description and links |

No keys are needed for adsb.lol, adsb.fi, adsbdb, aviationweather.gov, Open-Meteo, GFS/IFS, nowCOAST, GIBS, Esri imagery, or any GIS download.

---

## 9. Poll budget vs limits

| Source | Our cadence | Calls/day (approx.) | Limit | Headroom |
|---|---|---|---|---|
| adsb.lol point queries | ≤ 4 circles / 10 s while a viewer is active; 4 / 30 s idle | ≤ 35k active-hours-dependent | dynamic | Back off on 429 / `Retry-After` |
| adsb.fi point queries | same as adsb.lol, staggered ≥ 1 s apart | same | ~1 req/s | Keep ≤ 1 req/s globally per provider |
| `/mil` (adsb.lol + adsb.fi) | 30 s | 2 × 2,880 | dynamic / 1 req/s | ok |
| OpenSky bbox | 90 s (user) / 15 min (anon) | 960 / 96 | 1,000 / 100 calls | tight: never call more often |
| aviationweather.gov | METAR 5 min, TAF 30 min, stationinfo once at startup | ~340 | 100/min | ample |
| Open-Meteo | on click, 10 min cache | < 1,000 | 10,000/day | ample |
| OWM tiles | on view, 10 min cache | depends on panning | ~60/min (v) | cap the proxy at 50 req/min |
| nowCOAST / GIBS | 10 min cache | low | — | ok |
| GFS/IFS (sidecar) | 1 h cache | low | — | ok |

---

## 10. Attribution strings
These go in the credits panel (FR-MAP-16) and `THIRD_PARTY_NOTICES.md`.

- "Imagery: Esri, Maxar, Earthstar Geographics, and the GIS User Community"
- "Terrain: Cesium ion World Terrain" / "Terrain: Re:Earth / Mapterhorn (CC BY 4.0)"
- "Boundaries: DataMeet India community (CC BY 4.0 / CC BY 2.5 IN / CC-0); Natural Earth (public domain); geoBoundaries (per-boundary licence)"
- "Places: GeoNames (CC BY 4.0)"
- "Roads, railways, towers: © OpenStreetMap contributors (ODbL), via Geofabrik"
- "Airports: OurAirports (public domain)"
- "Live aircraft: adsb.lol (ODbL), adsb.fi, The OpenSky Network; enrichment: adsbdb"
- "Aviation weather: NOAA Aviation Weather Center"
- "Weather data by Open-Meteo.com (CC BY 4.0)"
- "Weather maps: OpenWeatherMap"
- "Wind: NOAA GFS; ECMWF open data (CC BY 4.0)"
- "Satellite IR: NOAA nowCOAST"
- "Road routing: Valhalla / FOSSGIS; data copyright OpenStreetMap contributors (ODbL)"
- "Map code portions: God's Eye View, © 2026 Bilawal Sidhu (MIT)"
- "Fonts: B612 (SIL OFL)"

---

## 11. Network checklist (run before every demo)
`make netcheck` curls each ✔ endpoint above and prints status, latency and bytes.

Known issue on 2026-10-16: on the team's campus network, `terrain.reearth.land` is blocked by the FortiGate web filter, and TLS is inspected by a FortiGate CA. If backend HTTPS calls fail with certificate errors, set `HTTPS_CA_BUNDLE` (ARCHITECTURE §13), or use a hotspot.
