"""
MySQL-backed GIS layer.

Real spatial lookups (point-in-polygon against district boundaries) rather
than just carrying a bare lat/lon around — this is the seam the brief calls
for under "GIS tools" and "urban planning" use cases: once real Survey-of-
India / OSM district polygons are loaded into the `districts` table (see
`sql/districts.sql`), advisories can be scoped to an actual administrative
unit ("Purba Bardhaman district, West Bengal") instead of a raw coordinate,
and could later be used to draw hazard polygons on a map.

Requires MySQL 8.0+ (or MariaDB 10.5+) — that's the version where
ST_Contains/ST_GeomFromText spatial functions are solid. To keep coordinate
handling simple and avoid MySQL 8's strict SRID axis-order rules (EPSG:4326
is defined as lat/lon order, which trips people up), the districts table
uses an SRID-less (SRID 0) plain-Cartesian geometry column with (lon, lat)
ordering throughout — fine for the bounding-box-sized polygons used here.

Degrades gracefully: if MySQL isn't reachable or `aiomysql` isn't installed,
`lookup_district` simply returns None and the rest of the app carries on
using plain coordinates — nothing else depends on this being available.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("gis")

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "weathergpt")

_pool = None
_unavailable = False


async def _get_pool():
    global _pool, _unavailable
    if _unavailable:
        return None
    if _pool is not None:
        return _pool
    try:
        import aiomysql
    except ImportError:
        logger.info("GIS: aiomysql not installed, district lookup disabled")
        _unavailable = True
        return None
    try:
        _pool = await aiomysql.create_pool(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            db=MYSQL_DB,
            minsize=1,
            maxsize=5,
            connect_timeout=5,
            autocommit=True,
        )
        return _pool
    except Exception as exc:
        logger.info("GIS: could not connect to MySQL (%s) — district lookup disabled", exc)
        _unavailable = True
        return None


async def lookup_district(lat: float, lon: float) -> dict | None:
    """Return {"state": ..., "district": ...} for the district polygon
    containing (lat, lon), or None if unavailable / no match.
    """
    pool = await _get_pool()
    if pool is None:
        return None
    query = """
        SELECT state, district
        FROM districts
        WHERE ST_Contains(geom, ST_GeomFromText(%s))
        LIMIT 1;
    """
    point_wkt = f"POINT({lon} {lat})"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (point_wkt,))
                row = await cur.fetchone()
        if row:
            return {"state": row[0], "district": row[1]}
        return None
    except Exception as exc:
        logger.info("GIS: lookup failed (%s)", exc)
        return None


async def gis_available() -> bool:
    return await _get_pool() is not None
