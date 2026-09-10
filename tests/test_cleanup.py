import pytest
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element
from endrawing import DrawingGenerator


def test_cleanup_preserves_manual_drawings(simple_building_ifc):
    """Test that manually created drawings without GeneratedBy are preserved"""
    # Create a manual drawing (no GeneratedBy marker)
    manual_annotation = ifcopenshell.api.run(
        "root.create_entity", simple_building_ifc, ifc_class="IfcAnnotation"
    )
    manual_annotation.Name = "Manual Drawing"
    manual_annotation.ObjectType = "DRAWING"

    # Run endrawing
    generator = DrawingGenerator(simple_building_ifc)
    generator.generate_drawings()

    # Manual annotation should still exist
    annotations = [a for a in simple_building_ifc.by_type("IfcAnnotation") if a.Name == "Manual Drawing"]
    assert len(annotations) == 1, "Manual drawing was incorrectly removed"


def test_cleanup_handles_missing_psets(simple_building_ifc):
    """Test cleanup handles annotations without property sets gracefully"""
    # Create annotation with no psets
    orphan_annotation = ifcopenshell.api.run(
        "root.create_entity", simple_building_ifc, ifc_class="IfcAnnotation"
    )
    orphan_annotation.Name = "Orphan"
    orphan_annotation.ObjectType = "DRAWING"

    # Should not crash
    generator = DrawingGenerator(simple_building_ifc)
    generator.generate_drawings()

    # Should complete successfully
    our_drawings = [a for a in simple_building_ifc.by_type("IfcAnnotation")
                    if ifcopenshell.util.element.get_psets(a).get("EPset_Drawing", {}).get("GeneratedBy") == "endrawing"]
    assert len(our_drawings) > 0, "No endrawing drawings created"


def test_multiple_cleanup_cycles(simple_building_ifc):
    """Test that multiple cleanup cycles don't cause issues"""
    # Run generation 3 times
    for i in range(3):
        generator = DrawingGenerator(simple_building_ifc)
        generator.generate_drawings()

    # Final count should be stable
    final_count = len(simple_building_ifc.by_type("IfcAnnotation"))
    final_groups = len(simple_building_ifc.by_type("IfcGroup"))

    # One more time should give same count
    generator = DrawingGenerator(simple_building_ifc)
    generator.generate_drawings()

    assert len(simple_building_ifc.by_type("IfcAnnotation")) == final_count
    assert len(simple_building_ifc.by_type("IfcGroup")) == final_groups


def test_cleanup_removes_all_endrawing_entities(simple_building_ifc):
    """Test that cleanup removes drawings, groups, and sheets"""
    # First run
    generator = DrawingGenerator(simple_building_ifc)
    generator.generate_drawings()

    # Verify we created all entity types
    our_drawings = [a for a in simple_building_ifc.by_type("IfcAnnotation")
                    if ifcopenshell.util.element.get_psets(a).get("EPset_Drawing", {}).get("GeneratedBy") == "endrawing"]
    our_groups = [g for g in simple_building_ifc.by_type("IfcGroup") if g.ObjectType == "DRAWING"]
    our_sheets = [d for d in simple_building_ifc.by_type("IfcDocumentInformation")
                  if hasattr(d, "Purpose") and d.Purpose == "General Arrangement"]

    assert len(our_drawings) > 0, "No drawings created"
    assert len(our_groups) > 0, "No groups created"
    assert len(our_sheets) > 0, "No sheets created"

    # Manually clean and verify all removed
    generator2 = DrawingGenerator(simple_building_ifc)
    generator2.cleanup_existing_drawings()

    # After cleanup, should have none of our entities (before regeneration)
    remaining_drawings = [a for a in simple_building_ifc.by_type("IfcAnnotation")
                         if ifcopenshell.util.element.get_psets(a).get("EPset_Drawing", {}).get("GeneratedBy") == "endrawing"]
    remaining_groups = [g for g in simple_building_ifc.by_type("IfcGroup")
                       if g.ObjectType == "DRAWING"]
    remaining_sheets = [d for d in simple_building_ifc.by_type("IfcDocumentInformation")
                       if hasattr(d, "Purpose") and d.Purpose == "General Arrangement"]

    assert len(remaining_drawings) == 0, f"Cleanup left {len(remaining_drawings)} drawings"
    assert len(remaining_groups) == 0, f"Cleanup left {len(remaining_groups)} groups"
    assert len(remaining_sheets) == 0, f"Cleanup left {len(remaining_sheets)} sheets"


