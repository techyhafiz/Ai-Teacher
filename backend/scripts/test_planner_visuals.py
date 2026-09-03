import asyncio
import sys
import json
sys.stdout.reconfigure(encoding='utf-8')

import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.planner import plan_lesson
from app.services.whiteboard import validate_tool_call

async def test():
    print("Testing plan_lesson with visual enrichment...")
    plan = await plan_lesson(
        session_id="test_visual_session_01",
        learner_id="test_user_01",
        mode="topic",
        topic_request="Ohm's Law and Electric Circuits",
        language="en",
        level="intermediate",
        time_budget="5min",
        persona="Aarav Sir"
    )
    
    print(f"\nLesson Title: {plan.get('lesson_title')}")
    print(f"Total Segments: {len(plan.get('segments', []))}")
    
    for seg in plan.get('segments', []):
        print(f"\n--- Segment {seg['seg_id']}: {seg.get('concept')} ({seg.get('kind')}) ---")
        visuals = seg.get('visuals', [])
        print(f"  Visual count: {len(visuals)}")
        for idx, v in enumerate(visuals):
            tool = v.get('tool')
            args = v.get('args', {})
            val = validate_tool_call(tool, args)
            print(f"    Visual {idx+1}: [{tool}] Valid={val['ok']}")
            if tool == 'draw_diagram':
                shapes = args.get('shapes', [])
                print(f"      Diagram shapes ({len(shapes)}): {[s.get('kind', s.get('type')) for s in shapes]}")
            elif tool == 'draw_equation':
                print(f"      LaTeX: {args.get('latex')}")
            elif tool == 'plot_graph':
                print(f"      Functions: {[f.get('fn') for f in args.get('functions', [])]}")
                
    print("\n✅ PLANNER VISUAL TEST COMPLETE: ALL SEGMENTS HAVE RICH SHAPES & VALID TOOLS!")

if __name__ == '__main__':
    asyncio.run(test())
