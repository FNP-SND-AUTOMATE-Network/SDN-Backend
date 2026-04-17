import re
from typing import Any, Dict, List

from app.core.logging import logger


_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9_.:\-]+$")


def normalize_chassis_id(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"[^a-z0-9]", "", raw)


def _validate_token(value: str, field: str) -> str:
    token = (value or "").strip()
    if not token:
        raise ValueError(f"{field} is required")
    if len(token) > 128:
        raise ValueError(f"{field} is too long")
    if not _ALLOWED_CHARS.match(token):
        raise ValueError(f"{field} contains unsupported characters")
    return token


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def ensure_binding_table(prisma) -> None:
    """Create LLDP binding table lazily (idempotent)."""
    ddl = """
    CREATE TABLE IF NOT EXISTS "TopologyLldpBinding" (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        chassis_id_norm TEXT UNIQUE NOT NULL,
        node_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    await prisma.query_raw(ddl)


async def list_lldp_bindings(prisma) -> List[Dict[str, Any]]:
    await ensure_binding_table(prisma)
    rows = await prisma.query_raw(
        'SELECT id::text AS id, chassis_id_norm, node_id, created_at, updated_at FROM "TopologyLldpBinding" ORDER BY created_at DESC'
    )
    return rows or []


async def get_lldp_binding_map(prisma) -> Dict[str, str]:
    rows = await list_lldp_bindings(prisma)
    out: Dict[str, str] = {}
    for r in rows:
        key = (r.get("chassis_id_norm") or "").strip().lower()
        node_id = (r.get("node_id") or "").strip()
        if key and node_id:
            out[key] = node_id
    return out


async def upsert_lldp_binding(prisma, chassis_id: str, node_id: str) -> Dict[str, Any]:
    await ensure_binding_table(prisma)

    chassis_token = _validate_token(chassis_id, "chassis_id")
    node_token = _validate_token(node_id, "node_id")

    # Ensure node_id exists in inventory to avoid broken bindings.
    device = await prisma.devicenetwork.find_unique(where={"node_id": node_token})
    if not device:
        raise ValueError(f"node_id '{node_token}' not found in DeviceNetwork")

    norm = normalize_chassis_id(chassis_token)
    if not norm:
        raise ValueError("chassis_id is invalid")

    sql = (
        'INSERT INTO "TopologyLldpBinding" (chassis_id_norm, node_id, updated_at) '
        f'VALUES ({_sql_string(norm)}, {_sql_string(node_token)}, NOW()) '
        'ON CONFLICT (chassis_id_norm) DO UPDATE '
        'SET node_id = EXCLUDED.node_id, updated_at = NOW() '
        'RETURNING id::text AS id, chassis_id_norm, node_id, created_at, updated_at'
    )
    rows = await prisma.query_raw(sql)
    if not rows:
        raise ValueError("failed to create binding")

    logger.info(f"[LLDP-BIND] Upsert binding chassis={norm} -> node_id={node_token}")
    return rows[0]


async def delete_lldp_binding(prisma, chassis_id: str) -> Dict[str, Any]:
    await ensure_binding_table(prisma)

    chassis_token = _validate_token(chassis_id, "chassis_id")
    norm = normalize_chassis_id(chassis_token)
    if not norm:
        raise ValueError("chassis_id is invalid")

    sql = (
        'DELETE FROM "TopologyLldpBinding" '
        f'WHERE chassis_id_norm = {_sql_string(norm)} '
        'RETURNING id::text AS id, chassis_id_norm, node_id, created_at, updated_at'
    )
    rows = await prisma.query_raw(sql)
    if not rows:
        raise ValueError(f"binding not found for chassis_id '{norm}'")

    logger.info(f"[LLDP-BIND] Deleted binding chassis={norm}")
    return rows[0]
