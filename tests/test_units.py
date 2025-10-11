import pytest
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.unit
import ifcopenshell.util.element
from endrawing import DrawingGenerator


def create_building_with_units(schema="IFC4", length_unit="METRE", prefix=None):
    """Create minimal valid IFC file with specified units

    Args:
        schema: IFC schema version
        length_unit: Unit name (METRE, FOOT, INCH, etc.)
        prefix: Unit prefix (MILLI for millimeter, None for base unit)

    Returns:
        IFC file object
    """
    ifc = ifcopenshell.file(schema=schema)

    # Create project
    project = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject")
    project.Name = "Test Project"

    # Create units with specified length unit
    ifcopenshell.api.run(
        "unit.assign_unit",
        ifc,
        length={"is_metric": length_unit == "METRE" or length_unit == "MILLIMETRE", "raw": length_unit}
    )

    # Override with prefix if specified (for millimeters)
    if prefix:
        for unit in ifc.by_type("IfcSIUnit"):
            if unit.UnitType == "LENGTHUNIT":
                unit.Prefix = prefix

    # Add necessary contexts
    model = ifcopenshell.api.run("context.add_context", ifc, context_type="Model")
    body = ifcopenshell.api.run(
        "context.add_context",
        ifc,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model
    )

    # Add site
    site = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcSite")
    site.Name = "Test Site"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=project, products=[site])

    # Add building
    building = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding")
    building.Name = "Test Building"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=site, products=[building])

    # Add storey at ground level (z=0)
    storey = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuildingStorey")
    storey.Name = "Ground Floor"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=building, products=[storey])

    # Add placement to storey
    origin = ifc.createIfcCartesianPoint((0.0, 0.0, 0.0))
    axis_z = ifc.createIfcDirection((0.0, 0.0, 1.0))
    axis_x = ifc.createIfcDirection((1.0, 0.0, 0.0))
    placement_3d = ifc.createIfcAxis2Placement3D(origin, axis_z, axis_x)
    storey.ObjectPlacement = ifc.createIfcLocalPlacement(None, placement_3d)

    # Add walls with placements for bbox calculation
    # Wall positions will be in the project's native units
    wall1 = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcWall")
    wall1.Name = "Test Wall 1"
    ifcopenshell.api.run("spatial.assign_container", ifc, relating_structure=storey, products=[wall1])
    wall1_origin = ifc.createIfcCartesianPoint((1.0, 1.0, 0.0))
    wall1_placement_3d = ifc.createIfcAxis2Placement3D(wall1_origin, axis_z, axis_x)
    wall1.ObjectPlacement = ifc.createIfcLocalPlacement(storey.ObjectPlacement, wall1_placement_3d)

    wall2 = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcWall")
    wall2.Name = "Test Wall 2"
    ifcopenshell.api.run("spatial.assign_container", ifc, relating_structure=storey, products=[wall2])
    wall2_origin = ifc.createIfcCartesianPoint((10.0, 10.0, 3.0))
    wall2_placement_3d = ifc.createIfcAxis2Placement3D(wall2_origin, axis_z, axis_x)
    wall2.ObjectPlacement = ifc.createIfcLocalPlacement(storey.ObjectPlacement, wall2_placement_3d)

    return ifc


@pytest.fixture
def meters_ifc():
    """IFC file with meter units"""
    return create_building_with_units(length_unit="METRE", prefix=None)


@pytest.fixture
def millimeters_ifc():
    """IFC file with millimeter units"""
    return create_building_with_units(length_unit="METRE", prefix="MILLI")


@pytest.fixture
def feet_ifc():
    """IFC file with foot units"""
    return create_building_with_units(length_unit="FEET", prefix=None)


def test_unit_scale_meters(meters_ifc):
    """Test that meter projects have unit_scale = 1.0"""
    generator = DrawingGenerator(meters_ifc)
    assert generator.unit_scale == pytest.approx(1.0, rel=1e-6)


def test_unit_scale_millimeters(millimeters_ifc):
    """Test that millimeter projects have unit_scale = 0.001"""
    generator = DrawingGenerator(millimeters_ifc)
    assert generator.unit_scale == pytest.approx(0.001, rel=1e-6)


def test_unit_scale_feet(feet_ifc):
    """Test that foot projects have unit_scale ≈ 0.3048"""
    generator = DrawingGenerator(feet_ifc)
    assert generator.unit_scale == pytest.approx(0.3048, rel=1e-4)


def test_millimeters_camera_height(millimeters_ifc):
    """Test that camera height is correctly converted for millimeter projects

    In a millimeter project, 1.8m above floor should be 1800mm in project units.
    """
    generator = DrawingGenerator(millimeters_ifc)
    generator.generate_drawings()

    # Find the plan drawing (Ground Floor)
    plan_drawing = None
    for annotation in millimeters_ifc.by_type("IfcAnnotation"):
        if annotation.Name == "Ground Floor" and annotation.ObjectType == "DRAWING":
            plan_drawing = annotation
            break

    assert plan_drawing is not None, "No plan drawing found"

    # Get camera placement
    placement = plan_drawing.ObjectPlacement
    point = placement.RelativePlacement.Location
    z_position = point.Coordinates[2]

    # 1.8 meters = 1800 millimeters, floor is at z=0
    # So camera should be at 0 + 1800 = 1800mm
    expected_z = 0.0 + 1.8 / 0.001  # elevation + (1.8m in mm)
    assert z_position == pytest.approx(expected_z, rel=1e-3), \
        f"Camera height {z_position} doesn't match expected {expected_z}mm"


