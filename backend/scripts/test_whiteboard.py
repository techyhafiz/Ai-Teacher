"""Validate whiteboard tool schemas + validation logic + stage directions
(no API key needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.whiteboard import (  # noqa: E402
    TOOL_DEFINITIONS, validate_tool_call,
)
from app.services.capture import (  # noqa: E402
    _script_with_stage_directions, _build_timeline, _levenshtein_ratio,
    _normalize_for_compare,
)

# --- schema sanity ---
names = [t["name"] for t in TOOL_DEFINITIONS]
expected = {"write_text", "draw_equation", "plot_graph", "draw_diagram",
            "draw_timeline", "write_code", "draw_map", "draw_flowchart",
            "show_table"}
assert set(names) == expected, f"tool set mismatch: {names}"
print("tools:", names)

# --- validation ---
ok = validate_tool_call("write_text", {"text": "hello"})
assert ok["ok"]
bad = validate_tool_call("write_text", {})
assert not bad["ok"]
bad2 = validate_tool_call("nope", {})
assert not bad2["ok"]
ok_graph = validate_tool_call("plot_graph", {"functions": [{"fn": "2*x+1"}]})
assert ok_graph["ok"]
bad_graph = validate_tool_call("plot_graph", {"functions": []})
assert not bad_graph["ok"]
ok_flow = validate_tool_call("draw_flowchart", {
    "nodes": [{"id": "a", "label": "Start", "x": 50, "y": 10}],
    "edges": [{"from": "a", "to": "b"}]})
assert not ok_flow["ok"], "edge to unknown node should fail"
ok_map = validate_tool_call("draw_map", {"region": "india",
                                         "markers": [{"name": "Delhi", "x": 40, "y": 30}]})
assert ok_map["ok"]
print("validation: all assertions passed")

# --- stage directions ---
script = ("Force is a push or a pull. Pressure is force per unit area. "
          "Sharp knives cut better.")
visuals = [{"tool": "draw_equation", "args": {"latex": "P = F / A"},
            "after_sentence": 2}]
sd = _script_with_stage_directions(script, visuals)
assert "[VISUAL: draw_equation]" in sd
assert sd.index("unit area.") < sd.index("[VISUAL:")
print("\nscript with directions:\n ", sd)

# --- timeline ---
tl = _build_timeline(visuals, script, "", 30.0)
assert len(tl) == 1
assert 0 <= tl[0]["t"] <= 30
assert tl[0]["valid"] is True
print("timeline:", tl)

# --- verbatim score ---
a = _normalize_for_compare("Force is a push or a pull on an object")
b = _normalize_for_compare("Force is a push or pull on an object")
score = _levenshtein_ratio(a, b)
assert score > 0.85, f"similar sentences should score high: {score}"
diff = _levenshtein_ratio(_normalize_for_compare("cat"), _normalize_for_compare("dog"))
assert diff < 0.5
print(f"verbatim score: similar={score:.3f}, different={diff:.3f}")

print("\nWHITEBOARD + CAPTURE LOGIC: ALL PASSED")
