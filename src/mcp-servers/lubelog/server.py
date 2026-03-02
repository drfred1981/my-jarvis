"""MCP Server for LubeLogger (vehicle maintenance tracker).

Provides tools to interact with LubeLogger via its REST API:
- List vehicles and their details
- Track odometer readings
- Log service records, repairs, upgrades
- Track fuel consumption
- View reminders and maintenance plans

Requires env vars:
  LUBELOG_URL=http://lubelog.local:8080
  LUBELOG_API_KEY=your-api-key
"""

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("lubelog")

LUBELOG_URL = os.getenv("LUBELOG_URL", "").rstrip("/")
LUBELOG_API_KEY = os.getenv("LUBELOG_API_KEY", "")


def _headers() -> dict:
    return {
        "x-api-key": LUBELOG_API_KEY,
        "Content-Type": "application/json",
        "culture-invariant": "true",
    }


def _client() -> httpx.Client:
    return httpx.Client(base_url=LUBELOG_URL, headers=_headers(), timeout=30)


@mcp.tool()
def list_vehicles() -> str:
    """List all vehicles tracked in LubeLogger."""
    with _client() as client:
        resp = client.get("/api/vehicles")
        resp.raise_for_status()
        vehicles = resp.json()

    result = []
    for v in vehicles:
        result.append({
            "id": v.get("id"),
            "year": v.get("year"),
            "make": v.get("make"),
            "model": v.get("model"),
            "license_plate": v.get("licensePlate", ""),
        })
    return json.dumps({"count": len(result), "vehicles": result}, indent=2)


@mcp.tool()
def get_vehicle_info(vehicle_id: int) -> str:
    """Get detailed info and statistics for a vehicle.

    Args:
        vehicle_id: Vehicle ID (from list_vehicles)
    """
    with _client() as client:
        resp = client.get("/api/vehicle/info", params={"vehicleId": vehicle_id})
        resp.raise_for_status()
        info = resp.json()

    return json.dumps(info, indent=2, default=str)


@mcp.tool()
def get_reminders(vehicle_id: int) -> str:
    """Get maintenance reminders for a vehicle with urgency levels.

    Args:
        vehicle_id: Vehicle ID
    """
    with _client() as client:
        resp = client.get("/api/vehicle/reminders", params={"vehicleId": vehicle_id})
        resp.raise_for_status()
        reminders = resp.json()

    result = []
    for r in reminders:
        result.append({
            "description": r.get("description", ""),
            "urgency": r.get("urgency", ""),
            "metric": r.get("metric", ""),
            "due_date": r.get("dueDate"),
            "due_odometer": r.get("dueOdometer"),
        })

    # Sort by urgency: Very Urgent > Urgent > Past Due > Not Urgent
    urgency_order = {"Very Urgent": 0, "Past Due": 1, "Urgent": 2, "Not Urgent": 3}
    result.sort(key=lambda x: urgency_order.get(x["urgency"], 99))

    return json.dumps({
        "vehicle_id": vehicle_id,
        "count": len(result),
        "reminders": result,
    }, indent=2)


@mcp.tool()
def get_odometer(vehicle_id: int) -> str:
    """Get the latest odometer reading for a vehicle.

    Args:
        vehicle_id: Vehicle ID
    """
    with _client() as client:
        resp = client.get("/api/vehicle/odometerrecords/latest", params={"vehicleId": vehicle_id})
        resp.raise_for_status()
        record = resp.json()

    return json.dumps(record, indent=2, default=str)


@mcp.tool()
def add_odometer(vehicle_id: int, odometer: int, date: str, notes: str = "") -> str:
    """Add an odometer reading for a vehicle.

    Args:
        vehicle_id: Vehicle ID
        odometer: Current odometer value (km or miles)
        date: Date of reading (YYYY-MM-DD)
        notes: Optional notes
    """
    payload = {
        "vehicleId": vehicle_id,
        "date": date,
        "odometer": odometer,
        "notes": notes,
    }
    with _client() as client:
        resp = client.post("/api/vehicle/odometerrecords/add", json=payload)
        resp.raise_for_status()

    return json.dumps({"status": "ok", "vehicle_id": vehicle_id, "odometer": odometer}, indent=2)


