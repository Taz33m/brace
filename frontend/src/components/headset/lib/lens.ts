/**
 * Fitting a split picture to a phone viewer's lenses. Each eye's picture must sit under its lens, or the eyes
 * cannot merge the two into one scene. Phones and viewers differ, so the spacing is set by eye on a fit screen
 * and remembered on the phone. iPhones show about 6.3 CSS pixels per millimetre (roughly 160 per inch).
 */
export const PX_PER_MM = 6.3;
export const SPACING_DEFAULT_MM = 60;
export const EYES_M = 0.064;
const SPACING_KEY = "brace.headset.spacingMm";

export const readSpacing = (): number => {
  try {
    const v = Number(window.localStorage.getItem(SPACING_KEY));
    return v >= 40 && v <= 80 ? v : SPACING_DEFAULT_MM;
  } catch {
    return SPACING_DEFAULT_MM;
  }
};

export const saveSpacing = (mm: number) => {
  try { window.localStorage.setItem(SPACING_KEY, String(mm)); } catch { /* private mode: keep it for this visit only */ }
};

/** Where each eye's picture goes: centred under its lens, as wide as fits without crossing the middle. */
export function eyeViewports(W: number, H: number, spacingMm: number): { x: number; w: number }[] {
  const sep = Math.min(W * 0.95, spacingMm * PX_PER_MM);
  const w = Math.max(1, Math.min(sep, W - sep, H * 1.15));
  return [-1, 1].map((side) => ({ x: Math.round(W / 2 + (side * sep) / 2 - w / 2), w: Math.round(w) }));
}

/** The field of view down one eye's picture: about 90 degrees across, which is what a phone viewer's lens shows. */
export function eyeFov(aspect: number): number {
  return Math.min(100, Math.max(70, (2 * Math.atan(Math.tan(Math.PI / 4) / aspect) * 180) / Math.PI));
}
