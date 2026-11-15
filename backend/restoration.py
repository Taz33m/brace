"""The room companion is separate from the report explainer. All scene edits happen in the browser."""
import os
from fastapi import APIRouter, HTTPException
from . import voice

router = APIRouter(prefix="/api/restoration")

def tool(name, description, properties, required):
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}

def choice(values):
    return {"type": "string", "enum": values}

def session():
    tools = [
        tool("clean_room", "Advance cleanup. 'Let's clean this place up' removes contents while retaining burn marks. 'More' restores the empty room. Only changes the illustration.", {}, []),
        tool("go_room", "Move to the kitchen or bathroom viewpoint in this same home.", {"room": choice(["kitchen", "bathroom"])}, ["room"]),
        tool("look", "Turn the view in the requested direction.", {"direction": choice(["left", "right", "up", "down", "behind", "forward"])}, ["direction"]),
        tool("place_furniture", "Instantly place an editable 3D concept object. Use bathroom for a toilet unless another room is requested. Moves to that room, prepares its empty restored view, and faces the object. 'There' uses the last floor spot the user tapped.", {
            "kind": choice(["toilet", "chair", "sofa", "table", "lamp", "plant", "bed"]), "room": choice(["current", "kitchen", "bathroom"]),
            "position": choice(["here", "there", "left", "right", "front", "back", "window", "door"]),
            "finish": choice(["matte", "gold", "chrome", "wood"]), "color": {"type": "string", "description": "CSS hex color such as #efdfc0"}}, ["kind", "room", "position", "finish", "color"]),
        tool("edit_furniture", "Modify the most recently placed object: move to the selected floor spot or a side, resize, recolor, remove, or face it. Undo restores the previous scene edit.", {
            "action": choice(["left", "right", "there", "bigger", "smaller", "gold", "remove", "focus", "undo"])}, ["action"]),
        tool("read_room", "Read the actual current room, cleanup stage, and placed concept objects before answering what is present.", {}, []),
    ]
    instructions = (
        "You are Brace's room companion, a spatial design guide inside an illustrated home. You are NOT the PDF or insurance explainer. "
        "Speak naturally in one short sentence, execute the user's command with a tool first, and describe only the returned result. "
        "Start by calling read_room. Offer: Let's clean this place up. Clean first removes contents but leaves fire damage; a second clean or 'more' restores the empty surfaces. "
        "Furniture is instant parametric 3D concept geometry from seven supported object types, not a live text-to-3D generation or a matched product. "
        "Customize material/color and placement. A golden toilet is kind=toilet finish=gold room=bathroom. Sofa/couch are the same. "
        "If asked for an unsupported object, say which supported object is closest; do not pretend it was created. "
        "For 'look left/right/up/down', use look. For 'take me there' after placing something, focus the last object. "
        "Do not say a model was placed until the tool says it was. Placement and scale are illustrative, not measured. "
        "Never imply actual cleanup, safe re-entry, physical construction or insurance work occurred. The burned and restored panoramas are AI-generated scenarios. "
        "Phone motion must be enabled by the user tapping Enable motion; you cannot grant browser permission. "
        "For cost/PDF questions, direct the user back to Talk with Brace in the owner report."
    )
    return {"session": {"type": "realtime", "model": voice.MODEL, "instructions": instructions,
        "audio": {"input": {"turn_detection": {"type": "semantic_vad"}, "noise_reduction": {"type": "near_field"}, "transcription": {"model": "gpt-4o-mini-transcribe"}},
                  "output": {"voice": os.environ.get("BRACE_ROOM_VOICE") or ("cedar" if voice.VOICE != "cedar" else "marin")}},
        "tools": tools, "tool_choice": "auto"}}

@router.post("/voice")
def room_voice():
    if not voice.ready():
        raise HTTPException(503, "The room voice is not configured. The text commands still work.")
    try:
        return voice.mint(session())
    except voice.VoiceError as exc:
        raise HTTPException(502, str(exc))
