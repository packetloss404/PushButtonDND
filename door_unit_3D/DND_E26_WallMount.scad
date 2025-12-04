
// DND_E26_WallMount.scad
// Parametric wall-mount stand for an E26 lamp socket + ESP32 + 1ch relay
// Includes wire channel and embossed "DO NOT DISTURB" text.
// Print flat (backplate on bed).
// Author: ChatGPT

//////////////////// PARAMETERS ////////////////////
socket_outer_d = 48;      // E26 keyless socket body OD (mm)
socket_flange_d = 60;     // Socket flange OD (mm) - visual ring
socket_depth    = 40;     // Depth seated (mm)

cup_wall = 3;             // Cup wall thickness (mm)
cup_clearance = 0.8;      // Fit clearance (mm)

backplate_w = 120;        // Plate width (mm)
backplate_h = 160;        // Plate height (mm)
backplate_t = 6;          // Plate thickness (mm)
corner_r     = 8;         // Corner fillet (visual)

hole_d       = 4.2;       // Mount hole for #8/M4 (mm)
hole_offset_y = 50;       // Vertical distance from center to holes
hole_offset_x = 30;       // Horizontal inset from edges

// Right-side electronics box
box_outer_w = 90;
box_outer_h = 65;
box_outer_d = 28;         // Depth off wall
box_wall    = 2.2;
lid_gap     = 0.4;        // Friction-fit lid slot

// Relay approx footprint
relay_w = 54;
relay_d = 20;
relay_h = 26;

// Wire channel
chan_w = 12;
chan_h = 10;
chan_wall = 2;

// Text
label_text = "DO NOT DISTURB";
label_depth = 1.2;
label_size  = 10;
label_font  = "Liberation Sans:style=Bold";

//////////////////// HELPERS ////////////////////
module backplate(){
    // Rounded rectangle plate
    difference(){
        translate([0,0,-backplate_t])
            linear_extrude(height=backplate_t)
                offset(r=corner_r)
                    square([backplate_w-2*corner_r, backplate_h-2*corner_r], center=true);
        // mount holes
        for (y = [-hole_offset_y, hole_offset_y]){
            for (x = [-backplate_w/2 + hole_offset_x, backplate_w/2 - hole_offset_x]){
                translate([x,y,-backplate_t-0.1]) cylinder(d=hole_d, h=backplate_t+2, $fn=32);
            }
        }
    }
}

module socket_cup(){
    cup_id = socket_outer_d + cup_clearance;
    cup_od = cup_id + 2*cup_wall;
    // cup body
    difference(){
        translate([0, backplate_h*0.08, 0])
            cylinder(d=cup_od, h=socket_depth + cup_wall, $fn=128);
        translate([0, backplate_h*0.08, cup_wall])
            cylinder(d=cup_id, h=socket_depth + 2, $fn=128);
    }
    // bezel
    if (socket_flange_d > socket_outer_d){
        translate([0, backplate_h*0.08, -2])
            difference(){
                cylinder(d=socket_flange_d, h=2, $fn=128);
                cylinder(d=cup_od*0.92, h=2.2, $fn=128);
            }
    }
    // pilot holes for socket screws (adjust as needed)
    translate([-20, backplate_h*0.08, socket_depth*0.4]) rotate([90,0,0]) cylinder(d=3, h=10, $fn=24);
    translate([ 20, backplate_h*0.08, socket_depth*0.4]) rotate([90,0,0]) cylinder(d=3, h=10, $fn=24);
}

module channel(){
    // Rectangular tunnel from cup to box
    len = (backplate_w/2 - box_outer_w/2) - 10;
    difference(){
        translate([(box_outer_w/2 + 10), 0, 0])
            cube([len, chan_w + 2*chan_wall, chan_h + 2*chan_wall], center=true);
        translate([(box_outer_w/2 + 10), 0, 0])
            cube([len+0.2, chan_w, chan_h], center=true);
    }
}

module box_with_lid(){
    // Electronics box on the right
    difference(){
        translate([ backplate_w/2 - box_outer_w/2, -backplate_h*0.05, 0 ])
            cube([box_outer_w, box_outer_h, box_outer_d], center=true);
        // cavity
        translate([ backplate_w/2 - box_outer_w/2, -backplate_h*0.05, 0 ])
            cube([box_outer_w - 2*box_wall, box_outer_h - 2*box_wall, box_outer_d - box_wall], center=true);
        // lid groove at front
        translate([ backplate_w/2 - box_outer_w/2, -backplate_h*0.05, box_outer_d/2 - (box_wall+lid_gap/2) ])
            cube([box_outer_w - 2*box_wall, box_outer_h - 2*box_wall, lid_gap], center=true);
        // pass-through for wire channel
        translate([ backplate_w/2 - box_outer_w - 6, 0, 0 ])
            cube([12, chan_w, chan_h], center=true);
    }
    // tiny relay shelf/ledge
    translate([ backplate_w/2 - box_outer_w/2, -backplate_h*0.05, -3 ])
        cube([relay_w, 2, relay_d], center=true);
}

module embossed_label(){
    translate([0, -backplate_h*0.32, -backplate_t + 0.3])
        linear_extrude(height=label_depth)
            text(label_text, size=label_size, font=label_font, halign="center", valign="center");
}

//////////////////// ASSEMBLY ////////////////////
difference(){
    union(){
        backplate();
        socket_cup();
        channel();
        box_with_lid();
        embossed_label();
    }
    // back side remains flat on bed
}

// DRILL TEMPLATE (uncomment to export DXF)
// projection(cut = true){
//     translate([0,0,-backplate_t])
//         offset(r=corner_r) square([backplate_w-2*corner_r, backplate_h-2*corner_r], center=true);
//     for (y = [-hole_offset_y, hole_offset_y])
//         for (x = [-backplate_w/2 + hole_offset_x, backplate_w/2 - hole_offset_x])
//             translate([x,y,0]) circle(d=hole_d, $fn=32);
// }
