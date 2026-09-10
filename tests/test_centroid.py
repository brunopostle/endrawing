import numpy as np
import pytest
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.geometry
import ifcopenshell.util.element
from endrawing import DrawingGenerator, GeometryUtils


def _make_space(prefix=None, rotation=0.0, profile_points=None):
    """Build a model with one space placed at (10, 20, 0) metres

    Args:
        prefix: SI length unit prefix, e.g. "MILLI", or None for metres
        rotation: Rotation of the space placement about z, in degrees
        profile_points: Optional closed polyline (project units) extruded 3m
            high; the default is a 4m x 2m x 3m box
    Returns:
        (ifc_file, space) tuple
    """
    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject")
    unit = ifcopenshell.api.run("unit.add_si_unit", ifc, unit_type="LENGTHUNIT", prefix=prefix)
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

    building = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding")
    building.Name = "Test Building"
    storey = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuildingStorey")
    storey.Name = "Ground Floor"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=building, products=[storey])
    ifcopenshell.api.geometry.edit_object_placement(ifc, product=storey)

    space = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcSpace")
    space.Name = "Kitchen"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=storey, products=[space])

    angle = np.radians(rotation)
    matrix = np.array(
        [
            [np.cos(angle), -np.sin(angle), 0.0, 10.0],
            [np.sin(angle), np.cos(angle), 0.0, 20.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    # The matrix is in metres, converted to project units by the API
    ifcopenshell.api.geometry.edit_object_placement(ifc, product=space, matrix=matrix)

    if profile_points:
        profile = ifc.createIfcArbitraryClosedProfileDef(
            "AREA",
            None,
            ifc.createIfcPolyline([ifc.createIfcCartesianPoint(p) for p in profile_points + profile_points[:1]]),
        )
        representation = ifcopenshell.api.geometry.add_profile_representation(
            ifc, context=body, profile=profile, depth=3.0
        )
    else:
        representation = ifcopenshell.api.geometry.add_wall_representation(
            ifc, context=body, length=4.0, height=3.0, thickness=2.0
        )
    ifcopenshell.api.geometry.assign_representation(ifc, product=space, representation=representation)

    return ifc, space


@pytest.mark.parametrize(
    "prefix, rotation, expected",
    [
        (None, 0.0, [12.0, 21.0, 1.5]),
        ("MILLI", 0.0, [12000.0, 21000.0, 1500.0]),
        (None, 90.0, [9.0, 22.0, 1.5]),
        ("MILLI", 90.0, [9000.0, 22000.0, 1500.0]),
    ],
)
def test_centroid_in_world_coordinates_and_project_units(prefix, rotation, expected):
    """Centroids include the placement rotation and are in project units (endrawing-bjm)"""
    ifc, space = _make_space(prefix=prefix, rotation=rotation)

    centroids = GeometryUtils.get_centroids(ifc, [space])

    assert centroids[space.id()] == pytest.approx(expected)


def test_centroid_is_volume_centroid_not_vertex_mean():
    """An L-shaped space's centroid is weighted by volume, not by vertex count"""
    # 4m x 1m leg plus a 1m x 2m leg: area centroid (1.5, 1.0), vertex mean (1.67, 1.33)
    ifc, space = _make_space(profile_points=[(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (1.0, 1.0), (1.0, 3.0), (0.0, 3.0)])

    centroids = GeometryUtils.get_centroids(ifc, [space])

    assert centroids[space.id()] == pytest.approx([11.5, 21.0, 1.5])


def test_centroid_skips_spaces_without_geometry():
    """Spaces without a body have no centroid, rather than raising"""
    ifc, space = _make_space()
    ifcopenshell.api.run("geometry.unassign_representation", ifc, product=space, representation=space.Representation.Representations[0])

    assert GeometryUtils.get_centroids(ifc, [space]) == {}


def test_space_label_placed_at_centroid():
    """The space label sits over the rotated space in a millimetre model"""
    ifc, space = _make_space(prefix="MILLI", rotation=90.0)

    DrawingGenerator(ifc).generate_drawings()

    labels = [
        a
        for a in ifc.by_type("IfcAnnotation")
        if ifcopenshell.util.element.get_psets(a).get("EPset_Annotation", {}).get("GeneratedBy") == "endrawing"
    ]
    assert len(labels) == 1
    x, y, z = labels[0].ObjectPlacement.RelativePlacement.Location.Coordinates
    assert (x, y) == pytest.approx((9000.0, 22000.0))
    assert z == pytest.approx(100.0)
