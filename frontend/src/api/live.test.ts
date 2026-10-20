import { describe, expect, it } from "vitest";
import { scheduledAirports, shortAirport } from "./live";

describe("scheduled route ends (D77)", () => {
  it("names both airports, and gives none unless both have a location", () => {
    const route = {
      origin: { iata_code: "DEL", name: "Indira Gandhi International Airport", latitude: 28.56, longitude: 77.1 },
      destination: { iata_code: "BLR", name: "Kempegowda International Airport", latitude: 13.2, longitude: 77.7 },
    };
    expect(scheduledAirports(route)).toEqual({
      origin: { at: [77.1, 28.56], code: "DEL", name: "Indira Gandhi" },
      destination: { at: [77.7, 13.2], code: "BLR", name: "Kempegowda" },
    });
    expect(scheduledAirports({ ...route, origin: { iata_code: "DEL" } })).toBeNull();
    expect(scheduledAirports(undefined)).toBeNull();
    expect(shortAirport("Chennai Airport")).toBe("Chennai");
  });
});
