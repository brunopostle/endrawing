import numpy as np
import pytest
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.geometry
import ifcopenshell.util.element
import ifcopenshell.util.placement
from endrawing import DrawingGenerator, GeometryUtils


def _placement(ifc, relative_to, rotation=0.0, xyz=(0.0, 0.0, 0.0)):
    """Create a local placement rotated about z by rotation degrees"""
    angle = np.radians(rotation)
    return ifc.createIfcLocalPlacement(
        relative_to,
        ifc.createIfcAxis2Placement3D(
            ifc.createIfcCartesianPoint([float(c) for c in xyz]),
            ifc.createIfcDirection((0.0, 0.0, 1.0)),
            ifc.createIfcDirection((float(np.cos(angle)), float(np.sin(angle)), 0.0)),
        ),
    )


def _make_building(building_rotation=0.0, site_rotation=0.0, block_rotation=0.0, true_north=None):
    """Build a metre model with a 10m x 6m x 3m block in a building at (100, 50, 0)

    The block and a 4m x 2m space run along the storey's x axis.

    Args:
        building_rotation: Building placement rotation relative to the site, in degrees
        site_rotation: Site placement rotation, in degrees
        block_rotation: Rotation of the block's own placement in the storey, in degrees
        true_north: Optional 2D TrueNorth direction ratios for the Model context
    Returns:
        (ifc_file, building) tuple
    """
    ifc = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject")
    unit = ifcopenshell.api.run("unit.add_si_unit", ifc, unit_type="LENGTHUNIT")
    ifcopenshell.api.run("unit.assign_unit", ifc, units=[unit])
    model = ifcopenshell.api.run("context.add_context", ifc, context_type="Model")
    body = ifcopenshell.api.run(
        "context.add_context",
        ifc,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model,
    )
    if true_north:
        model.TrueNorth = ifc.createIfcDirection([float(c) for c in true_north])

    site = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcSite")
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=project, products=[site])
    site.ObjectPlacement = _placement(ifc, None, site_rotation)

    building = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding")
    building.Name = "Block"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=site, products=[building])
    building.ObjectPlacement = _placement(ifc, site.ObjectPlacement, building_rotation, (100.0, 50.0, 0.0))

    storey = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuildingStorey")
    storey.Name = "Ground Floor"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=building, products=[storey])
    storey.ObjectPlacement = _placement(ifc, building.ObjectPlacement)

    block = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcWall")
    ifcopenshell.api.run("spatial.assign_container", ifc, relating_structure=storey, products=[block])
    block.ObjectPlacement = _placement(ifc, storey.ObjectPlacement, block_rotation)
    representation = ifcopenshell.api.geometry.add_wall_representation(
        ifc, context=body, length=10.0, height=3.0, thickness=6.0
    )
    ifcopenshell.api.geometry.assign_representation(ifc, product=block, representation=representation)

    space = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcSpace")
    space.Name = "Hall"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=storey, products=[space])
    space.ObjectPlacement = _placement(ifc, storey.ObjectPlacement)
    representation = ifcopenshell.api.geometry.add_wall_representation(
        ifc, context=body, length=4.0, height=3.0, thickness=2.0
    )
    ifcopenshell.api.geometry.assign_representation(ifc, product=space, representation=representation)

    return ifc, building


def _drawings(ifc):
    return {a.Name: a for a in ifc.by_type("IfcAnnotation") if a.ObjectType == "DRAWING"}


def _is_elevation(annotation):
    return ifcopenshell.util.element.get_psets(annotation)["EPset_Drawing"]["TargetView"] == "ELEVATION_VIEW"


def _camera(annotation):
    """Get (location, axis, ref_direction, block dimensions) of a drawing camera"""
    placement = annotation.ObjectPlacement.RelativePlacement
    block = annotation.Representation.Representations[0].Items[0].TreeRootExpression
    return (
        np.array(placement.Location.Coordinates),
        np.array(placement.Axis.DirectionRatios),
        np.array(placement.RefDirection.DirectionRatios),
        (block.XLength, block.YLength, block.ZLength),
    )


def _axes(rotation):
    angle = np.radians(rotation)
    return np.array([np.cos(angle), np.sin(angle), 0.0]), np.array([-np.sin(angle), np.cos(angle), 0.0])


ROTATED = [
    pytest.param({"building_rotation": 30.0}, 30.0, id="30"),
    pytest.param({"building_rotation": 45.0}, 45.0, id="45"),
    pytest.param({"site_rotation": 30.0}, 30.0, id="site-30"),
]


@pytest.mark.parametrize("kwargs, rotation", ROTATED + [pytest.param({}, 0.0, id="0")])
def test_building_rotation_from_placement(kwargs, rotation):
    """A building's rotation includes its site's, and unrotated buildings have none (endrawing-991)"""
    ifc, building = _make_building(**kwargs)

    matrix = GeometryUtils.get_rotation(building)

    if rotation == 0.0:
        assert matrix is None
    else:
        x_axis, y_axis = _axes(rotation)
        assert matrix[:, 0] == pytest.approx(x_axis)
        assert matrix[:, 1] == pytest.approx(y_axis)


@pytest.mark.parametrize("kwargs, rotation", ROTATED)
def test_oriented_bbox_fits_rotated_building(kwargs, rotation):
    """The bbox of a rotated building is aligned to it, not inflated by the world axes"""
    ifc, building = _make_building(**kwargs)

    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(
        ifc, [building], rotation=GeometryUtils.get_rotation(building)
    )

    assert np.subtract(bbox_max, bbox_min) == pytest.approx([10.0, 6.0, 3.0])