def _add_user_sheet(ifc, drawing_locations, purpose="General Arrangement"):
    """Add a sheet made by the user, holding drawings at the given locations"""
    sheet = ifcopenshell.api.document.add_information(ifc)
    ifcopenshell.api.document.edit_information(
        ifc,
        information=sheet,
        attributes={"Identification": "GA-101", "Name": "User GA", "Purpose": purpose, "Scope": "SHEET"},
    )
    for i, location in enumerate(drawing_locations):
        reference = ifcopenshell.api.document.add_reference(ifc, information=sheet)
        ifcopenshell.api.document.edit_reference(
            ifc,
            reference=reference,
            attributes={"Location": location, "Identification": str(i + 1), "Description": "DRAWING"},
        )
    return sheet


def _sheets(ifc, identification):
    return [d for d in ifc.by_type("IfcDocumentInformation") if d.Identification == identification]


def test_cleanup_preserves_user_general_arrangement_sheet(simple_building_ifc):
    """A user's sheet with the same Purpose, holding the user's drawing, survives (endrawing-6yk)"""
    _add_user_sheet(simple_building_ifc, ["drawings/USER PLAN.svg"])

    for _ in range(2):
        DrawingGenerator(simple_building_ifc).generate_drawings()

    sheets = _sheets(simple_building_ifc, "GA-101")
    assert len(sheets) == 1, "User sheet was removed"
    assert [r.Location for r in sheets[0].HasDocumentReferences] == ["drawings/USER PLAN.svg"]


def test_cleanup_preserves_empty_user_sheet(simple_building_ifc):
    """A user's General Arrangement sheet with no drawings yet survives"""
    _add_user_sheet(simple_building_ifc, [])

    for _ in range(2):
        DrawingGenerator(simple_building_ifc).generate_drawings()

    assert len(_sheets(simple_building_ifc, "GA-101")) == 1


def test_cleanup_preserves_sheet_mixing_user_and_generated_drawings(simple_building_ifc):
    """A sheet holding a generated drawing and a user drawing belongs to the user"""
    DrawingGenerator(simple_building_ifc).generate_drawings()
    _add_user_sheet(simple_building_ifc, ["drawings/Ground Floor.svg", "drawings/USER PLAN.svg"])

    DrawingGenerator(simple_building_ifc).generate_drawings()

    sheets = _sheets(simple_building_ifc, "GA-101")
    assert len(sheets) == 1
    assert len(sheets[0].HasDocumentReferences) == 2
    assert len(_sheets(simple_building_ifc, "A001")) == 1


def test_repeated_runs_leave_no_orphans(simple_building_ifc):
    """Drawing documents and references are removed with their drawings"""
    DrawingGenerator(simple_building_ifc).generate_drawings()
    count = len(list(simple_building_ifc))
    documents = len(simple_building_ifc.by_type("IfcDocumentInformation"))

    DrawingGenerator(simple_building_ifc).generate_drawings()

    assert len(simple_building_ifc.by_type("IfcDocumentInformation")) == documents
    assert len(list(simple_building_ifc)) == count


def test_file_writes_successfully_after_cleanup(simple_building_ifc, tmp_path):
    """Test that IFC file can be written after cleanup without corruption"""
    # Generate drawings twice (triggers cleanup)
    for _ in range(2):
        generator = DrawingGenerator(simple_building_ifc)
        generator.generate_drawings()

    # Write to file
    output_path = tmp_path / "test_cleanup.ifc"
    simple_building_ifc.write(str(output_path))

    # Should be able to reopen
    reopened = ifcopenshell.open(str(output_path))
    assert reopened is not None

    # Check drawings are valid
    annotations = reopened.by_type("IfcAnnotation")
    assert len(annotations) > 0, "No drawings in written file"

    # Check at least one has our marker
    found_marker = False
    for ann in annotations:
        psets = ifcopenshell.util.element.get_psets(ann)
        if psets.get("EPset_Drawing", {}).get("GeneratedBy") == "endrawing":
            found_marker = True
            break
    assert found_marker, "No marked drawings found in reopened file"
