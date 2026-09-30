"""
Austria provides geojson data with reversed coordinate order. I've never seen this before.
"""

import json
import sys


def swap_point_coordinates(obj):
    """Recursively find Point geometries and swap their first two coordinates."""

    if isinstance(obj, dict):
        # GeoJSON geometry
        if obj.get("type") == "Point" and "coordinates" in obj:
            coords = obj["coordinates"]

            if len(coords) >= 2:
                # Preserve altitude or additional dimensions, if present
                obj["coordinates"] = [coords[1], coords[0]] + coords[2:]

        # Recurse through all dictionary values
        for value in obj.values():
            swap_point_coordinates(value)

    elif isinstance(obj, list):
        for item in obj:
            swap_point_coordinates(item)


def main(input_file, output_file):
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    swap_point_coordinates(data)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Converted GeoJSON written to: {output_file}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python swap_geojson_coords.py input.geojson output.geojson")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])
