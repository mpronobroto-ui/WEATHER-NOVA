-- WeatherGPT district GIS layer (MySQL 8.0+ / MariaDB 10.5+ version).
--
-- First create the database (skip if it already exists):
--   CREATE DATABASE weathergpt;
--
-- Then run this file:
--   mysql -u root -p weathergpt < districts.sql
-- or, with the bundled docker-compose MySQL service:
--   docker compose exec -T mysql mysql -u root -proot weathergpt < sql/districts.sql
--
-- NOTE ON THE SAMPLE DATA: the polygons below are simplified rectangular
-- bounding boxes for a handful of Indian districts, good enough to prove out
-- real point-in-polygon lookups end to end. For production, replace this
-- table's contents with actual Survey of India / OSM administrative
-- boundaries (e.g. loaded via ogr2ogr into MySQL, or converted from
-- shapefiles with a GIS tool).
--
-- NOTE ON COORDINATES: this table intentionally does NOT set SRID 4326 on
-- the geometry column. MySQL 8 enforces EPSG:4326's official axis order
-- (latitude, longitude), which is the opposite of the (longitude, latitude)
-- convention used almost everywhere else (GeoJSON, this app's own code,
-- etc.). Using a plain SRID-less (SRID 0) column sidesteps that footgun
-- entirely — all coordinates below and in app/gis.py are consistently
-- (longitude, latitude), matching how the rest of the app works.

CREATE TABLE IF NOT EXISTS districts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    state VARCHAR(100) NOT NULL,
    district VARCHAR(100) NOT NULL,
    geom POLYGON NOT NULL,
    SPATIAL INDEX geom_idx (geom)
) ENGINE=InnoDB;

TRUNCATE TABLE districts;

INSERT INTO districts (state, district, geom) VALUES
('West Bengal', 'North 24 Parganas',
 ST_GeomFromText('POLYGON((88.30 22.40, 89.05 22.40, 89.05 23.00, 88.30 23.00, 88.30 22.40))')),
('West Bengal', 'Kolkata',
 ST_GeomFromText('POLYGON((88.25 22.45, 88.45 22.45, 88.45 22.63, 88.25 22.63, 88.25 22.45))')),
('West Bengal', 'Purba Bardhaman',
 ST_GeomFromText('POLYGON((87.60 23.00, 88.30 23.00, 88.30 23.60, 87.60 23.60, 87.60 23.00))')),
('Maharashtra', 'Mumbai City',
 ST_GeomFromText('POLYGON((72.78 18.89, 72.98 18.89, 72.98 19.08, 72.78 19.08, 72.78 18.89))')),
('Tamil Nadu', 'Chennai',
 ST_GeomFromText('POLYGON((80.15 12.90, 80.35 12.90, 80.35 13.25, 80.15 13.25, 80.15 12.90))')),
('Karnataka', 'Bengaluru Urban',
 ST_GeomFromText('POLYGON((77.35 12.75, 77.75 12.75, 77.75 13.15, 77.35 13.15, 77.35 12.75))')),
('Delhi', 'New Delhi',
 ST_GeomFromText('POLYGON((77.05 28.45, 77.35 28.45, 77.35 28.75, 77.05 28.75, 77.05 28.45))'));