@mcp.tool()
def get_service_records(vehicle_id: int) -> str:
    """Get service/maintenance records for a vehicle.

    Args:
        vehicle_id: Vehicle ID
    """
    with _client() as client:
        resp = client.get("/api/vehicle/servicerecords", params={"vehicleId": vehicle_id})
        resp.raise_for_status()
        records = resp.json()

    result = []
    for r in records:
        result.append({
            "id": r.get("id"),
            "date": r.get("date"),
            "description": r.get("description", ""),
            "cost": r.get("cost", 0),
            "odometer": r.get("odometer", 0),
            "notes": r.get("notes", ""),
            "tags": r.get("tags", []),
        })
    return json.dumps({"vehicle_id": vehicle_id, "count": len(result), "records": result}, indent=2)


@mcp.tool()
def add_service_record(vehicle_id: int, date: str, description: str, cost: float = 0, odometer: int = 0, notes: str = "", tags: str = "") -> str:
    """Add a service/maintenance record.

    Args:
        vehicle_id: Vehicle ID
        date: Service date (YYYY-MM-DD)
        description: What was done
        cost: Service cost
        odometer: Odometer at time of service
        notes: Additional notes
        tags: Comma-separated tags
    """
    payload = {
        "vehicleId": vehicle_id,
        "date": date,
        "description": description,
        "cost": cost,
        "odometer": odometer,
        "notes": notes,
        "tags": tags,
    }
    with _client() as client:
        resp = client.post("/api/vehicle/servicerecords/add", json=payload)
        resp.raise_for_status()

    return json.dumps({"status": "ok", "vehicle_id": vehicle_id, "description": description}, indent=2)


@mcp.tool()
def get_fuel_records(vehicle_id: int) -> str:
    """Get fuel/gas records for a vehicle.

    Args:
        vehicle_id: Vehicle ID
    """
    with _client() as client:
        resp = client.get("/api/vehicle/gasrecords", params={"vehicleId": vehicle_id})
        resp.raise_for_status()
        records = resp.json()

    result = []
    for r in records:
        result.append({
            "id": r.get("id"),
            "date": r.get("date"),
            "odometer": r.get("odometer", 0),
            "fuel_consumed": r.get("gallons", r.get("fuelConsumed", 0)),
            "cost": r.get("cost", 0),
            "is_full_tank": r.get("isFillToFull", False),
            "notes": r.get("notes", ""),
        })
    return json.dumps({"vehicle_id": vehicle_id, "count": len(result), "records": result}, indent=2)


@mcp.tool()
def add_fuel_record(vehicle_id: int, date: str, odometer: int, fuel_consumed: float, cost: float, is_full_tank: bool = True, notes: str = "") -> str:
    """Add a fuel/gas record.

    Args:
        vehicle_id: Vehicle ID
        date: Fill-up date (YYYY-MM-DD)
        odometer: Odometer at fill-up
        fuel_consumed: Liters or gallons filled
        cost: Total cost
        is_full_tank: Was this a full fill-up (for consumption calculation)
        notes: Optional notes
    """
    payload = {
        "vehicleId": vehicle_id,
        "date": date,
        "odometer": odometer,
        "gallons": fuel_consumed,
        "cost": cost,
        "isFillToFull": is_full_tank,
        "notes": notes,
    }
    with _client() as client:
        resp = client.post("/api/vehicle/gasrecords/add", json=payload)
        resp.raise_for_status()

    return json.dumps({"status": "ok", "vehicle_id": vehicle_id, "cost": cost}, indent=2)


@mcp.tool()
def get_repair_records(vehicle_id: int) -> str:
    """Get repair records for a vehicle.

    Args:
        vehicle_id: Vehicle ID
    """
    with _client() as client:
        resp = client.get("/api/vehicle/repairrecords", params={"vehicleId": vehicle_id})
        resp.raise_for_status()
        records = resp.json()

    result = []
    for r in records:
        result.append({
            "id": r.get("id"),
            "date": r.get("date"),
            "description": r.get("description", ""),
            "cost": r.get("cost", 0),
            "odometer": r.get("odometer", 0),
            "notes": r.get("notes", ""),
            "tags": r.get("tags", []),
        })
    return json.dumps({"vehicle_id": vehicle_id, "count": len(result), "records": result}, indent=2)


@mcp.tool()
def get_plans() -> str:
    """Get all maintenance plans/schedules."""
    with _client() as client:
        resp = client.get("/api/plans")
        resp.raise_for_status()
        plans = resp.json()

    return json.dumps({"count": len(plans), "plans": plans}, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
