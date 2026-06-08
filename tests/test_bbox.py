import ifcopenshell
import ifcopenshell.api
from endrawing import GeometryUtils


def _make_storey_with_walls(wall_coords):
    """Build a minimal IFC with one storey containing walls at given origins.

    Args:
        wall_coords: list of (x, y, z) tuples for wall placements
    Returns:
        (ifc_file, building) tuple
    """
    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject")
    ifcopenshell.api.run("unit.assign_unit", ifc)

    building = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding")
    building.Name = "Test Building"

    storey = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuildingStorey")
    storey.Name = "Test Building"  # location filter matches on Name
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=building, products=[storey])

    axis_z = ifc.createIfcDirection((0.0, 0.0, 1.0))
    axis_x = ifc.createIfcDirection((1.0, 0.0, 0.0))
    origin = ifc.createIfcCartesianPoint((0.0, 0.0, 0.0))
    storey.ObjectPlacement = ifc.createIfcLocalPlacement(
        None, ifc.createIfcAxis2Placement3D(origin, axis_z, axis_x)
    )

    for i, (x, y, z) in enumerate(wall_coords):
        wall = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcWall")
        wall.Name = f"Wall {i}"
        ifcopenshell.api.run(
            "spatial.assign_container", ifc, relating_structure=storey, products=[wall]
        )
        pt = ifc.createIfcCartesianPoint((float(x), float(y), float(z)))
        wall.ObjectPlacement = ifc.createIfcLocalPlacement(
            storey.ObjectPlacement, ifc.createIfcAxis2Placement3D(pt, axis_z, axis_x)
        )

    return ifc, building


def test_bbox_single_element_does_not_crash():
    """A location with one placed element must not raise (endrawing-4ix)."""
    ifc, building = _make_storey_with_walls([(5.0, 6.0, 7.0)])
    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert bbox_min == [5.0, 6.0, 7.0]
    assert bbox_max == [5.0, 6.0, 7.0]
    assert bbox_mid == [5.0, 6.0, 7.0]


def test_bbox_no_valid_elements_returns_degenerate():
    """No placed elements yields a zero bbox rather than crashing (endrawing-4ix)."""
    ifc, building = _make_storey_with_walls([])
    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert bbox_min == [0.0, 0.0, 0.0]
    assert bbox_max == [0.0, 0.0, 0.0]
    assert bbox_mid == [0.0, 0.0, 0.0]


def test_bbox_keeps_elements_on_world_axis():
    """Elements legitimately placed on x=0 or y=0 are not discarded (endrawing-qyz)."""
    # Wall on x=0 axis and a wall on y=0 axis; neither is the true origin.
    ifc, building = _make_storey_with_walls([(0.0, 4.0, 0.0), (8.0, 0.0, 0.0)])
    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert bbox_min == [0.0, 0.0, 0.0]
    assert bbox_max == [8.0, 4.0, 0.0]


def test_bbox_skips_true_origin_only():
    """An element at the world origin is skipped, real placements still bound (endrawing-qyz)."""
    ifc, building = _make_storey_with_walls([(0.0, 0.0, 0.0), (2.0, 3.0, 4.0), (9.0, 1.0, 1.0)])
    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert bbox_min == [2.0, 1.0, 1.0]
    assert bbox_max == [9.0, 3.0, 4.0]


def test_bbox_spans_all_elements():
    """Every element contributes to both min and max (lazy-fill regression)."""
    ifc, building = _make_storey_with_walls([(1.0, 1.0, 1.0), (5.0, 5.0, 5.0), (3.0, 9.0, 2.0)])
    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert bbox_min == [1.0, 1.0, 1.0]
    assert bbox_max == [5.0, 9.0, 5.0]
