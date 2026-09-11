# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Endrawing is a Python tool that automatically generates General Arrangement drawing sheets for IFC (Industry Foundation Classes) building models. It creates architectural documentation with plans and elevations for each building in an IFC file.

## Usage

Run the script from command line:

```bash
./endrawing.py input.ifc output.ifc
```

Or within Bonsai BIM: Load the script in the Blender Text Editor and run once. Then generate all drawings before generating sheets in Bonsai BIM.

## Core Architecture

The codebase is organized into functional classes in `endrawing.py`:

### Context and Representation Management
- **ContextManager**: Ensures IFC geometric representation contexts (Model, Plan, Annotation) exist before drawing creation. Creates the Plan context and Annotation subcontext if missing.
- **ShapeCreator**: Creates IFC shape representations for camera volumes (using CSG solids/IfcBlock) and text labels (using IfcTextLiteralWithExtent with `{{Name}}` template).

### Geometry Operations
- **GeometryUtils**:
  - `get_bbox()`: Calculates bounding boxes enclosing the geometry of all IfcElements in a location. Elements without geometry contribute their placement origin instead
  - `iterate_shapes()`: Tessellates elements in one multithreaded `ifcopenshell.geom.iterator` pass (world coords, project units, openings skipped). Uses the `hybrid-cgal-simple-opencascade` kernel (about 2x faster than OpenCASCADE, same bounds), falling back to `opencascade` on builds without CGAL
  - `get_element_bounds()`: Takes numpy min/max per vertex buffer from `iterate_shapes()`. DrawingGenerator calls it once and passes the result to every `get_bbox()` call
  - `get_centroids()`: Volume centroids of element meshes from `iterate_shapes()`, used to place space labels. `generate_drawings()` calls it once for all spaces

### Drawing Generation
- **DrawingGenerator**: Main orchestrator class that:
  - Calculates overall site bounding box from all buildings using natsorted ordering
  - Creates one sheet per building with identification like "A001", "A002", etc.
  - Generates plan drawings for each building storey (camera positioned at elevation + 1.8m), named "{building} {storey}". A drawing's name gives its SVG path (`drawings/{name}.svg`), and storey names such as "Ground Floor" repeat across buildings, so the building name keeps them apart
  - Creates four elevation drawings, one per face of the building's bbox, named by the nearest compass point to true north (NORTH, NORTH-EAST, ... NORTH-WEST)
  - Optionally creates location plans at 10x scale when multiple buildings exist
  - Places space labels at geometric centroids using text annotations

### Property and Document Management
All handled within DrawingGenerator methods:
- `create_drawing_pset()`: Creates EPset_Drawing property sets with scale (1:100 default), view type, and asset paths for CSS/SVG resources
- `set_elevation_properties()`: Configures ELEVATION_VIEW and Include filter for building-specific elements
- `attach_sheet()`: Creates the drawing's IfcDocumentInformation (Scope DRAWING) nested under Bonsai's DRAWINGS parent document, a reference to the drawing SVG associated with the annotation, and a DRAWING reference placing it on the sheet, following Bonsai's add_drawing and AddDrawingToSheet
- `create_sheet_info()`: Creates the sheet (Scope SHEET, Purpose "General Arrangement") with LAYOUT and TITLEBLOCK references, following Bonsai's add_sheet
- `create_drawing_group()`: Creates DRAWING groups, assigns annotation entities, and assigns the group to Bonsai's DRAWINGS parent group
- `ensure_drawings_parent_document()` / `ensure_drawings_parent_group()`: Find or create the DRAWINGS parents the same way Bonsai does. They're shared with Bonsai-made drawings and never removed
- `edit_information()` / `add_reference()`: Take IFC4 attribute names and convert them for IFC2X3 (DocumentId, ItemReference, and Name for Description), like Bonsai's generate_reference_attributes

### Drawing Identification and Update Strategy

**IMPORTANT**: Endrawing only creates General Arrangement (GA) drawings - plans and elevations showing entire buildings at layout scale. Real projects contain many other drawing types (details, sections, reflected ceiling plans, structural, electrical, etc.). Endrawing **never** modifies or deletes drawings it didn't create.

**Identification System**:
All endrawing-created content is marked with a custom property in EPset_Drawing:
- `GeneratedBy: "endrawing"` - Identifies all endrawing-created IfcAnnotation drawings

**Update Behavior** (automatic):
When endrawing runs, it automatically:
1. Finds all existing IfcAnnotation entities where EPset_Drawing (drawings) or EPset_Annotation (space labels) contains `GeneratedBy = "endrawing"`
2. Identifies generated sheets: Scope SHEET, Purpose "General Arrangement", and every DRAWING reference pointing at a generated drawing's SVG. A sheet holding any other drawing, or none, is the user's and is kept. Purpose alone never decides ownership
3. Removes the generated drawings' own IfcDocumentInformation (and with it their references and parent membership), then the annotations using `api.root.remove_product()`
4. Removes the generated drawings' DRAWING groups once they're empty (a group still holding annotations the user added is kept)
5. Removes the generated sheets with `api.document.remove_information()`
6. Regenerates fresh GA drawings and sheets for all current buildings

The DRAWINGS parent document and group are shared with Bonsai-made drawings and are never removed.

This makes endrawing **idempotent** - running it multiple times updates the GA drawings to match the current building model, while preserving all other project drawings.

**Safety**: Only entities explicitly marked with `GeneratedBy = "endrawing"` are ever modified. All other drawings, sheets, annotations, and documents are left untouched. The cleanup process uses proper ifcopenshell API calls and defensive programming to handle edge cases gracefully.

