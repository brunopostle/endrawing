import pytest
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.owner.settings
import ifcopenshell.util.element
import ifcopenshell.util.representation
from endrawing import DrawingGenerator
from test_units import create_building_with_units


def _generated_drawings(ifc):
    return [
        a
        for a in ifc.by_type("IfcAnnotation")
        if ifcopenshell.util.element.get_psets(a).get("EPset_Drawing", {}).get("GeneratedBy") == "endrawing"
    ]


def _drawing_reference(drawing):
    return next(
        rel.RelatingDocument
        for rel in drawing.HasAssociations
        if rel.is_a("IfcRelAssociatesDocument")
    )


def _parents(ifc):
    documents = [d for d in ifc.by_type("IfcDocumentInformation") if d.Name == "DRAWINGS" and d.Scope == "DRAWINGS"]
    groups = [g for g in ifc.by_type("IfcGroup") if g.Name == "DRAWINGS" and g.ObjectType == "DRAWINGS"]
    return documents, groups


@pytest.fixture
def owner_history(monkeypatch):
    """IFC2X3 needs an owner history, and so a user and application, on rooted entities"""

    def get_user(ifc):
        for user in ifc.by_type("IfcPersonAndOrganization"):
            return user
        return ifc.createIfcPersonAndOrganization(ifc.createIfcPerson(), ifc.createIfcOrganization(None, "Test"))

    def get_application(ifc):
        for application in ifc.by_type("IfcApplication"):
            return application
        return ifc.createIfcApplication(get_user(ifc).TheOrganization, "0", "endrawing tests", "endrawing")

    monkeypatch.setattr(ifcopenshell.api.owner.settings, "get_user", get_user)
    monkeypatch.setattr(ifcopenshell.api.owner.settings, "get_application", get_application)


def test_drawings_nested_under_bonsai_parents(simple_building_ifc):
    """Drawing documents and groups sit under Bonsai's DRAWINGS parents (endrawing-e85)"""
    DrawingGenerator(simple_building_ifc).generate_drawings()

    [parent_document], [parent_group] = _parents(simple_building_ifc)
    drawings = _generated_drawings(simple_building_ifc)
    assert drawings

    nested = {d for rel in parent_document.IsPointer for d in rel.RelatedDocuments}
    grouped = {g for rel in parent_group.IsGroupedBy for g in rel.RelatedObjects}
    for drawing in drawings:
        information = _drawing_reference(drawing).ReferencedDocument
        assert information in nested
        assert information.Scope == "DRAWING"
        assert information.Name == drawing.Name
        # Nested documents aren't associated with the project directly
        assert not information.DocumentInfoForObjects
        group = next(rel.RelatingGroup for rel in drawing.HasAssignments if rel.is_a("IfcRelAssignsToGroup"))
        assert group in grouped


def test_bonsai_parents_reused_and_kept(simple_building_ifc):
    """Existing parents are reused, and a Bonsai drawing's document under them survives cleanup"""
    parent = ifcopenshell.api.document.add_information(simple_building_ifc)
    ifcopenshell.api.document.edit_information(
        simple_building_ifc,
        information=parent,
        attributes={"Identification": "DRAWINGS", "Name": "DRAWINGS", "Scope": "DRAWINGS"},
    )
    user_drawing = ifcopenshell.api.document.add_information(simple_building_ifc, parent=parent)
    ifcopenshell.api.document.edit_information(
        simple_building_ifc,
        information=user_drawing,
        attributes={"Identification": "X", "Name": "USER SECTION", "Scope": "DRAWING"},
    )

    for _ in range(2):
        DrawingGenerator(simple_building_ifc).generate_drawings()

    documents, groups = _parents(simple_building_ifc)
    assert documents == [parent]
    assert len(groups) == 1
    nested = {d for rel in parent.IsPointer for d in rel.RelatedDocuments}
    assert user_drawing in nested
    assert len(nested) == len(_generated_drawings(simple_building_ifc)) + 1


def test_plan_context_registered_with_project(simple_building_ifc):
    """A Plan context created by endrawing is one of the project's contexts"""
    DrawingGenerator(simple_building_ifc)

    plan = ifcopenshell.util.representation.get_context(simple_building_ifc, "Plan")
    project = simple_building_ifc.by_type("IfcProject")[0]
    assert plan in project.RepresentationContexts


def test_ifc2x3(owner_history, tmp_path):
    """IFC2X3 models get drawings and sheets, using IFC2X3 attribute names (endrawing-f7g)"""
    ifc = create_building_with_units(schema="IFC2X3")

    for _ in range(2):
        DrawingGenerator(ifc).generate_drawings()

    [sheet] = [d for d in ifc.by_type("IfcDocumentInformation") if d.Scope == "SHEET"]
    assert sheet.DocumentId == "A001"
    assert sheet.Purpose == "General Arrangement"
    roles = sorted(r.Name for r in sheet.DocumentReferences)
    drawings = _generated_drawings(ifc)
    assert roles == sorted(["LAYOUT", "TITLEBLOCK"] + ["DRAWING"] * len(drawings))

    for drawing in drawings:
        reference = _drawing_reference(drawing)
        [information] = reference.ReferenceToDocument
        assert information.Name == drawing.Name
        assert information.Scope == "DRAWING"

    path = tmp_path / "ifc2x3.ifc"
    ifc.write(str(path))
    assert len(_generated_drawings(ifcopenshell.open(str(path)))) == len(drawings)
