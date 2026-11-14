/**
 * Photo preparation for resident uploads.
 *
 * Whatever the phone hands us (JPEG, PNG, HEIC on iPhone, WebP, huge camera originals) becomes an
 * upload-ready JPEG whose long edge is at most `maxEdge`, plus an object-URL thumbnail of that output.
 *
 * - Decoding prefers `createImageBitmap(file, { imageOrientation: "from-image" })` and falls back to
 *   an `<img>` + `img.decode()`, so EXIF rotation is applied before we draw.
 * - Safari can decode HEIC; most Chrome/Android builds cannot. When decoding fails we throw a
 *   PhotoPrepError with wording a resident can act on. Callers never see raw DOMExceptions.
 * - Transparent images are flattened onto white (JPEG has no alpha).
 * - Small JPEGs that already fit are passed through untouched to save battery.
 */

export interface PreparedPhoto {
  file: File;
  preview_url: string;
  width: number | null;
  height: number | null;
}

export const MAX_EDGE = 1600;
export const DEFAULT_QUALITY = 0.82;
/** Inputs above this are refused before decoding (a decode this large can crash a phone tab). */
export const MAX_INPUT_BYTES = 40 * 1024 * 1024;
/** A JPEG at or under this size that already fits maxEdge is sent as-is. */
export const PASSTHROUGH_BYTES = 1.5 * 1024 * 1024;

export type PhotoPrepReason = "too_large" | "not_image" | "undecodable" | "encode_failed";

export const PHOTO_PREP_MESSAGES: Record<PhotoPrepReason, string> = {
  too_large: "This photo is too large to send (over 40 MB). Try the Take photo button, or choose a smaller photo.",
  not_image: "That file isn't a photo. Choose a picture, or use the Take photo button.",
  undecodable: "This photo couldn't be opened on this phone. Try the Take photo button, or choose a JPEG or PNG.",
  encode_failed: "This photo couldn't be prepared for sending. Try again, or take a new photo.",
};

export class PhotoPrepError extends Error {
  readonly reason: PhotoPrepReason;
  constructor(reason: PhotoPrepReason, message: string = PHOTO_PREP_MESSAGES[reason]) {
    super(message);
    this.name = "PhotoPrepError";
    this.reason = reason;
  }
}

/** Scale (w, h) down so the long edge is at most maxEdge. Never scales up; never returns 0. */
export function fitWithin(width: number, height: number, maxEdge: number = MAX_EDGE): { width: number; height: number } {
  if (!(width > 0) || !(height > 0)) return { width: 0, height: 0 };
  const edge = maxEdge > 0 && Number.isFinite(maxEdge) ? Math.floor(maxEdge) : MAX_EDGE;
  const scale = Math.min(1, edge / Math.max(width, height));
  return {
    width: Math.max(1, Math.min(edge, Math.round(width * scale))),
    height: Math.max(1, Math.min(edge, Math.round(height * scale))),
  };
}

/** "IMG_0042.HEIC" -> "IMG_0042.jpg". */
export function jpegName(name: string): string {
  const base = (name || "").replace(/[/\\]/g, "_").replace(/\.[^.]*$/, "").trim();
  return `${base || "photo"}.jpg`;
}

const IMAGE_EXT = /\.(jpe?g|png|gif|webp|heic|heif|avif|bmp|tiff?)$/i;

/**
 * Cheap pre-decode screening. Returns a reason to refuse, or null to go ahead and decode.
 * Some Android pickers and iOS HEIC paths report an empty MIME type, so empty types are allowed
 * through to the decoder rather than rejected.
 */
export function screenPhoto(input: Pick<File, "size" | "type" | "name">): PhotoPrepReason | null {
  if (input.size > MAX_INPUT_BYTES) return "too_large";
  const type = (input.type || "").toLowerCase();
  if (type && !type.startsWith("image/")) return "not_image";
  if (!type && input.name && /\.[a-z0-9]{1,5}$/i.test(input.name) && !IMAGE_EXT.test(input.name)) return "not_image";
  if (input.size === 0) return "undecodable";
  return null;
}

interface Decoded {
  source: CanvasImageSource;
  width: number;
  height: number;
  release(): void;
}

