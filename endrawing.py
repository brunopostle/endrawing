#!/usr/bin/python3

import sys
import ifcopenshell
import ifcopenshell.api as api
import ifcopenshell.api.context
import ifcopenshell.api.drawing
import ifcopenshell.api.group
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.geom
import ifcopenshell.util
import ifcopenshell.util.selector
import ifcopenshell.util.representation

# 2024 Bruno Postle <bruno@postle.net>
# License: SPDX:GPL-3.0-or-later


class Endrawing:
    def ensure_contexts(ifc_file):
        """create Annotation Context if it doesn't already exist"""
        model_context = ifcopenshell.util.representation.get_context(ifc_file, "Model")
        plan_context = ifcopenshell.util.representation.get_context(ifc_file, "Plan")
        if not plan_context:
            plan_context = ifc_file.createIfcGeometricRepresentationContext(
                None, "Plan", 2, None, model_context.WorldCoordinateSystem, None
            )
        annotation_context = ifcopenshell.util.representation.get_context(
            ifc_file, "Plan", subcontext="Annotation"
        )
        if not annotation_context:
            annotation_context = api.context.add_context(
                ifc_file,
                context_identifier="Annotation",
                context_type=plan_context.ContextType,
                parent=plan_context,
                target_view="PLAN_VIEW",
            )

    def get_bbox(ifc_file, spatial_element):
        """fast but probably not the best way of doing this"""
        bbox_min = []
        bbox_max = []

        items = ifcopenshell.util.selector.filter_elements(
            ifc_file, 'IfcElement, location="' + spatial_element.Name + '"'
        )
        for item in items:
            local_placement = ifcopenshell.util.placement.get_local_placement(
                item.ObjectPlacement
            )
            x = local_placement[0][3]
            y = local_placement[1][3]
            z = local_placement[2][3]
            if x == 0.0 or y == 0.0:
                continue
            if not bbox_min:
                bbox_min = [x, y, z]
                continue
            if not bbox_max:
                bbox_max = [x, y, z]
                continue
            if x < bbox_min[0]:
                bbox_min[0] = x
            if y < bbox_min[1]:
                bbox_min[1] = y
            if z < bbox_min[2]:
                bbox_min[2] = z
            if x > bbox_max[0]:
                bbox_max[0] = x
            if y > bbox_max[1]:
                bbox_max[1] = y
            if z > bbox_max[2]:
                bbox_max[2] = z
        bbox_mid = [
            (bbox_min[0] + bbox_max[0]) / 2,
            (bbox_min[1] + bbox_max[1]) / 2,
            (bbox_min[2] + bbox_max[2]) / 2,
        ]
        return (bbox_min, bbox_mid, bbox_max)

    def get_centroid(element):
        """again, probably not the best way to do this"""
        settings = ifcopenshell.geom.settings()
        element_shape = ifcopenshell.geom.create_shape(settings, element)
        verts = element_shape.geometry.verts
        no_verts = int(len(verts) / 3)
        x = 0.0
        y = 0.0
        z = 0.0
        for i in range(no_verts):
            x += verts[(i * 3)]
            y += verts[(i * 3) + 1]
            z += verts[(i * 3) + 2]
        x /= no_verts
        y /= no_verts
        z /= no_verts
        local_placement = ifcopenshell.util.placement.get_local_placement(
            element.ObjectPlacement
        )
        return [
            x + float(local_placement[0][3]),
            y + float(local_placement[1][3]),
            z + float(local_placement[2][3]),
        ]

    def create_camera_shape(ifc_file, x, y, z):
        body_context = ifcopenshell.util.representation.get_context(
            ifc_file, "Model", subcontext="Body"
        )
        placement = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint([x / -2, y / -2, float(-z)]),
            None,
            None,
        )
        solid = ifc_file.createIfcCSGSolid(ifc_file.createIfcBlock(placement, x, y, z))
        return ifc_file.createIfcProductDefinitionShape(
            None,
            None,
            [
                ifc_file.createIfcShapeRepresentation(
                    body_context, "Body", "CSG", [solid]
                )
            ],
        )

    def create_label_shape(ifc_file):
        annotation_context = ifcopenshell.util.representation.get_context(
            ifc_file, "Plan", subcontext="Annotation"
        )
        placement = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint([0.0, 0.0, 0.0]),
            ifc_file.createIfcDirection([0.0, 0.0, 1.0]),
            ifc_file.createIfcDirection([1.0, 0.0, 0.0]),
        )
        literal = ifc_file.createIfcTextLiteralWithExtent(
            "{{Name}}",
            placement,
            "RIGHT",
            ifc_file.createIfcPlanarExtent(1000.0, 1000.0),
            "center",
        )
        representation = ifc_file.createIfcShapeRepresentation(
            annotation_context, "Annotation", "Annotation2D", [literal]
        )
        return ifc_file.createIfcProductDefinitionShape(None, None, [representation])

    def create_epset_drawing(ifc_file, annotation, scale=50):
        scale = str(int(scale))
        pset = api.pset.add_pset(ifc_file, product=annotation, name="EPset_Drawing")
        api.pset.edit_pset(
            ifc_file,
            pset=pset,
            properties={
                "TargetView": "PLAN_VIEW",
                "Scale": "1/" + scale,
                "HumanScale": "1:" + scale,
                "HasUnderlay": False,
                "HasLinework": True,
                "HasAnnotation": True,
                "GlobalReferencing": True,
                "Stylesheet": "drawings/assets/default.css",
                "Markers": "drawings/assets/markers.svg",
                "Symbols": "drawings/assets/symbols.svg",
                "Patterns": "drawings/assets/patterns.svg",
                "ShadingStyles": "drawings/assets/shading_styles.json",
                "CurrentShadingStyle": "Blender Default",
            },
        )
        return pset

    def edit_pset_elevation(ifc_file, pset, building):
        api.pset.edit_pset(
            ifc_file,
            pset=pset,
            properties={
                "TargetView": "ELEVATION_VIEW",
                "Include": 'IfcTypeProduct, IfcProduct, location="'
                + building.Name
                + '"',
            },
        )

    def edit_pset_location(ifc_file, pset, x, y):
        api.pset.edit_pset(
            ifc_file,
            pset=pset,
            properties={
                "PositionX": float(x),
                "PositionY": float(y),
            },
        )

    def create_drawing_group(ifc_file, annotation):
        group = api.group.add_group(
            ifc_file,
        )
        api.group.edit_group(
            ifc_file,
            group=group,
            attributes={
                "Name": annotation.Name,
                "ObjectType": "DRAWING",
            },
        )
        api.group.assign_group(ifc_file, group=group, products=[annotation])
        return group

    def attach_sheet(ifc_file, annotation, sheet_info, drawing_id):
        info = ifc_file.createIfcDocumentInformation(
            annotation.Name,
            annotation.Name,
            None,
            None,
            None,
            None,
            "DRAWING",
        )
        # associate this drawing-annotation with the Project
        rel = api.root.create_entity(ifc_file, ifc_class="IfcRelAssociatesDocument")
        rel.RelatedObjects = ifc_file.by_type("IfcProject")
        rel.RelatingDocument = info

        # FIXME don't use unsanitised IFC data for filenames
        path_drawing = "drawings/" + annotation.Name + ".svg"
        # associate SVG with this drawing-annotation
        rel = api.root.create_entity(ifc_file, ifc_class="IfcRelAssociatesDocument")
        rel.RelatedObjects = [annotation]
        rel.RelatingDocument = ifc_file.createIfcDocumentReference(
            path_drawing, None, None, None, info
        )
        # place SVG in sheet
        # FIXME drawing_id not used?
        ifc_file.createIfcDocumentReference(
            path_drawing,
            str(drawing_id),
            None,
            "DRAWING",
            sheet_info,
        )

    def execute(ifc_file, scale=100, titleblock="A2"):
        """Assemble drawings for storeys and sheets for buildings"""
        Endrawing.ensure_contexts(ifc_file)
        unit_scale_mm = ifcopenshell.util.unit.calculate_unit_scale(ifc_file) * 1000.0

        sheet_id = 0
        for building in sorted(ifc_file.by_type("IfcBuilding"), key=lambda x: x.Name):

            # drawing sheet
            sheet_id += 1
            identification = "A" + str(sheet_id).zfill(4)

            sheet_info = ifc_file.createIfcDocumentInformation(
                identification,
                building.Name,
                "General Arrangement",
                None,
                None,
                None,
                "SHEET",
            )

            rel = api.root.create_entity(ifc_file, ifc_class="IfcRelAssociatesDocument")
            rel.RelatedObjects = ifc_file.by_type("IfcProject")
            rel.RelatingDocument = sheet_info

            # FIXME don't use unsanitised IFC data for filenames
            ifc_file.createIfcDocumentReference(
                "layouts/" + identification + " - " + building.Name + ".svg",
                None,
                None,
                "LAYOUT",
                sheet_info,
            )
            ifc_file.createIfcDocumentReference(
                "layouts/titleblocks/" + titleblock + ".svg",
                None,
                None,
                "TITLEBLOCK",
                sheet_info,
            )

            # size of building
            bbox_min, bbox_mid, bbox_max = Endrawing.get_bbox(ifc_file, building)
            dim_x = int(bbox_max[0] - bbox_min[0]) + 2
            dim_y = int(bbox_max[1] - bbox_min[1]) + 2
            dim_z = int(bbox_max[2] - bbox_min[2]) + 2

            storeys = {}
            for ifc_storey in ifcopenshell.util.selector.filter_elements(
                ifc_file, 'IfcBuildingStorey, location="' + building.Name + '"'
            ):
                local_placement = ifcopenshell.util.placement.get_local_placement(
                    ifc_storey.ObjectPlacement
                )
                storeys[local_placement[2][3]] = ifc_storey

            # TODO create a location plan from all bounding boxes, label just this building

            drawing_id = 0
            location_x = 30.0
            location_y = 30.0
            for elevation in sorted(list(storeys.keys())):
                storey = storeys[elevation]

                point = ifc_file.createIfcCartesianPoint(
                    [float(bbox_mid[0]), float(bbox_mid[1]), float(elevation + 1.8)]
                )
                local_placement = ifc_file.createIfcLocalPlacement(
                    None, ifc_file.createIfcAxis2Placement3D(point, None, None)
                )
                annotation = api.root.create_entity(ifc_file, ifc_class="IfcAnnotation")
                annotation.Name = storey.Name
                annotation.ObjectType = "DRAWING"
                annotation.ObjectPlacement = local_placement
                annotation.Representation = Endrawing.create_camera_shape(
                    ifc_file, dim_x, dim_y, 10.0
                )
                pset = Endrawing.create_epset_drawing(ifc_file, annotation, scale)
                api.pset.edit_pset(
                    ifc_file,
                    pset=pset,
                    properties={
                        "TargetView": "PLAN_VIEW",
                    },
                )
                Endrawing.edit_pset_location(ifc_file, pset, location_x, location_y)
                drawing_id += 1
                location_x += 10.0 + (dim_x * unit_scale_mm / scale)
                Endrawing.attach_sheet(ifc_file, annotation, sheet_info, drawing_id)
                group = Endrawing.create_drawing_group(ifc_file, annotation)

                if storey.IsDecomposedBy:
                    for space in storey.IsDecomposedBy[0].RelatedObjects:
                        # label all the spaces in this storey
                        centroid = Endrawing.get_centroid(space)
                        placement = ifc_file.createIfcLocalPlacement(
                            None,
                            ifc_file.createIfcAxis2Placement3D(
                                ifc_file.createIfcCartesianPoint(
                                    [centroid[0], centroid[1], float(elevation) + 0.1]
                                ),
                                ifc_file.createIfcDirection([0.0, 0.0, 1.0]),
                                ifc_file.createIfcDirection([1.0, 0.0, 0.0]),
                            ),
                        )

                        # room label
                        annotation = api.root.create_entity(
                            ifc_file, ifc_class="IfcAnnotation"
                        )
                        annotation.Name = "TEXT"
                        annotation.ObjectType = "TEXT"
                        annotation.ObjectPlacement = placement
                        annotation.Representation = Endrawing.create_label_shape(
                            ifc_file
                        )

                        api.group.assign_group(
                            ifc_file,
                            group=group,
                            products=[annotation],
                        )
                        api.drawing.assign_product(
                            ifc_file,
                            relating_product=space,
                            related_object=annotation,
                        )
                        pset = api.pset.add_pset(
                            ifc_file,
                            product=annotation,
                            name="EPset_Annotation",
                        )
                        api.pset.edit_pset(
                            ifc_file,
                            pset=pset,
                            properties={"Classes": "header"},
                        )

            location_x = 30.0
            location_y = 30.0 + 20.0 + (dim_y * unit_scale_mm / scale)

            # north elevation
            point = ifc_file.createIfcCartesianPoint(
                [float(bbox_mid[0]), float(bbox_max[1]) + 1.0, float(bbox_mid[2])]
            )
            local_placement = ifc_file.createIfcLocalPlacement(
                None,
                ifc_file.createIfcAxis2Placement3D(
                    point,
                    ifc_file.createIfcDirection([0.0, 1.0, 0.0]),
                    ifc_file.createIfcDirection([-1.0, 0.0, 0.0]),
                ),
            )
            annotation = api.root.create_entity(ifc_file, ifc_class="IfcAnnotation")
            annotation.Name = building.Name + " NORTH"
            annotation.ObjectType = "DRAWING"
            annotation.ObjectPlacement = local_placement
            annotation.Representation = Endrawing.create_camera_shape(
                ifc_file, dim_x, dim_z, dim_y
            )
            pset = Endrawing.create_epset_drawing(ifc_file, annotation, scale)
            Endrawing.edit_pset_elevation(ifc_file, pset, building)
            Endrawing.edit_pset_location(ifc_file, pset, location_x, location_y)
            drawing_id += 1
            location_x += 10.0 + (dim_x * unit_scale_mm / scale)
            Endrawing.attach_sheet(ifc_file, annotation, sheet_info, drawing_id)
            group = Endrawing.create_drawing_group(ifc_file, annotation)

            # south elevation
            point = ifc_file.createIfcCartesianPoint(
                [float(bbox_mid[0]), float(bbox_min[1]) - 1.0, float(bbox_mid[2])]
            )
            local_placement = ifc_file.createIfcLocalPlacement(
                None,
                ifc_file.createIfcAxis2Placement3D(
                    point,
                    ifc_file.createIfcDirection([0.0, -1.0, 0.0]),
                    ifc_file.createIfcDirection([1.0, 0.0, 0.0]),
                ),
            )
            annotation = api.root.create_entity(ifc_file, ifc_class="IfcAnnotation")
            annotation.Name = building.Name + " SOUTH"
            annotation.ObjectType = "DRAWING"
            annotation.ObjectPlacement = local_placement
            annotation.Representation = Endrawing.create_camera_shape(
                ifc_file, dim_x, dim_z, dim_y
            )
            pset = Endrawing.create_epset_drawing(ifc_file, annotation, scale)
            Endrawing.edit_pset_elevation(ifc_file, pset, building)
            Endrawing.edit_pset_location(ifc_file, pset, location_x, location_y)
            drawing_id += 1
            location_x += 10.0 + (dim_x * unit_scale_mm / scale)
            Endrawing.attach_sheet(ifc_file, annotation, sheet_info, drawing_id)
            group = Endrawing.create_drawing_group(ifc_file, annotation)

            # west elevation
            point = ifc_file.createIfcCartesianPoint(
                [float(bbox_min[0]) - 1.0, float(bbox_mid[1]), float(bbox_mid[2])]
            )
            local_placement = ifc_file.createIfcLocalPlacement(
                None,
                ifc_file.createIfcAxis2Placement3D(
                    point,
                    ifc_file.createIfcDirection([-1.0, 0.0, 0.0]),
                    ifc_file.createIfcDirection([0.0, -1.0, 0.0]),
                ),
            )
            annotation = api.root.create_entity(ifc_file, ifc_class="IfcAnnotation")
            annotation.Name = building.Name + " WEST"
            annotation.ObjectType = "DRAWING"
            annotation.ObjectPlacement = local_placement
            annotation.Representation = Endrawing.create_camera_shape(
                ifc_file, dim_y, dim_z, dim_x
            )
            pset = Endrawing.create_epset_drawing(ifc_file, annotation, scale)
            Endrawing.edit_pset_elevation(ifc_file, pset, building)
            Endrawing.edit_pset_location(ifc_file, pset, location_x, location_y)
            drawing_id += 1
            location_x += 10.0 + (dim_y * unit_scale_mm / scale)
            Endrawing.attach_sheet(ifc_file, annotation, sheet_info, drawing_id)
            group = Endrawing.create_drawing_group(ifc_file, annotation)

            # east elevation
            point = ifc_file.createIfcCartesianPoint(
                [float(bbox_max[0]) + 1.0, float(bbox_mid[1]), float(bbox_mid[2])]
            )
            local_placement = ifc_file.createIfcLocalPlacement(
                None,
                ifc_file.createIfcAxis2Placement3D(
                    point,
                    ifc_file.createIfcDirection([1.0, 0.0, 0.0]),
                    ifc_file.createIfcDirection([0.0, 1.0, 0.0]),
                ),
            )
            annotation = api.root.create_entity(ifc_file, ifc_class="IfcAnnotation")
            annotation.Name = building.Name + " EAST"
            annotation.ObjectType = "DRAWING"
            annotation.ObjectPlacement = local_placement
            annotation.Representation = Endrawing.create_camera_shape(
                ifc_file, dim_y, dim_z, dim_x
            )
            pset = Endrawing.create_epset_drawing(ifc_file, annotation, scale)
            Endrawing.edit_pset_elevation(ifc_file, pset, building)
            Endrawing.edit_pset_location(ifc_file, pset, location_x, location_y)
            drawing_id += 1
            location_x += 10.0 + (dim_y * unit_scale_mm / scale)
            Endrawing.attach_sheet(ifc_file, annotation, sheet_info, drawing_id)
            group = Endrawing.create_drawing_group(ifc_file, annotation)

            # FIXME add storey SECTION_LEVEL lines


if __name__ == "__main__":
    try:
        import blenderbim.tool
    except ImportError:
        if not len(sys.argv) == 3:
            print("Usage: " + sys.argv[0] + " input.ifc output.ifc")
        else:
            ifc_file = ifcopenshell.open(sys.argv[1])
            Endrawing.execute(ifc_file)
            ifc_file.write(sys.argv[2])
    else:
        # running in BlenderBIM
        Endrawing.execute(blenderbim.tool.Ifc.get())
