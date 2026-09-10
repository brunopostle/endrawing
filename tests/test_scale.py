import pytest
import ifcopenshell.api
import ifcopenshell.util.element
from endrawing import DrawingGenerator
from test_units import create_building_with_units


def _drawing_scales(ifc):
    """Get {drawing name: (Scale, HumanScale)} for endrawing's drawings"""
    return {
        a.Name: (pset["Scale"], pset["HumanScale"])
        for a in ifc.by_type("IfcAnnotation")
        if (pset := ifcopenshell.util.element.get_psets(a).get("EPset_Drawing", {})).get("GeneratedBy") == "endrawing"
    }


@pytest.mark.parametrize("prefix", [None, "MILLI"])
def test_metric_default_scale(prefix):
    """Metric projects default to 1:100"""
    ifc = create_building_with_units(length_unit="METRE", prefix=prefix)

    DrawingGenerator(ifc).generate_drawings()

    assert set(_drawing_scales(ifc).values()) == {("1/100", "1:100")}


def test_imperial_default_scale():
    """Imperial projects default to 1/8"=1'-0", like Bonsai (endrawing-cr4)"""
    ifc = create_building_with_units(length_unit="FEET")

    DrawingGenerator(ifc).generate_drawings()

    assert set(_drawing_scales(ifc).values()) == {("1/96", '1/8"=1\'-0"')}


@pytest.mark.parametrize(
    "scale, human_scale",
    [(48, '1/4"=1\'-0"'), (240, "1\"=20'"), (100, "1:100")],
)
def test_imperial_custom_scale(scale, human_scale):
    """Imperial scales use architectural or engineering notation where Bonsai has one"""
    ifc = create_building_with_units(length_unit="FEET")

    DrawingGenerator(ifc, scale=scale).generate_drawings()

    assert set(_drawing_scales(ifc).values()) == {(f"1/{scale}", human_scale)}


def test_imperial_location_plan_scale():
    """The location plan is ten times the drawing scale: 1/960 is 1"=80'"""
    ifc = create_building_with_units(length_unit="FEET")
    site = ifc.by_type("IfcSite")[0]
    other = ifcopenshell.api.run("root.create_entity", ifc, ifc_class="IfcBuilding")
    other.Name = "Other Building"
    ifcopenshell.api.run("aggregate.assign_object", ifc, relating_object=site, products=[other])

    DrawingGenerator(ifc).generate_drawings()

    scales = _drawing_scales(ifc)
    locations = {scale for name, scale in scales.items() if name.endswith(" LOCATION")}
    assert locations == {("1/960", "1\"=80'")}
