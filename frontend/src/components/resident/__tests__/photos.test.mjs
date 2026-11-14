import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./load.mjs";

const p = await loadTs("lib/photos.ts");

test("fitWithin scales the long edge down to maxEdge and never up", () => {
  assert.deepEqual(p.fitWithin(4032, 3024, 1600), { width: 1600, height: 1200 });
  assert.deepEqual(p.fitWithin(3024, 4032, 1600), { width: 1200, height: 1600 });
  assert.deepEqual(p.fitWithin(800, 600, 1600), { width: 800, height: 600 });
  assert.deepEqual(p.fitWithin(1600, 1600, 1600), { width: 1600, height: 1600 });
  assert.deepEqual(p.fitWithin(10000, 3, 1600), { width: 1600, height: 1 });
  assert.deepEqual(p.fitWithin(0, 100, 1600), { width: 0, height: 0 });
  assert.equal(p.MAX_EDGE, 1600);
  for (const [w, h] of [[4033, 3025], [1601, 1599], [99999, 77777]]) {
    const out = p.fitWithin(w, h);
    assert.ok(Math.max(out.width, out.height) <= 1600, `${w}x${h}`);
  }
});

test("jpegName swaps the extension for .jpg", () => {
  assert.equal(p.jpegName("IMG_0042.HEIC"), "IMG_0042.jpg");
  assert.equal(p.jpegName("scan.png"), "scan.jpg");
  assert.equal(p.jpegName("no-ext"), "no-ext.jpg");
  assert.equal(p.jpegName(""), "photo.jpg");
  assert.match(p.jpegName("a/b.jpeg"), /\.jpg$/);
});

test("files over 40 MB are refused before decoding", async () => {
  const big = new File([new Uint8Array(40 * 1024 * 1024 + 1)], "huge.jpg", { type: "image/jpeg" });
  await assert.rejects(p.preparePhoto(big), (e) => e instanceof p.PhotoPrepError && e.reason === "too_large" && /40 MB/.test(e.message));
});

test("non-image files are refused with a clear message", async () => {
  for (const f of [new File(["%PDF"], "lease.pdf", { type: "application/pdf" }), new File(["hi"], "note.txt", { type: "" })]) {
    await assert.rejects(p.preparePhoto(f), (e) => e instanceof p.PhotoPrepError && e.reason === "not_image" && /isn't a photo/.test(e.message), f.name);
  }
});

test("an undecodable image becomes a friendly PhotoPrepError, never a raw exception", async () => {
  // Node has no createImageBitmap/document: same outcome as HEIC on a browser that can't read it.
  const heic = new File([new Uint8Array(32)], "IMG_0001.HEIC", { type: "image/heic" });
  await assert.rejects(p.preparePhoto(heic), (e) => e instanceof p.PhotoPrepError && e.reason === "undecodable" && /Take photo/.test(e.message));
  const typeless = new File([new Uint8Array(32)], "IMG_0002.heic", { type: "" });
  await assert.rejects(p.preparePhoto(typeless), (e) => e instanceof p.PhotoPrepError && e.reason === "undecodable");
});

test("screenPhoto lets typeless images through to the decoder", () => {
  assert.equal(p.screenPhoto({ size: 10, type: "", name: "IMG_1.HEIC" }), null);
  assert.equal(p.screenPhoto({ size: 10, type: "", name: "blob" }), null);
  assert.equal(p.screenPhoto({ size: 10, type: "image/png", name: "x.png" }), null);
  assert.equal(p.screenPhoto({ size: 0, type: "image/png", name: "x.png" }), "undecodable");
  assert.equal(p.screenPhoto({ size: 10, type: "video/mp4", name: "x.mp4" }), "not_image");
});
