# Endrawing

*Creates General Arrangement drawings for IFC buildings*

Each building gets a sheet with plans and north, south, east and west elevations.

## Features

- **Automatic drawing generation**: Creates plan and elevation drawings for all buildings
- **Universal unit support**: Works with metric (m, mm, cm) and imperial (ft, in) or any IFC-defined units
- **Idempotent operation**: Re-running updates existing drawings without creating duplicates
- **Safe**: Only modifies drawings it created, preserves all other project content
- **Configurable**: Supports custom scales and titleblock sizes via command-line arguments
- **Dual-mode**: Works as command-line tool or within Bonsai BIM

## Usage

### Command Line

```bash
# Basic usage with defaults (1:100 scale, or 1/8"=1'-0" in imperial projects; A2 titleblock)
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
- Four elevation drawings per building, square on to its faces and named by the nearest compass point to true north (NORTH, SOUTH, EAST and WEST, or NORTH-EAST etc. for buildings turned nearer 45 degrees)
- Plans and elevations follow the building's own axes, taken from its placement, so a rotated building's plans sit square on the sheet
- Optional location plan (when multiple buildings exist)
- One A-series sheet per building containing all its drawings

All generated content is marked with `GeneratedBy: "endrawing"` in the EPset_Drawing property set. This allows the tool to safely update drawings on subsequent runs without affecting manually created drawings.

## Requirements

- Python 3.9+
- ifcopenshell
- natsort

## Limitations

- **North arrows on rotated plans**: Plans of rotated buildings aren't north up, but Bonsai's titleblock north arrow only follows the project's true north, so on those sheets it's off by the building's rotation.

## Development

Run tests:

```bash
pip install -e .[dev]
python -m pytest tests/
```

2024 Bruno Postle <bruno@postle.net>

License: SPDX:GPL-3.0-or-later
