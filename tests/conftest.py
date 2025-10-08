import pytest
import ifcopenshell
import ifcopenshell.api


@pytest.fixture
def simple_building_ifc():
    """Create minimal valid IFC file with one building and storey"""
    ifc = ifcopenshell.file(schema="IFC4")

    # Create project
    project = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject")
    project.Name = "Test Project"

    # Create units
    ifcopenshell.api.run("unit.assign_unit", ifc)

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

    # Add storey
    storey = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuildingStorey")
    storey.Name = "Ground Floor"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=building, products=[storey])

    # Add placement to storey (required for endrawing)
    origin = ifc.createIfcCartesianPoint((0.0, 0.0, 0.0))
    axis_z = ifc.createIfcDirection((0.0, 0.0, 1.0))
    axis_x = ifc.createIfcDirection((1.0, 0.0, 0.0))
    placement_3d = ifc.createIfcAxis2Placement3D(origin, axis_z, axis_x)
    storey.ObjectPlacement = ifc.createIfcLocalPlacement(None, placement_3d)

    # Add walls with placements for bbox calculation (need at least 2 for min/max)
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