def test_feet_camera_height(feet_ifc):
    """Test that camera height is correctly converted for foot projects

    In a foot project, 1.8m above floor should be ≈5.9 feet in project units.
    """
    generator = DrawingGenerator(feet_ifc)
    generator.generate_drawings()

    # Find the plan drawing
    plan_drawing = None
    for annotation in feet_ifc.by_type("IfcAnnotation"):
        if annotation.Name == "Ground Floor" and annotation.ObjectType == "DRAWING":
            plan_drawing = annotation
            break

    assert plan_drawing is not None, "No plan drawing found"

    # Get camera placement
    placement = plan_drawing.ObjectPlacement
    point = placement.RelativePlacement.Location
    z_position = point.Coordinates[2]

    # 1.8 meters ≈ 5.906 feet
    expected_z = 0.0 + 1.8 / 0.3048  # elevation + (1.8m in feet)
    assert z_position == pytest.approx(expected_z, rel=1e-3), \
        f"Camera height {z_position} doesn't match expected {expected_z} feet"


def test_millimeters_bbox_padding(millimeters_ifc):
    """Test that bounding box padding is correctly converted for millimeter projects

    The 2 meter padding should become 2000mm in project units.
    """
    generator = DrawingGenerator(millimeters_ifc)

    # Walls are at (1,1,0) and (10,10,3) in mm
    # Bbox should be approximately 1 to 10 in each dimension
    # With 2m (2000mm) padding: dimensions should be about 9 + 2000 = 2009mm

    # Check that padding was applied (should be ~2000mm, not 2mm)
    assert generator.dim_all_x > 1000, \
        f"X dimension {generator.dim_all_x} too small - padding not applied correctly"
    assert generator.dim_all_y > 1000, \
        f"Y dimension {generator.dim_all_y} too small - padding not applied correctly"


def test_feet_bbox_padding(feet_ifc):
    """Test that drawings are generated successfully for foot projects

    This verifies that bounding box calculations don't crash for imperial units.
    """
    generator = DrawingGenerator(feet_ifc)
    generator.generate_drawings()

    # Check that drawings were created successfully
    annotations = feet_ifc.by_type("IfcAnnotation")
    assert len(annotations) > 0, "No drawings created for feet project"


def test_cross_unit_consistency(meters_ifc, millimeters_ifc):
    """Test that same real-world building produces proportional dimensions

    A building with walls at (1,1) and (10,10) in meters should have
    walls at (1000,1000) and (10000,10000) in millimeters.
    Camera heights should maintain the same ratio.
    """
    gen_m = DrawingGenerator(meters_ifc)
    gen_m.generate_drawings()

    gen_mm = DrawingGenerator(millimeters_ifc)
    gen_mm.generate_drawings()

    # Find plan drawings
    plan_m = None
    plan_mm = None

    for annotation in meters_ifc.by_type("IfcAnnotation"):
        if annotation.Name == "Ground Floor" and annotation.ObjectType == "DRAWING":
            plan_m = annotation
            break

    for annotation in millimeters_ifc.by_type("IfcAnnotation"):
        if annotation.Name == "Ground Floor" and annotation.ObjectType == "DRAWING":
            plan_mm = annotation
            break

    assert plan_m is not None and plan_mm is not None

    # Get camera Z positions
    z_m = plan_m.ObjectPlacement.RelativePlacement.Location.Coordinates[2]
    z_mm = plan_mm.ObjectPlacement.RelativePlacement.Location.Coordinates[2]

    # Ratio should be 1000:1 (mm to m conversion)
    ratio = z_mm / z_m
    assert ratio == pytest.approx(1000.0, rel=0.01), \
        f"Camera height ratio {ratio} doesn't match expected 1000:1"


def test_generates_valid_drawings_all_units(meters_ifc, millimeters_ifc, feet_ifc):
    """Test that drawings are successfully generated for all unit systems"""
    for ifc_file in [meters_ifc, millimeters_ifc, feet_ifc]:
        generator = DrawingGenerator(ifc_file)
        generator.generate_drawings()

        # Check drawings were created
        annotations = ifc_file.by_type("IfcAnnotation")
        assert len(annotations) > 0, "No drawings created"

        # Check our marker exists
        found_marker = False
        for annotation in annotations:
            psets = ifcopenshell.util.element.get_psets(annotation)
            if psets.get("EPset_Drawing", {}).get("GeneratedBy") == "endrawing":
                found_marker = True
                break

        assert found_marker, "No drawing found with GeneratedBy marker"
