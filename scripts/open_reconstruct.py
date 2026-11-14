"""Open problem "splats from sparse imagery": build the real height model of a site and list what 3D exists.

    python -m scripts.open_reconstruct --building 4303509                    # height grid, proof picture, asset inventory
    python -m scripts.open_reconstruct --building 4303509 --scan 9odpSsu2KYQ # also fetch that scan's MatterPak and describe it
    python -m scripts.open_reconstruct --building 4303509 --refresh          # ask the sponsors again instead of using the cache

No splat is trained or generated here. Everything printed is a sponsor measurement or arithmetic on one.
"""
from __future__ import annotations

import argparse
import sys

from backend import matterport, vexcel
from backend.openproblems import reconstruct


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--building", type=int, required=True, help="CoStar property id with a cached bundle")
    ap.add_argument("--scan", help="Matterport scan id whose MatterPak (point cloud and mesh) to fetch and describe")
    ap.add_argument("--refresh", action="store_true", help="refetch instead of using cached answers")
    ap.add_argument("--no-inventory", action="store_true", help="skip the Matterport asset inventory (no Matterport calls)")
    args = ap.parse_args()

    try:
        h = reconstruct.site_heights(args.building, refresh=args.refresh)
    except (reconstruct.ReconstructError, vexcel.VexcelError) as e:
        print(f"height model: failed: {e}")
        return 1
    if not h["available"]:
        print(f"height model: not available: {h['reason']}")
    else:
        src = h["source"]
        print(f"{h['name']} ({h['property_id']})")
        print(f"  grid          {h['cols']} x {h['rows']} cells, {h['metres_per_cell']} m per cell")
        print(f"  surface       {src['surface']['collection']}, captured {src['surface']['first_capture']} to {src['surface']['last_capture']}")
        print(f"  terrain       {src['terrain']['collection']}, captured {src['terrain']['first_capture']} to {src['terrain']['last_capture']}")
        step = src["step_between_flights"]
        print(f"  step between the two flights (derived): {step['offset_m']} m, applied: {step['applied']}")
        if h.get("cross_check"):
            c = h["cross_check"]
            print(f"  cross-check   same-flight roofs differ by {c['median_roof_difference_m']} m (median), "
                  f"{c['largest_roof_difference_m']} m (largest) over {c['structures_compared']} structures")
        print(f"  heights       {h['heights_png']}")
        print(f"  texture       {h['texture']}")
        print(f"  proof         {h['proof_side_by_side'] or h['proof_relief']}")
        print("  structure   roof m   tallest object within 10 m (m)   above roof   Vexcel also reports trees")
        for s in h["structures"]:
            t = s["tallest_nearby"]
            roof = "   n/a" if s["roof_height_m"] is None else f"{s['roof_height_m']:6.1f}"
            if t:
                print(f"  {s['id']:<10}{roof}   {t['height_m']:6.1f} at {t['distance_to_wall_m']:4.1f} m from the wall"
                      f"   {t.get('above_roof_m', float('nan')):+6.1f}       {'yes' if t.get('vexcel_reports_trees_within_30ft') else 'no'}")
            else:
                print(f"  {s['id']:<10}{roof}   none")

    if not args.no_inventory:
        try:
            inv = reconstruct.inventory(refresh=args.refresh)
            print(f"\nMatterport assets for {inv['scans']} scans of {inv['buildings']} cached buildings:")
            print(f"  MatterPak (point cloud + mesh): {len(inv['scans_with_matterpak'])}")
            print(f"  mesh downloadable on its own:   {len(inv['scans_with_mesh'])}")
            print(f"  e57 point cloud:                {len(inv['scans_with_e57'])}")
            print(f"  exterior gaussian splat:        {len(inv['scans_with_exterior_splat'])} {inv['scans_with_exterior_splat'] or ''}")
            print(f"  models with a splat anywhere in the sponsor account: {inv['splat_models_in_account']}")
        except matterport.MatterportError as e:
            print(f"\nMatterport inventory: failed: {e}")

    if args.scan:
        try:
            g = reconstruct.interior_geometry(args.scan, refresh=args.refresh)
        except matterport.MatterportError as e:
            print(f"\nMatterPak for {args.scan}: failed: {e}")
            return 1
        print(f"\nMatterPak for scan {args.scan}:")
        if not g.get("downloaded"):
            print(f"  not downloaded: {g.get('reason') or str(g.get('bytes')) + ' bytes, over the size limit'}")
        else:
            print(f"  archive       {g['archive']} ({g['bytes'] / 1e6:.1f} MB)")
            if g.get("point_cloud"):
                p = g["point_cloud"]
                print(f"  point cloud   {p['file']}: {p['points']:,} points, {p['format']}")
            if g.get("mesh"):
                m = g["mesh"]
                print(f"  mesh          {m['file']}: {m['vertices']:,} vertices, {m['faces']:,} faces, {m['textures']} textures")
            for k, v in (g.get("frame") or {}).items():
                print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