@pytest.mark.parametrize("kwargs, rotation", ROTATED + [pytest.param({}, 0.0, id="0")])
def test_plan_square_to_building(kwargs, rotation):
    """Plan cameras run along the building's x axis and fit its bbox"""
    ifc, building = _make_building(**kwargs)

    DrawingGenerator(ifc).generate_drawings()

    location, axis, ref_direction, dims = _camera(_drawings(ifc)["Block Ground Floor"])
    x_axis, _ = _axes(rotation)
    assert axis == pytest.approx([0.0, 0.0, 1.0])
    assert ref_direction == pytest.approx(x_axis)
    assert dims == pytest.approx((12.0, 8.0, 10.0))
    placement = ifcopenshell.util.placement.get_local_placement(building.ObjectPlacement)
    assert location == pytest.approx(placement[:3, :3] @ [5.0, 3.0, 1.8] + placement[:3, 3])


@pytest.mark.parametrize(
    "kwargs, names",
    [
        pytest.param({}, ["NORTH", "SOUTH", "WEST", "EAST"], id="0"),
        pytest.param({"building_rotation": 22.5}, ["NORTH", "SOUTH", "WEST", "EAST"], id="22.5-tie"),
        pytest.param(
            {"building_rotation": 30.0}, ["NORTH-WEST", "SOUTH-EAST", "SOUTH-WEST", "NORTH-EAST"], id="30"
        ),
        pytest.param(
            {"building_rotation": 45.0}, ["NORTH-WEST", "SOUTH-EAST", "SOUTH-WEST", "NORTH-EAST"], id="45"
        ),
        pytest.param(
            {"site_rotation": 30.0}, ["NORTH-WEST", "SOUTH-EAST", "SOUTH-WEST", "NORTH-EAST"], id="site-30"
        ),
        # True north 90 degrees anticlockwise of project north, towards world -x
        pytest.param({"true_north": (-1.0, 0.0)}, ["EAST", "WEST", "NORTH", "SOUTH"], id="true-north-90"),
        pytest.param(
            {"building_rotation": 30.0, "true_north": (-1.0, 0.0)},
            ["NORTH-EAST", "SOUTH-WEST", "NORTH-WEST", "SOUTH-EAST"],
            id="30-true-north-90",
        ),
    ],
)
def test_elevations_named_by_compass_point(kwargs, names):
    """Each elevation looks square on to one face of the building and is named by its compass bearing"""
    ifc, building = _make_building(**kwargs)
    rotation = GeometryUtils.get_rotation(building)
    rotation = np.eye(3) if rotation is None else rotation

    DrawingGenerator(ifc).generate_drawings()

    drawings = _drawings(ifc)
    assert {n for n, a in drawings.items() if _is_elevation(a)} == {f"Block {n}" for n in names}
    # Faces along the building's +y, -y, -x and +x axes
    normals = [[0.0, 1.0, 0.0], [0.0, -1.0, 0.0], [-1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    for name, normal in zip(names, normals):
        location, axis, ref_direction, dims = _camera(drawings[f"Block {name}"])
        assert axis == pytest.approx(rotation @ normal)
        assert ref_direction == pytest.approx(rotation @ np.cross([0.0, 0.0, 1.0], normal))
        # Face width and height padded by 2m, depth padded by 2m less 1m
        width, depth = (12.0, 7.0) if normal[1] else (8.0, 11.0)
        assert dims == pytest.approx((width, 5.0, depth))


def test_rotated_elements_in_unrotated_building_stay_world_aligned():
    """Orientation comes from the building placement only, never from its geometry"""
    ifc, building = _make_building(block_rotation=30.0)

    DrawingGenerator(ifc).generate_drawings()

    drawings = _drawings(ifc)
    assert {n for n, a in drawings.items() if _is_elevation(a)} == {
        "Block NORTH",
        "Block SOUTH",
        "Block EAST",
        "Block WEST",
    }
    location, axis, ref_direction, dims = _camera(drawings["Block Ground Floor"])
    assert ref_direction == pytest.approx([1.0, 0.0, 0.0])
    # World-aligned bbox of the rotated block, padded by 2m
    angle = np.radians(30.0)
    width = 10.0 * np.cos(angle) + 6.0 * np.sin(angle)
    assert dims[0] == pytest.approx(width + 2.0)


def test_location_plan_stays_north_up():
    """The site-wide location plan isn't rotated with the buildings"""
    ifc, building = _make_building(building_rotation=30.0)
    other = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding")
    other.Name = "Other"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=ifc.by_type("IfcSite")[0], products=[other])

    DrawingGenerator(ifc).generate_drawings()

    placement = _drawings(ifc)["Block LOCATION"].ObjectPlacement.RelativePlacement
    assert placement.RefDirection is None


def test_space_labels_follow_rotated_plan():
    """Space label text runs along the building's x axis, like its plan"""
    ifc, building = _make_building(building_rotation=30.0)

    DrawingGenerator(ifc).generate_drawings()

    [label] = [
        a
        for a in ifc.by_type("IfcAnnotation")
        if ifcopenshell.util.element.get_psets(a).get("EPset_Annotation", {}).get("GeneratedBy") == "endrawing"
    ]
    x_axis, _ = _axes(30.0)
    assert np.array(label.ObjectPlacement.RelativePlacement.RefDirection.DirectionRatios) == pytest.approx(x_axis)
