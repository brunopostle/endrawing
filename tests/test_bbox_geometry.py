import pytest
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.geometry
import ifcopenshell.geom
from endrawing import DrawingGenerator, GeometryUtils


def _make_building(prefix=None):
    """Build a minimal IFC with a Body context and one storey.

    Args:
        prefix: SI length unit prefix, e.g. "MILLI", or None for metres
    Returns:
        (ifc_file, building, storey, body_context) tuple
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
    storey.ObjectPlacement = _placement(ifc, None, (0.0, 0.0, 0.0))

    return ifc, building, storey, body


def _placement(ifc, relative_to, xyz):
    return ifc.createIfcLocalPlacement(
        relative_to,
        ifc.createIfcAxis2Placement3D(
            ifc.createIfcCartesianPoint([float(c) for c in xyz]),
            ifc.createIfcDirection((0.0, 0.0, 1.0)),
            ifc.createIfcDirection((1.0, 0.0, 0.0)),
        ),
    )


def _add_wall(ifc, storey, xyz, body=None):
    """Add a wall at xyz (project units), with a 5m x 0.2m x 3m body if given"""
    wall = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcWall")
    ifcopenshell.api.run("spatial.assign_container", ifc, relating_structure=storey, products=[wall])
    wall.ObjectPlacement = _placement(ifc, storey.ObjectPlacement, xyz)
    if body:
        # Dimensions are in metres, converted to project units by the API
        representation = ifcopenshell.api.geometry.add_wall_representation(
            ifc, context=body, length=5.0, height=3.0, thickness=0.2
        )
        ifcopenshell.api.geometry.assign_representation(ifc, product=wall, representation=representation)
    return wall


def test_bbox_encloses_geometry_not_origin():
    """The bbox covers the top of the wall, not just its base origin"""
    ifc, building, storey, body = _make_building()
    _add_wall(ifc, storey, (1.0, 2.0, 0.0), body)

    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert bbox_min == pytest.approx([1.0, 2.0, 0.0])
    assert bbox_max == pytest.approx([6.0, 2.2, 3.0])
    assert bbox_mid == pytest.approx([3.5, 2.1, 1.5])


def test_bbox_geometry_in_millimetres():
    """Geometry bounds are returned in project units, not metres"""
    ifc, building, storey, body = _make_building(prefix="MILLI")
    _add_wall(ifc, storey, (1000.0, 2000.0, 0.0), body)

    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert bbox_min == pytest.approx([1000.0, 2000.0, 0.0])
    assert bbox_max == pytest.approx([6000.0, 2200.0, 3000.0])


def test_bbox_mixes_geometry_and_origin_fallback():
    """Elements without geometry still contribute their placement origin"""
    ifc, building, storey, body = _make_building()
    _add_wall(ifc, storey, (1.0, 2.0, 0.0), body)
    _add_wall(ifc, storey, (20.0, 30.0, 1.0))

    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert bbox_min == pytest.approx([1.0, 2.0, 0.0])
    assert bbox_max == pytest.approx([20.0, 30.0, 3.0])


def test_bbox_uses_precomputed_bounds():
    """Precomputed element bounds are used instead of re-tessellating"""
    ifc, building, storey, body = _make_building()
    wall = _add_wall(ifc, storey, (1.0, 2.0, 0.0), body)

    fake_bounds = {wall.id(): ([-1.0, -2.0, -3.0], [4.0, 5.0, 6.0])}
    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building], fake_bounds)

    assert bbox_min == [-1.0, -2.0, -3.0]
    assert bbox_max == [4.0, 5.0, 6.0]


def test_generator_bbox_encloses_geometry():
    """DrawingGenerator's site bbox reaches the top of the geometry"""
    ifc, building, storey, body = _make_building()
    _add_wall(ifc, storey, (1.0, 2.0, 0.0), body)

    generator = DrawingGenerator(ifc)

    assert generator.bbox_all_max == pytest.approx([6.0, 2.2, 3.0])
    generator.generate_drawings()


def test_element_bounds_falls_back_without_cgal(monkeypatch):
    """Builds without the hybrid CGAL kernel fall back to OpenCASCADE"""
    ifc, building, storey, body = _make_building()
    _add_wall(ifc, storey, (1.0, 2.0, 0.0), body)

    real_iterator = ifcopenshell.geom.iterator
    libraries = []

    def iterator(*args, geometry_library="opencascade", **kwargs):
        libraries.append(geometry_library)
        if geometry_library != "opencascade":
            raise RuntimeError(f"No geometry kernel registered for {geometry_library}")
        return real_iterator(*args, geometry_library=geometry_library, **kwargs)

    monkeypatch.setattr(ifcopenshell.geom, "iterator", iterator)
    bbox_min, bbox_mid, bbox_max = GeometryUtils.get_bbox(ifc, [building])

    assert libraries == ["hybrid-cgal-simple-opencascade", "opencascade"]
    assert bbox_max == pytest.approx([6.0, 2.2, 3.0])
