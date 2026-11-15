import { KINDS } from "./furniture";
export type Room = "kitchen" | "bathroom";
export type Command = { name: string; args: Record<string, unknown> };

/** Fast typed commands use the same actions as the voice tools; no model or network wait. */
export function parseCommand(input: string): Command | null {
  const text = input.toLowerCase().trim().replace(/[’']/g, "");
  if (/^(undo|go back one|undo that)[.!]?$/.test(text)) return { name: "edit_furniture", args: { action: "undo" } };
  if (/\b(clean|clear|tidy)\b|^more[.!]?$/.test(text)) return { name: "clean_room", args: {} };
  const turn = text.match(/\blook (left|right|up|down|behind|forward)\b/);
  if (turn) return { name: "look", args: { direction: turn[1] } };
  const edit = text.match(/\b(bigger|smaller|remove|delete)\b/);
  if (edit) return { name: "edit_furniture", args: { action: edit[1] === "delete" ? "remove" : edit[1] } };
  if (/\b(move|put) (it|that)\b/.test(text)) return { name: "edit_furniture", args: { action: /left/.test(text) ? "left" : /right/.test(text) ? "right" : "there" } };
  if (/\b(make|turn) (it|that).*gold/.test(text)) return { name: "edit_furniture", args: { action: "gold" } };
  if (/\b(take me there|show it|focus|teleport to it)\b/.test(text)) return { name: "edit_furniture", args: { action: "focus" } };
  const kind = KINDS.find(k => new RegExp(`\\b${k}\\b`).test(text)) ?? (/\bcouch\b/.test(text) ? "sofa" : null);
  if (kind) {
    const color = Object.entries({ red: "#be4040", blue: "#4768ad", green: "#48774d", black: "#25262a", white: "#f3ede1", pink: "#da96b6", purple: "#8559a6", yellow: "#e8bf48" }).find(([key]) => text.includes(key))?.[1] ?? "#dfd3bd";
    return { name: "place_furniture", args: { kind, color, finish: /gold/.test(text) ? "gold" : /chrome|silver/.test(text) ? "chrome" : /wood|oak|walnut/.test(text) ? "wood" : "matte",
      room: /bathroom/.test(text) ? "bathroom" : /kitchen/.test(text) ? "kitchen" : kind === "toilet" ? "bathroom" : "current",
      position: ["there", "left", "right", "window", "door", "back"].find(p => text.includes(p)) ?? "front" } };
  }
  const room = text.match(/\b(kitchen|bathroom)\b/);
  if (room) return { name: "go_room", args: { room: room[1] } };
  return null;
}
