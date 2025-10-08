# Endrawing

*Creates General Arrangement drawings for IFC buildings*

Each building gets a sheet with plans and north, south, east and west elevations.

## Features

- **Automatic drawing generation**: Creates plan and elevation drawings for all buildings
- **Idempotent operation**: Re-running updates existing drawings without creating duplicates
- **Safe**: Only modifies drawings it created, preserves all other project content
- **Configurable**: Supports custom scales and titleblock sizes via command-line arguments
- **Dual-mode**: Works as command-line tool or within Bonsai BIM

## Usage

### Command Line

```bash
# Basic usage with defaults (1:100 scale, A2 titleblock)
python endrawing.py input.ifc output.ifc

# Custom scale and titleblock
python endrawing.py input.ifc output.ifc --scale 50 --titleblock A1

# View help
python endrawing.py --help
```

### Within Bonsai BIM

Load the script in the Blender Text Editor and 'run' (only once!).

Then in Bonsai BIM generate all the drawings before generating the sheets.

## Installation

Install via pip for the `endrawing` command:

```bash
pip install -e .
endrawing input.ifc output.ifc --scale 200
```

## How It Works

Endrawing generates:
- One plan drawing per building storey
- Four elevation drawings (NORTH, SOUTH, EAST, WEST) per building
- Optional location plan (when multiple buildings exist)
- One A-series sheet per building containing all its drawings

All generated content is marked with `GeneratedBy: "endrawing"` in the EPset_Drawing property set. This allows the tool to safely update drawings on subsequent runs without affecting manually created drawings.

## Requirements

- Python 3.9+
- ifcopenshell
- natsort

## Limitations

- **Metric units**: Camera positioning assumes project coordinates are in meters. Imperial projects (feet/inches) will have incorrectly positioned cameras.
- **Building rotation**: Bounding box calculation doesn't account for rotated buildings in their local coordinate system.

## Development

Run tests:

```bash
pip install -e .[dev]
python -m pytest tests/
```

2024 Bruno Postle <bruno@postle.net>

License: SPDX:GPL-3.0-or-later
