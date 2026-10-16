#!/usr/bin/env bash
# Probe every upstream in docs/API.md and print a pass/fail table (run before every demo).
UA="iaf-airops-netcheck/0.1"
printf "%-30s %-6s %-8s %s\n" "SOURCE" "HTTP" "TIME" "NOTE"
check() {
  local name=$1 url=$2 note=${3:-}
  local out
  out=$(curl -s -o /dev/null -A "$UA" -w "%{http_code} %{time_total}" --max-time 25 "$url" 2>/dev/null) || true
  [ -z "$out" ] && out="000 0"
  local code=${out% *} t=${out#* }
  local mark="ok"
  case "$code" in 2*|3*|401|403|405) ;; *) mark="FAIL";; esac
  printf "%-30s %-6s %-8s %s %s\n" "$name" "$code" "${t}s" "$mark" "$note"
}
check "adsb.lol /v2/mil"           "https://api.adsb.lol/v2/mil"
check "adsb.fi point"              "https://opendata.adsb.fi/api/v2/lat/28.6/lon/77.2/dist/50"
check "OpenSky states (anon)"      "https://opensky-network.org/api/states/all?lamin=28&lomin=76&lamax=29&lomax=78"
check "adsbdb"                     "https://api.adsbdb.com/v0/callsign/AIC101"
check "aviationweather METAR"      "https://aviationweather.gov/api/data/metar?ids=VIDP&format=json"
check "Open-Meteo"                 "https://api.open-meteo.com/v1/forecast?latitude=28.6&longitude=77.2&current=temperature_2m"
check "OpenWeatherMap tiles"       "https://tile.openweathermap.org/map/clouds_new/3/5/3.png" "(401 = reachable, key added server-side)"
check "NOAA nowCOAST WMS"          "https://nowcoast.noaa.gov/geoserver/observations/satellite/ows?service=WMS&request=GetCapabilities"
check "NOAA GFS (S3)"              "https://noaa-gfs-bdp-pds.s3.amazonaws.com/"
check "Esri World Imagery"         "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/3/3/5"
check "OpenFreeMap basemap"        "https://tiles.openfreemap.org/planet"
check "OpenFreeMap fonts"          "https://tiles.openfreemap.org/fonts/Noto%20Sans%20Regular/0-255.pbf"
check "AWS terrain (terrarium)"    "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/5/22/13.png"
