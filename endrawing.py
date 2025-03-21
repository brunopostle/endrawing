#!/usr/bin/python3

import sys
from natsort import natsorted
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
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# 2024 Bruno Postle <bruno@postle.net>
# License: SPDX:GPL-3.0-or-later

"""
Generate General Arrangement drawings for IFC buildings. Each building gets a
sheet with plans and north, south, east and west elevations.

Either run on the command-line:

    endrawing.py infile.ifc outfile.ifc

..or within Bonsai BIM: Load the script in the Blender Text Editor and 'run'
(only once!).

Then in Bonsai BIM generate all the drawings before generating the sheets.
"""


class ContextManager:
    """Manages IFC context creation and retrieval"""

    @staticmethod
    def ensure_contexts(ifc_file):
        """Create Annotation Context if it doesn't already exist

        Args:
            ifc_file: The IFC file

        Returns:
            Dictionary of contexts
        """
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

        return {
            "model": model_context,
            "plan": plan_context,
            "annotation": annotation_context,
        }


class GeometryUtils:
    """Utility functions for geometry operations"""

    @staticmethod
    def get_bbox(ifc_file, spatial_elements):
        """Calculate bounding box for spatial elements

        Args:
            ifc_file: The IFC file
            spatial_elements: List of spatial elements

        Returns:
            Tuple of (min_point, mid_point, max_point)
        """
        bbox_min = []
        bbox_max = []

        for spatial_element in spatial_elements:
            items = ifcopenshell.util.selector.filter_elements(
                ifc_file, f'IfcElement, location="{spatial_element.Name}"'
            )

            for item in items:
                local_placement = ifcopenshell.util.placement.get_local_placement(
                    item.ObjectPlacement
                )
                x, y, z = (
                    local_placement[0][3],
                    local_placement[1][3],
                    local_placement[2][3],
                )

                if x == 0.0 or y == 0.0:
                    continue

                if not bbox_min:
                    bbox_min = [x, y, z]
                    continue

                if not bbox_max:
                    bbox_max = [x, y, z]
                    continue

                bbox_min[0] = min(bbox_min[0], x)
                bbox_min[1] = min(bbox_min[1], y)
                bbox_min[2] = min(bbox_min[2], z)

                bbox_max[0] = max(bbox_max[0], x)
                bbox_max[1] = max(bbox_max[1], y)
                bbox_max[2] = max(bbox_max[2], z)

        # Calculate midpoint
        bbox_mid = [
            (bbox_min[0] + bbox_max[0]) / 2,
            (bbox_min[1] + bbox_max[1]) / 2,
            (bbox_min[2] + bbox_max[2]) / 2,
        ]

        return (bbox_min, bbox_mid, bbox_max)

    @staticmethod
    def get_centroid(element):
        """Calculate centroid of an element

        Args:
            element: The IFC element

        Returns:
            List [x, y, z] of centroid coordinates
        """
        settings = ifcopenshell.geom.settings()
        element_shape = ifcopenshell.geom.create_shape(settings, element)
        verts = element_shape.geometry.verts
        no_verts = int(len(verts) / 3)

        x, y, z = 0.0, 0.0, 0.0
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


class ShapeCreator:
    """Creates IFC shape representations"""

    @staticmethod
    def create_camera_shape(ifc_file, x, y, z):
        """Create a camera shape representation

        Args:
            ifc_file: The IFC file
            x, y, z: Dimensions

        Returns:
            IfcProductDefinitionShape
        """
        body_context = ifcopenshell.util.representation.get_context(
            ifc_file, "Model", subcontext="Body"
        )

        placement = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint([float(x / -2), float(y / -2), float(-z)]),
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

    @staticmethod
    def create_label_shape(ifc_file):
        """Create a text label shape representation

        Args:
            ifc_file: The IFC file

        Returns:
            IfcProductDefinitionShape
        """
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


