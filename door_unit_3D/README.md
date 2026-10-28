# DND door wall mount prototype

## Files and status

- `DND_E26_WallMount.scad`: parametric OpenSCAD source. Render and export an STL
  before printing. No rendered/printed fit test is established by the software
  audit.
- `DND_E26_DrillTemplate.dxf`: placeholder, not a usable mounting template.
  Generate the real 2D drawing from the source and verify scale/hole locations.
- `README.md`: these notes. No `README_3D.txt` is included.

No desk-unit enclosure model is provided. The door prototype has not been
validated for socket fit, relay fit, temperature, strain relief, insulation,
clearance, or electrical enclosure suitability.

## CAD dimensions and trial print

The source's default socket cup ID is 48.8 mm (48 mm socket diameter plus 0.8 mm
clearance). Verify those dimensions against the actual socket. The electronics
box targets an ESP32 DevKit and a small single-channel relay; board sizes vary.

The original trial settings were 0.2 mm layers, 3–4 perimeters, 20–30% infill,
backplate flat on the bed. These are starting parameters, not validated print
instructions. Determine supports, material, wall strength, and heat suitability
from the actual model, printer, bulb, and enclosure conditions.

## Export

1. Open `DND_E26_WallMount.scad` in OpenSCAD.
2. Render with F6 and inspect for geometry warnings/intersections.
3. Export an STL for a trial fit.
4. For a drill template, select the source's DRILL TEMPLATE projection, render,
   and export DXF. Check that the 3D assembly is excluded, then verify 1:1 scale
   before drilling.

## Wiring context

The intended relay COM→NO connection switches the hot leg so the light is
normally off; neutral bypasses the relay. Earth and mains requirements depend
on the actual installation. Keep mains and low-voltage wiring isolated and
provide appropriate strain relief. A successful print or software test does
not establish electrical or thermal safety.
