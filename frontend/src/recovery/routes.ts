/** Hash routes shared by the preparation, owner, and isolated resident roots. */
export type AppRoute =
  | { kind: "prepare"; scenario: string | null; step: string | null; building: number | null; vr: boolean }
  | { kind: "walk"; scenario: string; step: string | null; building: number }
  | { kind: "recovery"; case_id: string | null }
  | { kind: "resident"; invitation_token: string | null }
  | { kind: "invalid"; message: string };

export interface InvitationLocation {
  hash: string;
  pathname: string;
  search: string;
}

export interface InvitationHistory {
  state?: unknown;
  replaceState(data: unknown, unused: string, url?: string | URL | null): void;
}

const invalid = (message = "This Brace link is invalid."): AppRoute => ({ kind: "invalid", message });
const safePart = (value: string): boolean =>
  value.length > 0 && value.length <= 256 && value !== "." && value !== ".." &&
  !/[\/\\?#\s\u0000-\u001f\u007f]/u.test(value);
const safeToken = (value: string): boolean =>
  value.length > 0 && value.length <= 512 && !/[\s\u0000-\u001f\u007f]/u.test(value);
const safeBuilding = (value: number): boolean => Number.isSafeInteger(value) && value > 0;

function decodePart(value: string): string {
  const decoded = decodeURIComponent(value);
  if (!safePart(decoded)) throw new Error("Invalid path component");
  return decoded;
}

function readQuery(query: string): URLSearchParams {
  // URLSearchParams alone replaces malformed UTF-8 and tolerates broken escapes.
  // Validate the raw encoding before its forgiving parser sees it.
  for (const part of query.split("&")) {
    const equals = part.indexOf("=");
    const key = equals < 0 ? part : part.slice(0, equals);
    const value = equals < 0 ? "" : part.slice(equals + 1);
    decodeURIComponent(key.replace(/\+/g, " "));
    decodeURIComponent(value.replace(/\+/g, " "));
  }
  return new URLSearchParams(query);
}

/** Invalid input returns a controlled route; it never throws or echoes tokens. */
export function parseAppRoute(hash: string): AppRoute {
  try {
    if (hash === "" || hash === "#" || hash === "#/") {
      return { kind: "prepare", scenario: null, step: null, building: null, vr: false };
    }
    if (!hash.startsWith("#") || hash.slice(1).includes("#")) return invalid();
    const fragment = hash.slice(1).replace(/^\//, "");
    const queryAt = fragment.indexOf("?");
    const path = queryAt < 0 ? fragment : fragment.slice(0, queryAt);
    const query = queryAt < 0 ? null : fragment.slice(queryAt + 1);
    const parts = path.replace(/\/$/, "").split("/").map(decodePart);
    const prefix = parts[0];
    if (prefix === "resident") {
      if (parts.length !== 1) return invalid();
      const invitations = readQuery(query ?? "").getAll("invite");
      if (invitations.length > 1 || (invitations.length === 1 && !safeToken(invitations[0]))) {
        return invalid("This resident invitation is invalid. Request a new invitation.");
      }
      return { kind: "resident", invitation_token: invitations[0] ?? null };
    }
    if (query !== null) return invalid();
    if (prefix === "recovery") {
      return parts.length <= 2 ? { kind: "recovery", case_id: parts[1] ?? null } : invalid();
    }
    const vr = prefix === "vr";
    const walk = prefix === "walk";
    const prepare = vr || walk ? parts.slice(1) : parts;
    if (!prepare.length) return invalid();
    const scenario = prepare[0];
    if (["resident", "recovery", "vr", "walk"].includes(scenario)) return invalid();
    let step: string | null = null;
    let building: number | null = null;
    let offset = 1;
    if (prepare[offset] && prepare[offset] !== "b") {
      step = prepare[offset] === "-" ? null : prepare[offset];
      offset += 1;
    }
    if (prepare[offset]) {
      if (prepare[offset] !== "b" || prepare.length !== offset + 2 || !/^[1-9]\d*$/.test(prepare[offset + 1])) return invalid();
      building = Number(prepare[offset + 1]);
      if (!safeBuilding(building)) return invalid();
    }
    // The walk-through is always of one building.
    if (walk) return building === null ? invalid() : { kind: "walk", scenario, step, building };
    return { kind: "prepare", scenario, step, building, vr };
  } catch {
    return invalid();
  }
}

function encodedPart(value: string): string {
  if (!safePart(value)) throw new Error("Invalid Brace route identifier.");
  return encodeURIComponent(value);
}

export function prepareHash(scenario: string | null, step: string | null = null,
                            building: number | null = null, vr = false): string {
  if (scenario === null) {
    if (step !== null || building !== null || vr) throw new Error("A scenario is required for this route.");
    return "#/";
  }
  if (["resident", "recovery", "vr", "walk"].includes(scenario)) throw new Error("Reserved Brace route identifier.");
  if (step === "b" || step === "-") throw new Error("Reserved Brace step identifier.");
  if (building !== null && !safeBuilding(building)) throw new Error("A positive building ID is required.");
  return `#/${vr ? "vr/" : ""}${encodedPart(scenario)}/${step === null ? "-" : encodedPart(step)}${building === null ? "" : `/b/${building}`}`;
}

export function walkHash(scenario: string, step: string | null, building: number): string {
  return prepareHash(scenario, step, building).replace(/^#\//, "#/walk/");
}

export function recoveryHash(case_id: string | null = null): string {
  return `#/recovery${case_id === null ? "" : `/${encodedPart(case_id)}`}`;
}

export function residentHash(invitation_token: string | null = null): string {
  if (invitation_token === null) return "#/resident";
  if (!safeToken(invitation_token)) throw new Error("Invalid resident invitation.");
  return `#/resident?invite=${encodeURIComponent(invitation_token)}`;
}

/**
 * Consume once, before session exchange or any owner bootstrap. The caller keeps
 * the return value in memory. No storage, network, or global browser dependency.
 * Invalid invitations are scrubbed before a sanitized error reaches the caller.
 */
export function consumeResidentInvitation(locationLike: InvitationLocation,
                                          historyLike: InvitationHistory): string | null {
  const hash = locationLike.hash;
  const queryAt = hash.indexOf("?");
  const route = parseAppRoute(hash);
  if (queryAt >= 0) {
    const rawQuery = hash.slice(queryAt + 1);
    const parameters = new URLSearchParams(rawQuery);
    let malformed = false;
    try { readQuery(rawQuery); } catch { malformed = true; }
    if (parameters.has("invite") || malformed) {
      parameters.delete("invite");
      // A malformed query can conceal an invitation key. Remove that whole
      // fragment query; the actual URL pathname/search remain exactly intact.
      const remaining = malformed ? "" : parameters.toString();
      const cleanHash = hash.slice(0, queryAt) + (remaining ? `?${remaining}` : "");
      historyLike.replaceState(historyLike.state ?? null, "",
        `${locationLike.pathname}${locationLike.search}${cleanHash}`);
    }
  }
  if (route.kind === "invalid") throw new Error(route.message);
  return route.kind === "resident" ? route.invitation_token : null;
}
