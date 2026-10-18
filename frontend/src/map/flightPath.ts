/** Sample the shortest great-circle arc; unwrap longitude so dateline legs don't cross the whole map. */
export function greatCircle(from: number[], to: number[]): number[][] {
  const rad = Math.PI / 180;
  const vector = ([lon, lat]: number[]) => [Math.cos(lat * rad) * Math.cos(lon * rad), Math.cos(lat * rad) * Math.sin(lon * rad), Math.sin(lat * rad)];
  const a = vector(from), b = vector(to);
  const dot = Math.max(-1, Math.min(1, a.reduce((v, x, i) => v + x * b[i], 0)));
  const angle = Math.acos(dot);
  if (angle < 1e-8) return [from, to];
  const tangent = b.map((x, i) => x - dot * a[i]);
  let length = Math.hypot(...tangent);
  if (length < 1e-8) {
    // Antipodes have no unique shortest arc: choose the perpendicular through the north pole.
    tangent.splice(0, 3, -a[2] * a[0], -a[2] * a[1], 1 - a[2] ** 2);
    length = Math.hypot(...tangent);
    if (length < 1e-8) { tangent.splice(0, 3, 1, 0, 0); length = 1; }
  }
  let previous = from[0];
  return Array.from({ length: 65 }, (_, i) => {
    const t = angle * i / 64;
    const v = a.map((x, j) => x * Math.cos(t) + tangent[j] / length * Math.sin(t));
    let lon = Math.atan2(v[1], v[0]) / rad;
    while (lon - previous > 180) lon -= 360;
    while (lon - previous < -180) lon += 360;
    previous = lon;
    return [lon, Math.atan2(v[2], Math.hypot(v[0], v[1])) / rad];
  });
}
