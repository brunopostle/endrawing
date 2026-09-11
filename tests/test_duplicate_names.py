import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element
import ifcopenshell.util.selector
from endrawing import DrawingGenerator


def _make_twin_buildings():
    """Build a model with two buildings both named "Plot"

    Each has one storey, named "Ground A" and "Ground B", holding one wall.

    Returns:
        (ifc_file, [(building, storey, wall), ...]) tuple
    """
    ifc = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcProject")
    ifcopenshell.api.run("unit.assign_unit", ifc)
    model = ifcopenshell.api.run("context.add_context", ifc, context_type="Model")
    ifcopenshell.api.run(
        "context.add_context",
        ifc,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model,
    )
    site = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcSite")
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=project, products=[site])

    plots = []
    for suffix, x in (("A", 0.0), ("B", 50.0)):
        building = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding")
        building.Name = "Plot"
        ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=site, products=[building])
        storey = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuildingStorey")
        storey.Name = f"Ground {suffix}"
        ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=building, products=[storey])
        ifcopenshell.api.run("geometry.edit_object_placement", ifc, product=storey)
        wall = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcWall")
        ifcopenshell.api.run("spatial.assign_container", ifc, relating_structure=storey, products=[wall])
        ifcopenshell.api.run(
            "geometry.edit_object_placement",
            ifc,
            product=wall,
            matrix=[[1.0, 0.0, 0.0, x], [0.0, 1.0, 0.0, 1.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
        )
        plots.append((building, storey, wall))
    return ifc, plots


def test_buildings_sharing_a_name_keep_their_own_storeys():
    """Each building's sheet gets only its own storey plan (endrawing-12h)"""
    ifc, plots = _make_twin_buildings()

    DrawingGenerator(ifc).generate_drawings()

    plan_locations = {"drawings/Plot Ground A.svg", "drawings/Plot Ground B.svg"}
    sheets = sorted(
        (d for d in ifc.by_type("IfcDocumentInformation") if d.Scope == "SHEET"),
        key=lambda d: d.Identification,
    )
    plans = [sorted(r.Location for r in s.HasDocumentReferences if r.Location in plan_locations) for s in sheets]
    assert sorted(plans) == [["drawings/Plot Ground A.svg"], ["drawings/Plot Ground B.svg"]]


def test_include_filters_select_their_own_building():
    """Elevation and location plan Include filters select one building, not every "Plot" (endrawing-12h)"""
    ifc, plots = _make_twin_buildings()

    DrawingGenerator(ifc).generate_drawings()

    includes = [
        pset["Include"]
        for a in ifc.by_type("IfcAnnotation")
        if (pset := ifcopenshell.util.element.get_psets(a).get("EPset_Drawing", {})).get("GeneratedBy") == "endrawing"
        and "Include" in pset
    ]
    # Four elevations and a location plan per building
    assert len(includes) == 10
    walls = {wall for _, _, wall in plots}
    for include in includes:
        selected = ifcopenshell.util.selector.filter_elements(ifc, include) & walls
        assert len(selected) == 1, include


def test_plans_of_storeys_sharing_a_name_get_their_own_svg():
    """Plans are named "{building} {storey}", so each building's "Ground Floor" gets its own SVG (endrawing-fkb)"""
    ifc, plots = _make_twin_buildings()
    for (building, storey, _), name in zip(plots, ("North Block", "South Block")):
        building.Name = name
        storey.Name = "Ground Floor"

    DrawingGenerator(ifc).generate_drawings()

    locations = {
        a.Name: next(rel.RelatingDocument.Location for rel in a.HasAssociations if rel.is_a("IfcRelAssociatesDocument"))
        for a in ifc.by_type("IfcAnnotation")
        if a.ObjectType == "DRAWING" and a.Name.endswith("Ground Floor")
    }
    assert locations == {
        "North Block Ground Floor": "drawings/North Block Ground Floor.svg",
        "South Block Ground Floor": "drawings/South Block Ground Floor.svg",
    }