class DrawingGenerator:
    """Main drawing generation class"""

    def __init__(self, ifc_file, scale=100, titleblock="A2"):
        """Initialize the drawing generator

        Args:
            ifc_file: The IFC file
            scale: Drawing scale denominator (default 100)
            titleblock: Titleblock size (default "A2")
        """
        self.ifc_file = ifc_file
        self.scale = scale
        self.titleblock = titleblock
        self.contexts = ContextManager.ensure_contexts(ifc_file)
        self.unit_scale_mm = (
            ifcopenshell.util.unit.calculate_unit_scale(ifc_file) * 1000.0
        )

        # Calculate overall bounding box for site plan
        self.buildings = natsorted(
            ifc_file.by_type("IfcBuilding"), key=lambda x: x.Name
        )
        self.bbox_all = GeometryUtils.get_bbox(ifc_file, self.buildings)
        self.bbox_all_min, self.bbox_all_mid, self.bbox_all_max = self.bbox_all

        # Calculate dimensions
        self.dim_all_x = self.bbox_all_max[0] - self.bbox_all_min[0] + 2
        self.dim_all_y = self.bbox_all_max[1] - self.bbox_all_min[1] + 2
        self.dim_all_z = self.bbox_all_max[2] - self.bbox_all_min[2] + 2

    def create_drawing_pset(self, annotation, scale=50):
        """Create EPset_Drawing property set

        Args:
            annotation: The annotation element
            scale: Drawing scale denominator

        Returns:
            The created property set
        """
        scale_str = str(int(scale))
        pset = api.pset.add_pset(
            self.ifc_file, product=annotation, name="EPset_Drawing"
        )

        api.pset.edit_pset(
            self.ifc_file,
            pset=pset,
            properties={
                "TargetView": "PLAN_VIEW",
                "Scale": f"1/{scale_str}",
                "HumanScale": f"1:{scale_str}",
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

    def set_elevation_properties(self, pset, building):
        """Set elevation view properties

        Args:
            pset: The property set
            building: The building element
        """
        api.pset.edit_pset(
            self.ifc_file,
            pset=pset,
            properties={
                "TargetView": "ELEVATION_VIEW",
                "Include": f'IfcTypeProduct, IfcProduct, location="{building.Name}"',
            },
        )

    def create_drawing_group(self, annotation):
        """Create a drawing group

        Args:
            annotation: The annotation element

        Returns:
            The created group
        """
        group = api.group.add_group(self.ifc_file)

        api.group.edit_group(
            self.ifc_file,
            group=group,
            attributes={
                "Name": annotation.Name,
                "ObjectType": "DRAWING",
            },
        )

        api.group.assign_group(self.ifc_file, group=group, products=[annotation])

        return group

    def attach_sheet(self, annotation, sheet_info, drawing_id):
        """Attach a drawing to a sheet

        Args:
            annotation: The annotation element
            sheet_info: Sheet document information
            drawing_id: Drawing ID
        """
        info = self.ifc_file.createIfcDocumentInformation(
            annotation.Name,
            annotation.Name,
            None,
            None,
            None,
            None,
            "DRAWING",
        )

        # Associate this drawing-annotation with the Project
        rel = api.root.create_entity(
            self.ifc_file, ifc_class="IfcRelAssociatesDocument"
        )
        rel.RelatedObjects = self.ifc_file.by_type("IfcProject")
        rel.RelatingDocument = info

        # Generate path for drawing SVG
        path_drawing = f"drawings/{annotation.Name}.svg"

        # Associate SVG with this drawing-annotation
        rel = api.root.create_entity(
            self.ifc_file, ifc_class="IfcRelAssociatesDocument"
        )
        rel.RelatedObjects = [annotation]
        rel.RelatingDocument = self.ifc_file.createIfcDocumentReference(
            path_drawing, None, None, None, info
        )

        # Place SVG in sheet
        self.ifc_file.createIfcDocumentReference(
            path_drawing,
            str(drawing_id),
            None,
            "DRAWING",
            sheet_info,
        )

    def create_sheet_info(self, identification, building_name):
        """Create sheet document information

        Args:
            identification: Sheet identifier
            building_name: Building name

        Returns:
            IfcDocumentInformation
        """
        sheet_info = self.ifc_file.createIfcDocumentInformation(
            identification,
            building_name,
            "General Arrangement",
            None,
            None,
            None,
            "SHEET",
        )

        rel = api.root.create_entity(
            self.ifc_file, ifc_class="IfcRelAssociatesDocument"
        )
        rel.RelatedObjects = self.ifc_file.by_type("IfcProject")
        rel.RelatingDocument = sheet_info

        # Create document references
        self.ifc_file.createIfcDocumentReference(
            f"layouts/{identification} - {building_name}.svg",
            None,
            None,
            "LAYOUT",
            sheet_info,
        )

        self.ifc_file.createIfcDocumentReference(
            f"layouts/titleblocks/{self.titleblock}.svg",
            None,
            None,
            "TITLEBLOCK",
            sheet_info,
        )

        return sheet_info

    def create_plan_drawing(
        self,
        storey,
        building_bbox,
        scale,
        sheet_info,
        drawing_id,
    ):
        """Create a plan drawing for a storey

        Args:
            storey: The building storey
            building_bbox: Building bounding box tuple
            scale: Drawing scale
            sheet_info: Sheet document information
            drawing_id: Drawing ID

        Returns:
            Tuple of (new_drawing_id, annotation, group)
        """
        bbox_min, bbox_mid, bbox_max = building_bbox
        dim_x = bbox_max[0] - bbox_min[0] + 2
        dim_y = bbox_max[1] - bbox_min[1] + 2

        # Get elevation from storey placement
        local_placement = ifcopenshell.util.placement.get_local_placement(
            storey.ObjectPlacement
        )
        elevation = local_placement[2][3]

        # Create camera position
        point = self.ifc_file.createIfcCartesianPoint(
            [float(bbox_mid[0]), float(bbox_mid[1]), float(elevation + 1.8)]
        )

        local_placement = self.ifc_file.createIfcLocalPlacement(
            None, self.ifc_file.createIfcAxis2Placement3D(point, None, None)
        )

        # Create annotation
        annotation = api.root.create_entity(self.ifc_file, ifc_class="IfcAnnotation")
        annotation.Name = storey.Name
        annotation.ObjectType = "DRAWING"
        annotation.ObjectPlacement = local_placement
        annotation.Representation = ShapeCreator.create_camera_shape(
            self.ifc_file, dim_x, dim_y, 10.0
        )

        # Create property set
        pset = self.create_drawing_pset(annotation, scale)
        api.pset.edit_pset(
            self.ifc_file,
            pset=pset,
            properties={
                "TargetView": "PLAN_VIEW",
            },
        )

        # Attach to sheet
        self.attach_sheet(annotation, sheet_info, drawing_id)

        # Create group
        group = self.create_drawing_group(annotation)

        # Update drawing ID and position for next drawing
        drawing_id += 1
        return drawing_id, annotation, group

    def create_space_labels(self, storey, elevation, group):
        """Create labels for spaces in a storey

        Args:
            storey: The building storey
            elevation: Elevation value
            group: Drawing group
        """
        if not storey.IsDecomposedBy:
            return

        for space in storey.IsDecomposedBy[0].RelatedObjects:
            # Get space centroid
            centroid = GeometryUtils.get_centroid(space)

            # Create placement
            placement = self.ifc_file.createIfcLocalPlacement(
                None,
                self.ifc_file.createIfcAxis2Placement3D(
                    self.ifc_file.createIfcCartesianPoint(
                        [centroid[0], centroid[1], float(elevation) + 0.1]
                    ),
                    self.ifc_file.createIfcDirection([0.0, 0.0, 1.0]),
                    self.ifc_file.createIfcDirection([1.0, 0.0, 0.0]),
                ),
            )

            # Create room label annotation
            annotation = api.root.create_entity(
                self.ifc_file, ifc_class="IfcAnnotation"
            )
            annotation.Name = "TEXT"
            annotation.ObjectType = "TEXT"
            annotation.ObjectPlacement = placement
            annotation.Representation = ShapeCreator.create_label_shape(self.ifc_file)

            # Add to group and assign to space
            api.group.assign_group(
                self.ifc_file,
                group=group,
                products=[annotation],
            )

            api.drawing.assign_product(
                self.ifc_file,
                relating_product=space,
                related_object=annotation,
            )

            # Add properties
            pset = api.pset.add_pset(
                self.ifc_file,
                product=annotation,
                name="EPset_Annotation",
            )

            api.pset.edit_pset(
                self.ifc_file,
                pset=pset,
                properties={"Classes": "header"},
            )

    def create_elevation_drawing(
        self,
        building,
        building_bbox,
        direction,
        sheet_info,
        drawing_id,
    ):
        """Create an elevation drawing

        Args:
            building: The building element
            building_bbox: Building bounding box tuple
            direction: Elevation direction ("NORTH", "SOUTH", "EAST", "WEST")
            sheet_info: Sheet document information
            drawing_id: Drawing ID

        Returns:
            new_drawing_id
        """
        bbox_min, bbox_mid, bbox_max = building_bbox
        dim_x = bbox_max[0] - bbox_min[0] + 2
        dim_y = bbox_max[1] - bbox_min[1] + 2
        dim_z = bbox_max[2] - bbox_min[2] + 2

        # Set up direction-specific parameters
        if direction == "NORTH":
            point = self.ifc_file.createIfcCartesianPoint(
                [float(bbox_mid[0]), float(bbox_max[1]) + 0.5, float(bbox_mid[2])]
            )
            axis_dir = self.ifc_file.createIfcDirection([0.0, 1.0, 0.0])
            ref_dir = self.ifc_file.createIfcDirection([-1.0, 0.0, 0.0])
            camera_dims = (dim_x, dim_z, dim_y - 1.0)

        elif direction == "SOUTH":
            point = self.ifc_file.createIfcCartesianPoint(
                [float(bbox_mid[0]), float(bbox_min[1]) - 0.5, float(bbox_mid[2])]
            )
            axis_dir = self.ifc_file.createIfcDirection([0.0, -1.0, 0.0])
            ref_dir = self.ifc_file.createIfcDirection([1.0, 0.0, 0.0])
            camera_dims = (dim_x, dim_z, dim_y - 1.0)

        elif direction == "WEST":
            point = self.ifc_file.createIfcCartesianPoint(
                [float(bbox_min[0]) - 0.5, float(bbox_mid[1]), float(bbox_mid[2])]
            )
            axis_dir = self.ifc_file.createIfcDirection([-1.0, 0.0, 0.0])
            ref_dir = self.ifc_file.createIfcDirection([0.0, -1.0, 0.0])
            camera_dims = (dim_y, dim_z, dim_x - 1.0)

        elif direction == "EAST":
            point = self.ifc_file.createIfcCartesianPoint(
                [float(bbox_max[0]) + 0.5, float(bbox_mid[1]), float(bbox_mid[2])]
            )
            axis_dir = self.ifc_file.createIfcDirection([1.0, 0.0, 0.0])
            ref_dir = self.ifc_file.createIfcDirection([0.0, 1.0, 0.0])
            camera_dims = (dim_y, dim_z, dim_x - 1.0)

        # Create placement
        local_placement = self.ifc_file.createIfcLocalPlacement(
            None,
            self.ifc_file.createIfcAxis2Placement3D(point, axis_dir, ref_dir),
        )

        # Create annotation
        annotation = api.root.create_entity(self.ifc_file, ifc_class="IfcAnnotation")
        annotation.Name = f"{building.Name} {direction}"
        annotation.ObjectType = "DRAWING"
        annotation.ObjectPlacement = local_placement
        annotation.Representation = ShapeCreator.create_camera_shape(
            self.ifc_file, camera_dims[0], camera_dims[1], camera_dims[2]
        )

        # Create property set
        pset = self.create_drawing_pset(annotation, self.scale)
        self.set_elevation_properties(pset, building)

        # Attach to sheet
        self.attach_sheet(annotation, sheet_info, drawing_id)

        # Create group
        self.create_drawing_group(annotation)

        # Update drawing ID and position for next drawing
        drawing_id += 1

        return drawing_id

    def create_location_plan(
        self, building, sheet_info, drawing_id
    ):
        """Create a location plan drawing

        Args:
            building: The building element
            sheet_info: Sheet document information
            drawing_id: Drawing ID

        Returns:
            new_drawing_id
        """
        # Create point at center of all buildings, above max height
        point = self.ifc_file.createIfcCartesianPoint(
            [
                float(self.bbox_all_mid[0]),
                float(self.bbox_all_mid[1]),
                float(self.bbox_all_max[2] + 1.0),
            ]
        )

        # Create placement
        local_placement = self.ifc_file.createIfcLocalPlacement(
            None, self.ifc_file.createIfcAxis2Placement3D(point, None, None)
        )

        # Create annotation
        annotation = api.root.create_entity(self.ifc_file, ifc_class="IfcAnnotation")
        annotation.Name = f"{building.Name} LOCATION"
        annotation.ObjectType = "DRAWING"
        annotation.ObjectPlacement = local_placement
        annotation.Representation = ShapeCreator.create_camera_shape(
            self.ifc_file, self.dim_all_x, self.dim_all_y, self.dim_all_z
        )

        # Use larger scale for location plan
        location_scale = self.scale * 10.0

        # Create property set
        pset = self.create_drawing_pset(annotation, location_scale)
        api.pset.edit_pset(
            self.ifc_file,
            pset=pset,
            properties={
                "TargetView": "PLAN_VIEW",
                "Include": f'IfcSite + IfcRoof, IfcWall, IfcSlab, location="{building.Name}"',
            },
        )

        # Attach to sheet
        self.attach_sheet(annotation, sheet_info, drawing_id)

        # Create group
        self.create_drawing_group(annotation)

        # Update drawing ID and position for next drawing
        drawing_id += 1

        return drawing_id

    def generate_drawings(self):
        """Generate all drawings for buildings"""
        sheet_id = 0

        for building in self.buildings:
            # Create sheet for the building
            sheet_id += 1
            identification = f"A{str(sheet_id).zfill(3)}"
            sheet_info = self.create_sheet_info(identification, building.Name)

            # FIXME should use local building orientation for bbox and cameras
            # Calculate building bounding box and dimensions
            building_bbox = GeometryUtils.get_bbox(self.ifc_file, [building])
            bbox_min, bbox_mid, bbox_max = building_bbox

            # Get all storeys for the building
            storeys = {}
            for ifc_storey in ifcopenshell.util.selector.filter_elements(
                self.ifc_file, f'IfcBuildingStorey, location="{building.Name}"'
            ):
                local_placement = ifcopenshell.util.placement.get_local_placement(
                    ifc_storey.ObjectPlacement
                )
                storeys[local_placement[2][3]] = ifc_storey

            # Initial drawing position
            drawing_id = 0

            # Create plan drawings for each storey
            for elevation in sorted(list(storeys.keys())):
                storey = storeys[elevation]
                drawing_id, annotation, group = self.create_plan_drawing(
                    storey,
                    building_bbox,
                    self.scale,
                    sheet_info,
                    drawing_id,
                )

                # Add space labels
                self.create_space_labels(storey, elevation, group)

            # Create elevation drawings
            for direction in ["NORTH", "SOUTH", "WEST", "EAST"]:
                drawing_id = self.create_elevation_drawing(
                    building,
                    building_bbox,
                    direction,
                    sheet_info,
                    drawing_id,
                )

            # Create location plan if there's more than one building
            if len(self.buildings) > 1:
                drawing_id = self.create_location_plan(
                    building, sheet_info, drawing_id
                )


def main():
    """Main function"""
    try:
        import bonsai.tool

        # Running in Bonsai BIM
        generator = DrawingGenerator(bonsai.tool.Ifc.get())
        generator.generate_drawings()
    except ImportError:
        if len(sys.argv) != 3:
            print("Usage: " + sys.argv[0] + " input.ifc output.ifc")
            sys.exit(1)
        else:
            # Running from command line
            ifc_file = ifcopenshell.open(sys.argv[1])
            generator = DrawingGenerator(ifc_file)
            generator.generate_drawings()
            ifc_file.write(sys.argv[2])


if __name__ == "__main__":
    main()