## Key Technical Details

**Drawing Scale**: Default scale is 1:100 on A2 sheets, or 1/96 (1/8"=1'-0") in imperial projects, matching Bonsai's add_drawing. Imperial HumanScale uses Bonsai's architectural and engineering notation (`IMPERIAL_HUMAN_SCALES`), falling back to `1:N`. The location plan is 10x the drawing scale (1:1000, or 1"=80'). Scale and titleblock are configurable via DrawingGenerator constructor parameters. Drawing positions on sheets are handled automatically by Bonsai BIM's heuristic placement when sheets are generated.

**Building Orientation**: A building's orientation comes only from the z rotation of its absolute placement (`GeometryUtils.get_rotation()`, which includes a rotated site above it). Geometry is never used to infer orientation: walls rotated inside an unrotated building placement are a modelling error, and such buildings stay world-aligned. For rotated buildings, `get_oriented_element_bounds()` rotates each element's vertices into the building's axes before taking min/max, in the same tessellation pass as the world bounds, and `get_bbox(..., rotation=)` returns the bbox in coordinates along those axes. Camera code works in those coordinates, and `create_camera_placement()` rotates points and directions back to world coordinates. Unrotated buildings (rotation None) behave exactly as world-aligned ones always did.

**Camera Placement**: Drawing cameras are positioned using IFC placement matrices:
- Plans: Positioned above storey elevations at `elevation + 1.8m` looking down, with RefDirection along the building's x axis, so plans of rotated buildings are square to the sheet (north isn't up)
- Elevations: Offset 0.5m from each face of the building's bbox, looking square on to it: Axis is the face's outward normal and RefDirection is z × normal. Faces along the building's +y, -y, -x and +x axes are drawn in that order
- Elevation names: the compass bearing of the face's outward normal, measured clockwise from true north (the Model context's TrueNorth, via `ifcopenshell.util.geolocation.get_true_north()`), snapped to the nearest of eight points in `COMPASS_POINTS` (N, NE, E, SE, S, SW, W, NW). The four faces are 90 degrees apart so names never collide; a bearing exactly between two points goes to the cardinal one
- Location plans: world-aligned and north up, whatever the buildings' rotations
- Space labels: text RefDirection along the building's x axis, so it reads along the plan

**IFC API Usage**: The tool uses ifcopenshell.api for contexts, documents, groups, psets and products (api.context, api.document, api.group, api.pset, api.root, api.drawing), which handles schema differences, so IFC2X3 and IFC4 both work. Direct IFC entity creation is only used for lower-level geometry whose attribute layout is the same in both schemas (createIfcCartesianPoint, createIfcAxis2Placement3D, createIfcBlock, createIfcTextLiteralWithExtent). IFC2X3 models need an owner history user and application (see tests/test_documents.py).

**Building Selection**: Bounding boxes collect a building's elements with `ifcopenshell.util.element.get_decomposition()`, which gives the same elements as a selector `location=` query but is about 20x faster on large models. Storeys are found the same way. Elevation and location plan Include filters, which Bonsai evaluates as selector strings, use `location="{building.GlobalId}"`: the selector matches a location by Name or GlobalId, and GlobalId keeps buildings that share a Name apart.

**Asset References**: EPset_Drawing properties reference external resources:
- `drawings/assets/default.css` - Drawing stylesheet
- `drawings/assets/markers.svg` - SVG markers
- `drawings/assets/symbols.svg` - Symbol library
- `drawings/assets/patterns.svg` - Hatch patterns
- `drawings/assets/shading_styles.json` - Shading configuration

**Output Structure**:
- `drawings/` - Individual SVG drawings (plans, elevations)
- `drawings/assets/` - CSS, SVG markers/symbols/patterns, shading styles
- `drawings/cache/` - Temporary cache files
- `layouts/` - Assembled sheets with drawings positioned on titleblocks
- `layouts/titleblocks/` - A2 (or other) titleblock templates

## Dependencies

Required Python packages:
- **ifcopenshell** - IFC file manipulation and API
- **natsort** - Natural sorting of building names for consistent sheet ordering

Runtime modes:
- **Standalone**: Command line execution with input/output IFC files
- **Bonsai BIM integration**: Uses `bonsai.tool.Ifc.get()` to access active model in Blender

## Unit Support

**Automatic Unit Detection**: Endrawing automatically detects and handles project units using `ifcopenshell.util.unit.calculate_unit_scale()`. All geometric offsets are converted to the project's native units:
- **Camera positioning**: 1.8m height offset above floors (converted to project units)
- **Bounding box padding**: 2m padding around buildings (converted to project units)
- **Elevation offsets**: 0.5m camera distance from building faces (converted to project units)

**Supported Units**: Works with any unit system including:
- Metric: meters, millimeters, centimeters
- Imperial: feet, inches
- Any other IFC-defined length units

**Scale Denominators**: Only the default scale depends on project units: projects whose length unit isn't an SI unit are imperial, as in Bonsai. Any scale can be specified (e.g., `--scale 100` for 1:100, `--scale 48` for 1/4"=1'-0" in an imperial project).

## Known Limitations

- **North arrows on rotated plans**: Bonsai's titleblocks rotate their north arrows by the project's true north only, per sheet, so on sheets of rotated buildings (whose plans are square to the sheet) the titleblock arrow is off by the building's rotation. Automatic north arrows belong in lower-level tools (Bonsai), since users drawing by hand want them too, so endrawing doesn't place its own
- **Default settings**: A2 and 1:100 (1/8"=1'-0" imperial) scale are defaults (configurable via `--scale` and `--titleblock` arguments)


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
