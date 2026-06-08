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
  - `get_bbox()`: Calculates bounding boxes from spatial element placements by iterating through all IfcElements in a location
  - `get_centroid()`: Computes geometric centroid from element vertices for label placement
  - Both methods are essential for camera positioning and space label placement

### Drawing Generation
- **DrawingGenerator**: Main orchestrator class that:
  - Calculates overall site bounding box from all buildings using natsorted ordering
  - Creates one sheet per building with identification like "A001", "A002", etc.
  - Generates plan drawings for each building storey (camera positioned at elevation + 1.8m)
  - Creates four elevation drawings (NORTH, SOUTH, EAST, WEST) with direction-specific camera placement
  - Optionally creates location plans at 10x scale when multiple buildings exist
  - Places space labels at geometric centroids using text annotations

### Property and Document Management
All handled within DrawingGenerator methods:
- `create_drawing_pset()`: Creates EPset_Drawing property sets with scale (1:100 default), view type, and asset paths for CSS/SVG resources
- `set_elevation_properties()`: Configures ELEVATION_VIEW and Include filter for building-specific elements
- `attach_sheet()`: Associates drawings with sheets via IfcDocumentInformation and IfcDocumentReference hierarchy
- `create_drawing_group()`: Creates DRAWING groups and assigns annotation entities

### Drawing Identification and Update Strategy

**IMPORTANT**: Endrawing only creates General Arrangement (GA) drawings - plans and elevations showing entire buildings at layout scale. Real projects contain many other drawing types (details, sections, reflected ceiling plans, structural, electrical, etc.). Endrawing **never** modifies or deletes drawings it didn't create.

**Identification System**:
All endrawing-created content is marked with a custom property in EPset_Drawing:
- `GeneratedBy: "endrawing"` - Identifies all endrawing-created IfcAnnotation drawings

**Update Behavior** (automatic):
When endrawing runs, it automatically:
1. Finds all existing IfcAnnotation entities where EPset_Drawing contains `GeneratedBy = "endrawing"`
2. Removes those annotations using `api.root.remove_product()` (handles relationships automatically)
3. Finds and removes orphaned IfcGroup entities with ObjectType = "DRAWING" that have no related objects
4. Finds and removes orphaned IfcDocumentInformation sheets with Purpose = "General Arrangement" that have no drawing references
5. Regenerates fresh GA drawings and sheets for all current buildings

This makes endrawing **idempotent** - running it multiple times updates the GA drawings to match the current building model, while preserving all other project drawings.

**Safety**: Only entities explicitly marked with `GeneratedBy = "endrawing"` are ever modified. All other drawings, sheets, annotations, and documents are left untouched. The cleanup process uses proper ifcopenshell API calls and defensive programming to handle edge cases gracefully.

## Key Technical Details

**Drawing Scale**: Default scale is 1:100 on A2 sheets. Scale and titleblock are configurable via DrawingGenerator constructor parameters. Drawing positions on sheets are handled automatically by Bonsai BIM's heuristic placement when sheets are generated.

**Camera Placement**: Drawing cameras are positioned using IFC placement matrices:
- Plans: Positioned above storey elevations at `elevation + 1.8m` looking down
- Elevations: Offset 0.5m from bounding box faces with direction-specific axis/reference directions
  - NORTH: Views from north looking south (y+, ref direction x-)
  - SOUTH: Views from south looking north (y-, ref direction x+)
  - EAST: Views from east looking west (x+, ref direction y+)
  - WEST: Views from west looking east (x-, ref direction y-)

**IFC API Usage**: The tool uses ifcopenshell.api for high-level operations (api.root.create_entity, api.pset, api.group, api.drawing) and direct IFC entity creation for lower-level geometry (createIfcCartesianPoint, createIfcAxis2Placement3D, createIfcDocumentReference).

**Building Selection**: Uses ifcopenshell.util.selector with location filters: `'IfcElement, location="{building.Name}"'` to scope geometry queries to specific buildings/storeys.

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

**Scale Denominators**: Drawing scale is independent of project units. Any scale can be specified (e.g., `--scale 100` for 1:100, `--scale 48` for 1:48).

## Known Limitations

- **Building orientation**: Bounding box calculation doesn't consider building's local coordinate system rotation (see FIXME comment at endrawing.py:833)
- **Default settings**: A2 and 1:100 scale are defaults (configurable via `--scale` and `--titleblock` arguments)


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
