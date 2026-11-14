/**
 * PLACEHOLDER — replaced by the mobile-hardening builder.
 * Contract for callers: preparePhoto turns any picked/captured image into an upload-ready JPEG
 * (long edge <= maxEdge) plus a thumbnail object URL. Never throws for HEIC on Safari.
 */
export interface PreparedPhoto {
  file: File;
  preview_url: string;
  width: number | null;
  height: number | null;
}

export async function preparePhoto(input: File, _opts: { maxEdge?: number; quality?: number } = {}): Promise<PreparedPhoto> {
  return { file: input, preview_url: URL.createObjectURL(input), width: null, height: null };
}
