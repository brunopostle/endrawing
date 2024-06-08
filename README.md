# Endrawing

*Creates General Arrangement drawings for IFC buildings*

Each building gets a sheet with plans and north, south, east and west
elevations.

Either run on the command-line:

    endrawing.py infile.ifc outfile.ifc

..or within BlenderBIM: Load the script in the Blender Text Editor and 'run'
(only once!).

Then in BlenderBIM generate all the drawings before generating the sheets.

Drawbacks:

- A2 and 1:100 scale are currently hard-coded
- BlenderBIM currently doesn't recognise drawing positions, so you still have to arrange in Inkscape

2024 Bruno Postle <bruno@postle.net>

License: SPDX:GPL-3.0-or-later
