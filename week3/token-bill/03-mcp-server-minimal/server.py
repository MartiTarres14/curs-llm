# © 2026 Marc Alier i Forment (Universitat Politècnica de Catalunya) · https://wasabi.essi.upc.edu/ludo · https://lamb-project.org
# BSC Agents Course — Transformers, LLMs, RAG and Agents: From Theory to Production
# Licensed under Creative Commons BY-NC-SA 4.0 — reuse must credit the author, no commercial use, derivatives under the same license.

# =============================================================================================================== #
# Universitat Politècnica de Catalunya (UPC)                                                                      #
# =============================================================================================================== #

"""
🔌 A minimal MCP server — one tool, one resource.

MCP (the Model Context Protocol) is a standard way to plug capabilities into an
LLM-driven app without hand-wiring each one. A server advertises its capabilities
over JSON-RPC; a client (your agent) discovers and calls them. The three primitives:

  - tools     : actions the model can invoke      (here: get_robot_spec)
  - resources : data the model can read           (here: acme://company)
  - prompts   : reusable prompt templates         (omitted — keep it minimal)

When a client connects, the server hands it a REGISTRY: each tool's name,
description, and JSON schema. That registry is loaded into the model's context at
the head of the session — true and useful to know, and the exact structure a later
chapter's cost model takes apart.

Run it directly to serve over stdio:  uv run server.py
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("acme-robotics")

# canned data — offline, so the demo needs no network
_SPECS = {
    "pallet pup": "Pallet Pup: top speed 2.4 m/s, 9 h battery, carries up to 600 kg, runs PupOS.",
    "shelf cat":  "Shelf Cat: top speed 0.9 m/s, reaches 8 m racking, shares the PupOS platform.",
}


@mcp.tool()
def get_robot_spec(model: str) -> str:
    """Return the spec sheet for an Acme Robotics model (e.g. 'Pallet Pup', 'Shelf Cat')."""
    return _SPECS.get(model.strip().lower(), f"No spec on file for {model!r}.")


@mcp.tool()
def get_warehouse_map(zone: str) -> str:
    """Return the floor map of a warehouse zone as ASCII art, including rack rows,
    charging docks, forbidden aisles and the current positions of every robot
    assigned to that zone (e.g. 'zone-A', 'zone-B', 'cold-storage')."""
    return f"[map of {zone}: 12 rack rows, 3 charging docks, aisle 7 closed]"


@mcp.tool()
def open_support_ticket(summary: str, severity: str) -> str:
    """Open a ticket with Acme Robotics customer support. Provide a one-line
    summary of the problem and a severity level ('low', 'normal', 'high',
    'critical'). Returns the ticket number and the expected response time."""
    return f"Ticket ACME-4711 opened ({severity}): {summary}. Response within 4 h."


@mcp.tool()
def get_battery_status(robot_id: str) -> str:
    """Return the live battery telemetry for one robot: charge percentage,
    charge cycles used, estimated remaining runtime in hours, and whether the
    robot is currently docked at a charging station."""
    return f"{robot_id}: 84% charge, 212 cycles, 7.6 h remaining, not docked."


@mcp.tool()
def schedule_maintenance(robot_id: str, date: str) -> str:
    """Book a preventive-maintenance slot for a robot at the nearest Acme
    service point. Date must be ISO format (YYYY-MM-DD). Returns the confirmed
    slot and the service point address."""
    return f"{robot_id} booked on {date}, 09:00, service point Girona-Nord."


@mcp.tool()
def list_firmware_updates(product_line: str) -> str:
    """List the firmware updates available for a product line ('Pallet Pup' or
    'Shelf Cat'): version numbers, release dates, changelog highlights and
    whether each update is mandatory for warranty coverage."""
    return f"{product_line}: PupOS 3.2 (2026-08-01, mandatory), 3.1.4 (2026-05-12)."


@mcp.resource("acme://company")
def company() -> str:
    """Background facts about Acme Robotics that the model may read."""
    return ("Acme Robotics, founded 2019 in Girona, builds small autonomous warehouse "
            "robots. CEO Berta Comas. Motto: 'small robots, heavy lifting.'")


if __name__ == "__main__":
    mcp.run()  # stdio transport (JSON-RPC over stdin/stdout)
