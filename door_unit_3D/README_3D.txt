DND_E26_WallMount — 3D Blueprint

Files:
- DND_E26_WallMount.scad  (OpenSCAD parametric model; export STL from OpenSCAD)
- DND_E26_DrillTemplate.dxf (placeholder; generate real DXF from .scad by uncommenting section)
- README_3D.txt

Printing Tips (FDM):
- Material: PETG (recommended for heat) or PLA
- Layer height: 0.2 mm
- Perimeters: 3–4
- Top/Bottom: 5–7 layers
- Infill: 20–30%
- Supports: Not required
- Orientation: Backplate flat on bed

Fit Notes:
- Socket cup ID = socket_outer_d + cup_clearance (defaults: 48 + 0.8 = 48.8 mm).
  If your E26 socket is tighter/looser, tweak values and re-export.
- Electronics box sized for ESP32 DevKit and typical 1ch relay (≈52×26×19 mm).

Wiring Notes:
- Route hot (AC) through relay COM→NO (light is normally OFF).
- Neutral direct to bulb. Earth ground as per local code.
- Keep mains wiring isolated from low voltage electronics.

Export STL:
1) Install OpenSCAD (openscad.org)
2) Open DND_E26_WallMount.scad
3) Press F6 (Render) → File → Export → STL

Drill Template:
- In the .scad, scroll to "DRILL TEMPLATE" and uncomment the block, render, and export DXF.
