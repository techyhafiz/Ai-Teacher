"""Whiteboard tool vocabulary — the schema the LLM writes visuals against.

The performance-capture Live session is given these tools; each call is
timestamped alongside the audio and replayed deterministically in the
browser's classroom canvas.

9 code-drawn primitives (subject-aware):
  write_text      — headings, bullet points, plain annotations
  draw_equation   — LaTeX (rendered by KaTeX in the browser)
  plot_graph      — function plots / data points with axes
  draw_diagram    — schematic primitives: boxes, arrows, vectors, circuits
  draw_timeline   — history: eras, events on a horizontal band
  write_code      — syntax-highlighted code blocks (programming)
  draw_map        — simplified world / India outline via embedded path data
  draw_flowchart  — process/execution-flow boxes and arrows
  show_table      — structured tabular data
  draw_concept_card — titled card with bulleted key points (definitions/summaries)
  show_image      — backend-generated slide image, layered over the board (optional)
"""
from __future__ import annotations

import json
from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "write_text",
        "description": "Write text on the whiteboard. Use for titles, bullet lists, key terms, definitions, labels. Chalk-colored text.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "The text content. Use '\\n' for line breaks; lines starting with '- ' or '* ' render as bullets."},
                "title": {"type": "string",
                          "description": "Optional short heading for this text block."},
                "position": {"type": "string", "enum": ["center", "left", "right", "top", "bottom"],
                             "description": "Where to place the block (default center)."},
                "chalk": {"type": "string", "enum": ["white", "yellow", "blue", "pink", "green"],
                          "description": "Chalk color (default white)."},
                "append": {"type": "boolean",
                            "description": "If true, add to existing board content instead of replacing it (default false)."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "draw_equation",
        "description": "Write a mathematical equation or formula in LaTeX on the whiteboard (KaTeX).",
        "parameters": {
            "type": "object",
            "properties": {
                "latex": {"type": "string",
                          "description": "LaTeX body, e.g. 'V = I \\\\times R' or 'E = mc^2'."},
                "label": {"type": "string",
                          "description": "Optional label above the equation."},
                "position": {"type": "string", "enum": ["center", "left", "right", "top", "bottom"]},
                "chalk": {"type": "string", "enum": ["white", "yellow", "blue", "pink", "green"]},
            },
            "required": ["latex"],
        },
    },
    {
        "name": "plot_graph",
        "description": "Plot a function or data points on axes (math graphs, physics V-I curves, demand curves, sine waves, distributions).",
        "parameters": {
            "type": "object",
            "properties": {
                "functions": {
                    "type": "array",
                    "description": "Functions to plot.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fn": {"type": "string",
                                   "description": "JS math expression in x, e.g. '2*x+1', 'Math.sin(x)', 'x^2' NOT valid - use pow(x,2) or x**2."},
                            "label": {"type": "string", "description": "Legend label."},
                            "color": {"type": "string", "enum": ["yellow", "blue", "pink", "green", "white"]},
                        },
                        "required": ["fn"],
                    },
                },
                "points": {
                    "type": "array",
                    "description": "Scatter points [[x,y],...].",
                    "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                },
                "x_range": {"type": "array", "items": {"type": "number"},
                             "description": "[xmin, xmax] (default [-5, 5])."},
                "y_range": {"type": "array", "items": {"type": "number"},
                             "description": "[ymin, ymax]; auto if omitted."},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "title": {"type": "string"},
                "show_grid": {"type": "boolean"},
            },
            "required": ["functions"],
        },
    },
    {
        "name": "draw_diagram",
        "description": "Draw schematic diagrams from geometric primitives — physics (forces, vectors, circuits, ray optics), geometry, biology structures (cells, labeled blobs), flows. THE go-to for science visuals.",
        "parameters": {
            "type": "object",
            "properties": {
                "shapes": {
                    "type": "array",
                    "description": "Ordered drawing instructions.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string",
                                     "enum": ["rect", "circle", "ellipse", "line", "arrow",
                                              "vector", "arc", "polygon", "label",
                                              "resistor", "battery", "bulb", "switch",
                                              "ammeter", "voltmeter", "wire", "spring",
                                              "pulley", "inclined_plane", "wave",
                                              "lens", "mirror", "ray", "angle", "cell",
                                              "blob", "double_arrow"]},
                            "x": {"type": "number", "description": "Center x in 0..100 board units."},
                            "y": {"type": "number", "description": "Center y in 0..100 board units."},
                            "w": {"type": "number", "description": "Width (units)."},
                            "h": {"type": "number", "description": "Height (units)."},
                            "x2": {"type": "number", "description": "Second point x (lines/arrows/rays)."},
                            "y2": {"type": "number", "description": "Second point y."},
                            "r": {"type": "number", "description": "Radius (circles)."},
                            "points": {"type": "array", "items": {"type": "number"},
                                       "description": "Polygon/ polyline [x1,y1,x2,y2,...]."},
                            "label": {"type": "string", "description": "Text label."},
                            "label_pos": {"type": "string", "enum": ["above", "below", "left", "right"]},
                            "chalk": {"type": "string", "enum": ["white", "yellow", "blue", "pink", "green"]},
                            "dash": {"type": "boolean"},
                            "fill": {"type": "boolean"},
                            "angle_deg": {"type": "number", "description": "Vector direction / rotation."},
                            "voltage": {"type": "number", "description": "Battery voltage label."},
                        },
                        "required": ["kind"],
                    },
                },
                "title": {"type": "string"},
                "clear_first": {"type": "boolean", "description": "Clear board before drawing (default true)."},
            },
            "required": ["shapes"],
        },
    },
    {
        "name": "draw_timeline",
        "description": "Draw a historical timeline: a horizontal band with ordered events.",
        "parameters": {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "year": {"type": "string", "description": "Year/era label, e.g. '1947', 'c.500 BCE'."},
                            "label": {"type": "string", "description": "Short event description."},
                        },
                        "required": ["year", "label"],
                    },
                },
                "title": {"type": "string"},
                "alternating": {"type": "boolean", "description": "Alternate labels above/below the band (default true)."},
            },
            "required": ["events"],
        },
    },
    {
        "name": "write_code",
        "description": "Write a syntax-highlighted code block on the whiteboard (programming lessons: code, output, execution flow).",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The code text (preserve indentation with spaces)."},
                "language": {"type": "string", "enum": ["python", "javascript", "java", "c", "cpp", "sql", "html", "css", "bash"],
                             "description": "Language for highlighting."},
                "caption": {"type": "string", "description": "Optional caption above the block."},
                "output": {"type": "string", "description": "Optional expected output shown below the code."},
            },
            "required": ["code", "language"],
        },
    },
    {
        "name": "draw_map",
        "description": "Draw a simplified outline map (world continents or India states-outline) with marked points and labels — history/geography lessons.",
        "parameters": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "enum": ["world", "india"],
                           "description": "Which base map to draw."},
                "title": {"type": "string"},
                "markers": {
                    "type": "array",
                    "description": "Points to mark on the map.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "x": {"type": "number", "description": "Map coordinate 0..100."},
                            "y": {"type": "number", "description": "Map coordinate 0..100."},
                            "label_pos": {"type": "string", "enum": ["above", "below", "left", "right"]},
                        },
                        "required": ["name", "x", "y"],
                    },
                },
                "regions": {
                    "type": "array",
                    "description": "Named regions to highlight (best-effort).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string",
                                     "description": "Named region to highlight (best-effort)."},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["region"],
        },
    },
    {
        "name": "draw_flowchart",
        "description": "Draw a flowchart / process diagram: boxes connected by arrows (algorithms, biological processes, decision flows, architecture).",
        "parameters": {
            "type": "object",
            "properties": {
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Node id."},
                            "label": {"type": "string"},
                            "shape": {"type": "string", "enum": ["rect", "rounded", "diamond", "stadium", "ellipse"]},
                            "x": {"type": "number", "description": "Position in 0..100 board units."},
                            "y": {"type": "number"},
                            "w": {"type": "number"},
                            "h": {"type": "number"},
                            "chalk": {"type": "string", "enum": ["white", "yellow", "blue", "pink", "green"]},
                        },
                        "required": ["id", "label", "x", "y"],
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "label": {"type": "string"},
                            "dash": {"type": "boolean"},
                        },
                        "required": ["from", "to"],
                    },
                },
                "title": {"type": "string"},
                "direction": {"type": "string", "enum": ["TB", "LR"],
                               "description": "Preferred flow direction (layout is manual by x/y)."},
            },
            "required": ["nodes"],
        },
    },
    {
        "name": "show_table",
        "description": "Show a table on the whiteboard (comparisons, periodic data, unit tables).",
        "parameters": {
            "type": "object",
            "properties": {
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "title": {"type": "string"},
                "highlight_rows": {"type": "array", "items": {"type": "integer"},
                                   "description": "Row indexes to highlight (0-based)."},
            },
            "required": ["headers", "rows"],
        },
    },
    {
        "name": "draw_concept_card",
        "description": "Show a titled chalk card with 2-5 short bullet key points — the go-to for definitions, summaries, and any conceptual topic that is not inherently a diagram/graph/timeline. Always available for on-the-spot topics.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Card heading."},
                "subtitle": {"type": "string", "description": "Optional one-line subtitle under the title."},
                "points": {"type": "array", "items": {"type": "string"},
                           "description": "2-5 short key points, shown as bullets."},
                "chalk": {"type": "string", "enum": ["white", "yellow", "blue", "pink", "green"]},
            },
            "required": ["title"],
        },
    },
    {
        "name": "show_image",
        "description": "Display an illustrative slide image (already generated by the backend) centered on the board with an optional caption. This is layered OVER the code-drawn board as an enhancement. Do NOT invent URLs — the backend injects this tool when a slide has been generated.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Backend-served image URL."},
                "caption": {"type": "string", "description": "Optional caption shown under the image."},
            },
            "required": ["url"],
        },
    },
]


