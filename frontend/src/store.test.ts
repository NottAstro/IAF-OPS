import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const values = new Map<string, string>();
beforeEach(() => {
  vi.resetModules();
  values.clear();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) });
});
afterEach(() => vi.unstubAllGlobals());

describe("map view preferences", () => {
  it("defaults to tilt and relief height 1.5", async () => {
    const { useStore } = await import("./store");
    expect(useStore.getState()).toMatchObject({ tilt: true, exaggeration: 1.5 });
  });
  it("loads persisted false and a valid relief height", async () => {
    values.set("airops.view.v1", JSON.stringify({ tilt: false, exaggeration: 2.5 }));
    const { useStore } = await import("./store");
    expect(useStore.getState()).toMatchObject({ tilt: false, exaggeration: 2.5 });
  });
  it("persists both values on either change and reloads them without persisting camera state", async () => {
    const { useStore } = await import("./store");
    useStore.getState().set({ tilt: false });
    expect(JSON.parse(values.get("airops.view.v1")!)).toEqual({ tilt: false, exaggeration: 1.5 });
    useStore.getState().set({ exaggeration: 3 });
    useStore.getState().set({ mode: "WX", cursor: { lat: 28, lon: 77 } });
    expect(JSON.parse(values.get("airops.view.v1")!)).toEqual({ tilt: false, exaggeration: 3 });
    vi.resetModules();
    expect((await import("./store")).useStore.getState()).toMatchObject({ tilt: false, exaggeration: 3, mode: "LIVE" });
  });
  it("ignores malformed JSON, null, wrong types and invalid heights", async () => {
    for (const saved of ["{", "null", '{"tilt":0,"exaggeration":"3"}', '{"exaggeration":99}']) {
      values.set("airops.view.v1", saved);
      vi.resetModules();
      expect((await import("./store")).useStore.getState()).toMatchObject({ tilt: true, exaggeration: 1.5 });
    }
  });
});
