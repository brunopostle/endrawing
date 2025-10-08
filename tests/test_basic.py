import pytest
import ifcopenshell
import ifcopenshell.util.element
from endrawing import DrawingGenerator


def test_no_buildings_raises_error():
    """Test that files without buildings raise clear error"""
    # Create minimal IFC with no buildings
    ifc = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject")

    with pytest.raises(ValueError, match="No IfcBuilding"):
        DrawingGenerator(ifc)


def test_no_model_context_raises_error():
    """Test that files without Model context raise clear error"""
    # Create IFC with building but no Model context
    ifc = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject")
    building = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding")
    building.Name = "Test Building"

    with pytest.raises(ValueError, match="No Model context"):
        DrawingGenerator(ifc)


def test_generates_drawings(simple_building_ifc):
    """Test that drawings are created for valid building"""
    generator = DrawingGenerator(simple_building_ifc)
    generator.generate_drawings()

    # Check drawings were created
    annotations = simple_building_ifc.by_type("IfcAnnotation")
    assert len(annotations) > 0

    # Check our marker exists on at least one drawing
    found_marker = False
    for annotation in annotations:
        psets = ifcopenshell.util.element.get_psets(annotation)
        if psets.get("EPset_Drawing", {}).get("GeneratedBy") == "endrawing":
            found_marker = True
            break

    assert found_marker, "No drawing found with GeneratedBy marker"


def test_cleanup_removes_only_our_drawings(simple_building_ifc):
    """Test that cleanup only removes endrawing content"""
    # First run creates drawings
    generator = DrawingGenerator(simple_building_ifc)
    generator.generate_drawings()

    count_after_first = len(simple_building_ifc.by_type("IfcAnnotation"))
    groups_after_first = len(simple_building_ifc.by_type("IfcGroup"))
    sheets_after_first = len([d for d in simple_building_ifc.by_type("IfcDocumentInformation")
                              if hasattr(d, "Purpose") and d.Purpose == "General Arrangement"])

    assert count_after_first > 0, "No drawings created on first run"
    assert groups_after_first > 0, "No groups created on first run"
    assert sheets_after_first > 0, "No sheets created on first run"

    # Second run should cleanup and recreate (same counts)
    generator2 = DrawingGenerator(simple_building_ifc)
    generator2.generate_drawings()

    count_after_second = len(simple_building_ifc.by_type("IfcAnnotation"))
    groups_after_second = len(simple_building_ifc.by_type("IfcGroup"))
    sheets_after_second = len([d for d in simple_building_ifc.by_type("IfcDocumentInformation")
                               if hasattr(d, "Purpose") and d.Purpose == "General Arrangement"])

    assert count_after_second == count_after_first, \
        f"Drawing count changed: {count_after_first} -> {count_after_second}"
    assert groups_after_second == groups_after_first, \
        f"Group count changed: {groups_after_first} -> {groups_after_second}"
    assert sheets_after_second == sheets_after_first, \
        f"Sheet count changed: {sheets_after_first} -> {sheets_after_second}"


def test_custom_scale(simple_building_ifc):
    """Test that custom scale is applied"""
    generator = DrawingGenerator(simple_building_ifc, scale=50)
    generator.generate_drawings()

    # Check that at least one drawing has the custom scale
    found_scale = False
    for annotation in simple_building_ifc.by_type("IfcAnnotation"):
        psets = ifcopenshell.util.element.get_psets(annotation)
        if psets.get("EPset_Drawing", {}).get("Scale") == "1/50":
            found_scale = True
            break

    assert found_scale, "No drawing found with custom scale 1/50"


def test_custom_titleblock(simple_building_ifc):
    """Test that custom titleblock is referenced"""
    generator = DrawingGenerator(simple_building_ifc, titleblock="A1")
    generator.generate_drawings()

    # Check that sheet references the correct titleblock
    found_titleblock = False
    for doc_ref in simple_building_ifc.by_type("IfcDocumentReference"):
        if hasattr(doc_ref, "Location") and "A1.svg" in (doc_ref.Location or ""):
            found_titleblock = True
            break

    assert found_titleblock, "No sheet found referencing A1 titleblock"