async function decodeWithBitmap(file: Blob): Promise<Decoded | null> {
  if (typeof createImageBitmap !== "function") return null;
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    try {
      // Older engines reject the options bag itself; they also apply EXIF by default.
      bitmap = await createImageBitmap(file);
    } catch {
      return null;
    }
  }
  if (!bitmap.width || !bitmap.height) {
    bitmap.close();
    return null;
  }
  return { source: bitmap, width: bitmap.width, height: bitmap.height, release: () => bitmap.close() };
}

async function decodeWithImg(file: Blob): Promise<Decoded | null> {
  if (typeof document === "undefined" || typeof Image === "undefined") return null;
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.decoding = "async";
  try {
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("img load failed"));
      img.src = url;
    });
    if (typeof img.decode === "function") await img.decode().catch(() => undefined);
  } catch {
    URL.revokeObjectURL(url);
    return null;
  }
  const width = img.naturalWidth;
  const height = img.naturalHeight;
  if (!width || !height) {
    URL.revokeObjectURL(url);
    return null;
  }
  return {
    source: img,
    width,
    height,
    release: () => {
      img.removeAttribute("src");
      URL.revokeObjectURL(url);
    },
  };
}

async function decode(file: Blob): Promise<Decoded> {
  const decoded = (await decodeWithBitmap(file)) ?? (await decodeWithImg(file));
  if (!decoded) throw new PhotoPrepError("undecodable");
  return decoded;
}

function paint(ctx: OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D, img: Decoded, w: number, h: number) {
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img.source, 0, 0, w, h);
}

async function encodeOffscreen(img: Decoded, w: number, h: number, quality: number): Promise<Blob | null> {
  if (typeof OffscreenCanvas === "undefined") return null;
  try {
    const canvas = new OffscreenCanvas(w, h);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    paint(ctx, img, w, h);
    return await canvas.convertToBlob({ type: "image/jpeg", quality });
  } catch {
    return null; // e.g. Safari builds with a partial OffscreenCanvas
  }
}

async function encodeElement(img: Decoded, w: number, h: number, quality: number): Promise<Blob | null> {
  if (typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  try {
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    paint(ctx, img, w, h);
    return await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
  } catch {
    return null;
  } finally {
    // Free the backing store now; iOS caps total canvas memory per tab.
    canvas.width = 0;
    canvas.height = 0;
  }
}

export async function preparePhoto(input: File, opts: { maxEdge?: number; quality?: number } = {}): Promise<PreparedPhoto> {
  const maxEdge = opts.maxEdge && opts.maxEdge > 0 && Number.isFinite(opts.maxEdge) ? Math.floor(opts.maxEdge) : MAX_EDGE;
  const quality =
    typeof opts.quality === "number" && Number.isFinite(opts.quality) ? Math.min(1, Math.max(0.1, opts.quality)) : DEFAULT_QUALITY;

  const refused = screenPhoto(input);
  if (refused) throw new PhotoPrepError(refused);

  let decoded: Decoded | null = null;
  try {
    decoded = await decode(input);
    const name = jpegName(input.name);

    const isJpeg = /^image\/(jpeg|jpg|pjpeg)$/i.test(input.type);
    if (isJpeg && input.size <= PASSTHROUGH_BYTES && Math.max(decoded.width, decoded.height) <= maxEdge) {
      const file = input.name === name ? input : new File([input], name, { type: "image/jpeg", lastModified: input.lastModified });
      return { file, preview_url: URL.createObjectURL(file), width: decoded.width, height: decoded.height };
    }

    const { width, height } = fitWithin(decoded.width, decoded.height, maxEdge);
    const blob = (await encodeOffscreen(decoded, width, height, quality)) ?? (await encodeElement(decoded, width, height, quality));
    if (!blob || blob.size === 0) throw new PhotoPrepError("encode_failed");
    const file = new File([blob], name, { type: "image/jpeg", lastModified: Date.now() });
    return { file, preview_url: URL.createObjectURL(file), width, height };
  } catch (e) {
    if (e instanceof PhotoPrepError) throw e;
    throw new PhotoPrepError(decoded ? "encode_failed" : "undecodable");
  } finally {
    decoded?.release();
  }
}
