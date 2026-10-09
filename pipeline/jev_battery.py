#!/usr/bin/env python3
"""Typed decision battery for the Jev poster pilot.

Questions are independent forced-choice items about one sheet. Option count
stays at K≤16 so the same battery can run on Visual Jev (LM-head readout).
CLIP's 18-way census is collapsed: animals share one slot; 'none' is explicit.
"""
from __future__ import annotations

from typing import Any

CLIP_ANIMALS = {"shark", "spider", "snake", "wolf_dog", "bird", "insect"}
CLIP_NONE = {"none", "uncertain"}

CREATURE_TYPES = [
    "vampire",
    "werewolf",
    "zombie",
    "ghost",
    "demon",
    "witch",
    "skeleton",
    "alien",
    "giant_monster",
    "masked_killer",
    "clown",
    "doll",
    "animal",
    "none",
]

QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "creature_present",
        "kind": "choice",
        "prompt": (
            "Does this horror movie poster show a creature: a monster, "
            "masked killer, witch, ghost, alien, or attacking animal? "
            "A jack-o'-lantern, a knife without a person, a house, or an ordinary "
            "human face is not a creature. An alien egg, xenomorph, or kaiju counts as yes."
        ),
        "options": ["yes", "no", "uncertain"],
    },
    {
        "id": "creature_type",
        "kind": "choice",
        "prompt": (
            "If a creature is visible on this poster, which taxonomy label fits best? "
            "Use animal for shark, spider, snake, wolf/dog, birds, or insects. "
            "masked_killer requires a visible mask or killer figure, not just a knife. "
            "alien includes the xenomorph, facehugger, or the egg. "
            "Use none if there is no creature — only people, a house, a pumpkin, or a prop."
        ),
        "options": CREATURE_TYPES,
    },
    {
        "id": "medium",
        "kind": "choice",
        "prompt": (
            "Is the artwork hand-painted / illustrated, a photograph of real people, "
            "or a mix of both?"
        ),
        "options": ["painted", "photo", "mixed"],
    },
    {
        "id": "blood",
        "kind": "noul",
        "prompt": (
            "Does this poster show actual blood or a bloodstain? "
            "Orange pumpkin flesh, red type, or a red sky is not blood."
        ),
        "options": ["no", "yes"],
    },
    {
        "id": "lettering",
        "kind": "choice",
        "prompt": (
            "Look at the title lettering, not the scene. Is it ornate / decorative "
            "hand-drawn display type, clean modern sans-serif, or in between?"
        ),
        "options": ["ornate", "clean", "mixed"],
    },
    {
        "id": "title_band",
        "kind": "choice",
        "prompt": (
            "Where is the main title of the film on this sheet? "
            "Top third, bottom third, or no readable title?"
        ),
        "options": ["top", "bottom", "none"],
    },
    {
        "id": "sheet_kind",
        "kind": "choice",
        "prompt": (
            "Is this a designed theatrical one-sheet, a video still / screenshot, "
            "or a logo / title-card with almost no scene?"
        ),
        "options": ["one_sheet", "still", "logo"],
    },
]


def letters_for(n: int) -> list[str]:
    return [chr(ord("A") + i) for i in range(n)]


def render_prompt(q: dict[str, Any]) -> tuple[str, list[str]]:
    opts = list(q["options"])
    labs = letters_for(len(opts))
    lines = [
        "You are a System One decision model. Look at the movie poster image.",
        "Answer with exactly one option letter. No explanation.",
        "",
        q["prompt"],
        "",
    ]
    for lab, opt in zip(labs, opts):
        lines.append(f"{lab}) {opt}")
    lines.append("")
    lines.append("Answer:")
    return "\n".join(lines), labs


def clip_creature_slot(label: str | None) -> str | None:
    if label is None or (isinstance(label, float) and label != label):
        return None
    lab = str(label).strip()
    if lab in CLIP_ANIMALS:
        return "animal"
    if lab in CLIP_NONE:
        return "none" if lab == "none" else None
    if lab in CREATURE_TYPES:
        return lab
    return None


def clip_medium_slot(painted: Any, p_painted: Any) -> str | None:
    try:
        p = float(p_painted)
    except (TypeError, ValueError):
        p = None
    try:
        flag = int(painted)
    except (TypeError, ValueError):
        flag = None
    if p is not None:
        if p >= 0.6:
            return "painted"
        if p <= 0.4:
            return "photo"
        return "mixed"
    if flag == 1:
        return "painted"
    if flag == 0:
        return "photo"
    return None


def clip_lettering_slot(register: str | None) -> str | None:
    if not register or str(register) == "nan":
        return None
    r = str(register).strip().lower()
    if r in {"ornate", "decorative"}:
        return "ornate"
    if r in {"clean", "minimal"}:
        return "clean"
    if r in {"standard"}:
        return "mixed"
    return None


def attr_title_band(text_top: Any, text_h: Any) -> str | None:
    try:
        top = float(text_top)
        h = float(text_h)
    except (TypeError, ValueError):
        return None
    if top < 0 or h <= 0:
        return None
    mid = top + 0.5 * h
    if mid < 0.33:
        return "top"
    if mid > 0.67:
        return "bottom"
    return None


SCALE_QUESTION_IDS = (
    "creature_present",
    "creature_type",
    "medium",
    "blood",
    "title_band",
    "sheet_kind",
)


def questions_by_id(ids: list[str] | None = None) -> list[dict[str, Any]]:
    by = {q["id"]: q for q in QUESTIONS}
    if ids is None:
        return [by[i] for i in SCALE_QUESTION_IDS if i in by]
    out = []
    for i in ids:
        if i not in by:
            raise KeyError(f"unknown question id: {i}")
        out.append(by[i])
    return out


def reconcile_creature(present: str | None, ctype: str | None) -> tuple[str | None, str | None]:
    """Published labels. Type is source of truth except knife→masked_killer.

    yes+none (Smile) → no/none. no+alien (egg) → yes/alien.
    no+masked_killer (Halloween knife) → no/none.
    """
    p = (present or "").strip() or None
    t = (ctype or "").strip() or None
    if t == "none":
        return "no", "none"
    if t == "masked_killer" and p == "no":
        return "no", "none"
    if t and t != "none":
        return "yes", t
    if p == "yes":
        return "yes", t
    if p == "no":
        return "no", "none"
    return p, t
