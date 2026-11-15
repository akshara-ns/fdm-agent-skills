"""Independent check through the real HW5 MCP server: call the new HW5 tool `check_deviated_part` over stdio
with the bracket case (two-sided features and the solid arm only, which is all that tool models) and save the
request and response to mcp_check.json."""
import asyncio
import json
import sys

from mcp import Client, StdioServerParameters

ARGS = {
    "features": [
        # range limits 4.0-6.5 mm written as midpoint +- half-width; worst (smallest) readings
        {"name": "left (load) hole diameter", "role": "fit", "nominal_mm": 5.25, "measured_mm": 4.86, "tolerance_mm": 1.25},
        {"name": "right (clamped) hole diameter", "role": "fit", "nominal_mm": 5.25, "measured_mm": 5.04, "tolerance_mm": 1.25},
        {"name": "hole spacing", "role": "fit", "nominal_mm": 40.0, "measured_mm": 40.25, "tolerance_mm": 1.0},
    ],
    "beam": {"material": "PLA", "length_mm": 37, "width_mm": 30.04, "nominal_thickness_mm": 8.0,
             "measured_thickness_mm": 7.58, "load_N": 100, "orientation": "flat", "target_safety_factor": 1.5},
    "repaired_in_load_path": True,
    "reprint_time_h": 0.8,
    "reprint_filament_g": 13.2,
}


async def main(out="mcp_check.json"):
    params = StdioServerParameters(command=sys.executable, args=["-m", "fdm_mcp.server"])
    async with Client(params) as c:
        tools = [t.name for t in (await c.list_tools()).tools]
        r = await c.call_tool("check_deviated_part", ARGS)
    rec = {"tools_listed": tools, "request": {"tool": "check_deviated_part", "arguments": ARGS},
           "is_error": r.is_error, "structured": r.structured_content}
    with open(out, "w") as f:
        json.dump(rec, f, indent=2, ensure_ascii=False)
    return rec


if __name__ == "__main__":
    rec = asyncio.run(main())
    s = rec["structured"]
    print("tools listed:", ", ".join(rec["tools_listed"]))
    print("decision:", s["decision"], "| verdict:", s["verdict"])
    print(s["summary"])
    for k, v in s["results"].items():
        print(f"  {v['label']}: {v['value']} {v['unit']}")