def tools_for_live_api() -> list[dict[str, Any]]:
    """Tool definitions formatted for the Gemini Live API (proto-ish dict).

    ``show_image`` is intentionally withheld from the live model: slide images
    are backend-generated and injected at capture time, so the model should
    never fabricate an image URL. It remains a known/valid tool for the
    injection + validation path below.
    """
    return [
        {
            "functionDeclarations": [t],
        }
        for t in TOOL_DEFINITIONS
        if t["name"] != "show_image"
    ]


def validate_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Lightweight validation/normalization of a whiteboard tool call.

    Returns {ok: bool, errors: [...], args: normalized}.
    """
    errors: list[str] = []
    known = {t["name"] for t in TOOL_DEFINITIONS}
    if name not in known:
        return {"ok": False, "errors": [f"Unknown tool '{name}'"], "args": args}

    if name == "write_text" and not (args.get("text") or "").strip():
        errors.append("write_text: 'text' is required")
    if name == "draw_equation" and not (args.get("latex") or "").strip():
        errors.append("draw_equation: 'latex' is required")
    if name == "plot_graph":
        fns = args.get("functions") or []
        if not fns:
            errors.append("plot_graph: 'functions' required")
        for f in fns:
            if not (f.get("fn") or "").strip():
                errors.append("plot_graph: empty function expression")
    if name == "draw_diagram":
        shapes = args.get("shapes") or []
        if not shapes:
            errors.append("draw_diagram: 'shapes' required")
        for i, s in enumerate(shapes):
            k = s.get("kind") or s.get("type") or s.get("shape")
            if k:
                s["kind"] = k
            else:
                errors.append(f"draw_diagram: shape {i} missing 'kind'")
    if name == "draw_timeline":
        evs = args.get("events") or []
        if not evs:
            errors.append("draw_timeline: 'events' required")
        for i, e in enumerate(evs):
            if not e.get("year"):
                errors.append(f"draw_timeline: event {i} missing 'year'")
    if name == "write_code":
        if not (args.get("code") or "").strip():
            errors.append("write_code: 'code' required")
        if not args.get("language"):
            args["language"] = "python"
    if name == "draw_map" and args.get("region") not in ("world", "india"):
        errors.append("draw_map: 'region' must be world|india")
    if name == "draw_flowchart":
        if not (args.get("nodes") or []):
            errors.append("draw_flowchart: 'nodes' required")
        ids = {n.get("id") for n in (args.get("nodes") or [])}
        for i, e in enumerate(args.get("edges") or []):
            if e.get("from") not in ids or e.get("to") not in ids:
                errors.append(f"draw_flowchart: edge {i} references unknown node")
    if name == "show_table":
        if not (args.get("headers") or []):
            errors.append("show_table: 'headers' required")
        if not (args.get("rows") or []):
            errors.append("show_table: 'rows' required")
    if name == "draw_concept_card" and not (args.get("title") or "").strip():
        errors.append("draw_concept_card: 'title' is required")
    if name == "show_image" and not (args.get("url") or "").strip():
        errors.append("show_image: 'url' is required")

    return {"ok": not errors, "errors": errors, "args": args}
