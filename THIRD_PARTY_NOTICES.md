# Third-party notices

## Code

**God's Eye View — MIT License, Copyright (c) 2026 Bilawal Sidhu** (https://github.com/bilawalsidhu/gods-eye-view)
Ported or adapted files carry a header naming the original path:
- `frontend/src/map/wind.ts` (src/layers/wind/model.js, src/layers/wind/source.js)
- `backend/app/live/classify.py` (src/data/aircraftClass.js, src/data/aircraftEmergency.js)
- `backend/app/live/feeds.py` (server/providers/aircraft/*.js, src/sources/live/aircraft.js, src/layers/aircraft/classification.js)
- `wind/vendor/**` (server/providers/wind.js, server/providers/wind/*.js, src/sources/windBody.js), copied verbatim

```
MIT License
Copyright (c) 2026 Bilawal Sidhu
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

**skylight — MIT License** (https://github.com/cpaczek/skylight). The aircraft type-designator sets in
`backend/app/live/classify.py` were adapted by God's Eye View from skylight's `aircraftGlyph.ts`.

| Library | Licence |
|---|---|
| MapLibre GL JS | BSD-3-Clause |
| B612 / B612 Mono fonts | SIL OFL 1.1 |
| React, TanStack Query, Zustand, React Router | MIT |
| FastAPI, SQLAlchemy, GeoAlchemy2, Shapely, httpx, truststore | MIT / BSD |
| @meri-imperiumi/eccodes-wasm | Apache-2.0 |

## Data (credits panel text in docs/API.md §10)
| Source | Licence / terms |
|---|---|
| DataMeet India maps: india-soi outline, States, Districts (Census 2011) | CC BY 4.0 / CC BY 2.5 IN |
| Natural Earth admin-0 (India point of view) | Public domain |
| geoBoundaries (neighbour ADM1/ADM2) | Per boundary, mostly CC BY 4.0 / public domain |
| GeoNames cities1000 | CC BY 4.0 |
| OpenStreetMap via Geofabrik (roads, rail, telecom towers) and the Overpass API (railway stations) | ODbL 1.0: © OpenStreetMap contributors. Share-alike applies if the database is distributed |
| OurAirports | Public domain |
| Wikipedia (station / squadron lists, aircraft inventory) | Facts only, with a source URL per row |
| OpenFreeMap vector tiles (OpenMapTiles schema, Noto Sans glyphs) | © OpenMapTiles, data © OpenStreetMap contributors (ODbL); OpenFreeMap is free to use with attribution |
| AWS Terrain Tiles (Mapzen terrarium) | Open data; attribution per source (SRTM, GMTED, ETOPO1 and others) |
| Esri World Imagery (optional satellite layer) | Esri terms, attribution |
| Indian Air Force crest (`frontend/public/iaf-crest.svg`, Wikimedia Commons) | Government Open Data Licence – India (GODL-India); use governed by the Emblems and Names (Prevention of Improper Use) Act, 1950 |
| adsb.lol | ODbL |
| adsb.fi, OpenSky Network, adsbdb | Provider terms (non-commercial) |
| NOAA Aviation Weather Center, nowCOAST, GFS | US Government public data |
| ECMWF open data | CC BY 4.0 |
| Open-Meteo | CC BY 4.0 |
| OpenWeatherMap | Provider terms |

## Public-road routing

Infra connectivity requests distance-based routes from the public [Valhalla / FOSSGIS](https://valhalla.openstreetmap.de/) service, using OpenStreetMap data (ODbL 1.0, copyright OpenStreetMap contributors). No Valhalla engine code or new library is bundled. Attribution and links to OpenStreetMap copyright and Fix the map appear in the connection card; the map attribution names the routing provider. Follow the provider's fair-use limits; this is a demo integration, not a guaranteed service.

`data/fixtures/valhalla_route.json` is an unmodified routing response recorded on 2026-10-18 for the existing public VIJO / VIUT coordinates, with auto shortest-distance costing, hierarchy pruning disabled where supported, OSRM format and GeoJSON shape. It is used only for offline tests and is covered by the routing-data attribution above. It does not establish verified access to a base.
