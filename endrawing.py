#!/usr/bin/python3

import sys
import multiprocessing
import numpy as np
from natsort import natsorted
import ifcopenshell
import ifcopenshell.api as api
import ifcopenshell.api.context
import ifcopenshell.api.document
import ifcopenshell.api.drawing
import ifcopenshell.api.group
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.geom
import ifcopenshell.util
import ifcopenshell.util.selector
import ifcopenshell.util.representation
import ifcopenshell.util.placement
import ifcopenshell.util.shape
import ifcopenshell.util.unit
import ifcopenshell.util.element

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
    def get_location_elements(ifc_file, spatial_elements):
        """Collect the IfcElements located in any of the spatial elements

        Walks the spatial decomposition directly, which returns the same
        elements as a selector location="{Name}" query but is much faster on
        large models and doesn't depend on names being unique or set.

        Args:
            ifc_file: The IFC file
            spatial_elements: List of spatial elements

        Returns:
            Set of IfcElements
        """
        elements = set()
        for spatial_element in spatial_elements:
            elements.update(
                e
                for e in ifcopenshell.util.element.get_decomposition(spatial_element)
                if e.is_a("IfcElement")
            )
        return elements

    @staticmethod
    def get_element_bounds(ifc_file, elements):
        """Calculate world bounding boxes of element geometry

        Tessellates all elements in one multithreaded iterator pass and takes
        min/max over each vertex buffer with numpy, so no per-vertex Python
        loop is involved.

        Args:
            ifc_file: The IFC file
            elements: Iterable of IfcElements

        Returns:
            Dict of {element id: (min_xyz, max_xyz)} in project units. Elements
            without body geometry are absent.
        """
        bounds = {}
        elements = list(elements)
        if not elements:
            return bounds

        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        settings.set("convert-back-units", True)
        # Openings only ever remove material, so they can't enlarge a
        # bounding box, and boolean subtraction is the slowest part of
        # tessellation.
        settings.set("disable-opening-subtractions", True)
        settings.set("no-normals", True)
        settings.set("weld-vertices", False)

        # The hybrid kernel uses CGAL for polyhedral geometry and OpenCASCADE
        # only where needed, giving the same bounds around twice as fast.
        iterator_args = (settings, ifc_file, multiprocessing.cpu_count())
        try:
            iterator = ifcopenshell.geom.iterator(
                *iterator_args,
                include=elements,
                geometry_library="hybrid-cgal-simple-opencascade",
            )
        except RuntimeError:
            # Builds without CGAL have no hybrid kernel
            iterator = ifcopenshell.geom.iterator(*iterator_args, include=elements)
        if not iterator.initialize():
            return bounds

        while True:
            shape = iterator.get()
            verts = ifcopenshell.util.shape.get_vertices(shape.geometry)
            if len(verts):
                bounds[shape.id] = (verts.min(axis=0), verts.max(axis=0))
            if not iterator.next():
                break

        return bounds

    @staticmethod
    def get_bbox(ifc_file, spatial_elements, element_bounds=None):
        """Calculate bounding box for spatial elements

        Encloses the geometry of all elements located in the spatial elements.
        Elements without geometry contribute their placement origin instead.

        Args:
            ifc_file: The IFC file
            spatial_elements: List of spatial elements
            element_bounds: Optional precomputed result of get_element_bounds(),
                to avoid tessellating the same elements more than once

        Returns:
            Tuple of (min_point, mid_point, max_point)
        """
        elements = GeometryUtils.get_location_elements(ifc_file, spatial_elements)
        if element_bounds is None:
            element_bounds = GeometryUtils.get_element_bounds(ifc_file, elements)

        mins = []
        maxs = []

        for element in elements:
            if element.id() in element_bounds:
                element_min, element_max = element_bounds[element.id()]
                mins.append(element_min)
                maxs.append(element_max)
                continue

            local_placement = ifcopenshell.util.placement.get_local_placement(
                element.ObjectPlacement
            )
            origin = local_placement[:3, 3]

            # Skip only elements sitting at the true world origin, which
            # are typically unplaced. Elements legitimately placed on a
            # single world axis (e.g. on x=0 at the grid origin) are kept.
            if not origin.any():
                continue

            mins.append(origin)
            maxs.append(origin)

        # No geometry or validly placed elements found: return a degenerate
        # bbox at the origin rather than crashing in the midpoint calculation.
        if not mins:
            bbox_min = [0.0, 0.0, 0.0]
            bbox_max = [0.0, 0.0, 0.0]
        else:
            bbox_min = [float(v) for v in np.min(mins, axis=0)]
            bbox_max = [float(v) for v in np.max(maxs, axis=0)]

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

        # Validate basic requirements
        buildings = ifc_file.by_type("IfcBuilding")
        if not buildings:
            raise ValueError("No IfcBuilding entities found in IFC file")

        model_context = ifcopenshell.util.representation.get_context(ifc_file, "Model")
        if not model_context:
            raise ValueError("No Model context found in IFC file")

        self.scale = scale
        self.titleblock = titleblock
        self.contexts = ContextManager.ensure_contexts(ifc_file)
        # To convert meters to project units: project_units = meters / unit_scale
        self.unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc_file)

        # Calculate overall bounding box for site plan
        self.buildings = natsorted(
            ifc_file.by_type("IfcBuilding"), key=lambda x: x.Name or ""
        )
        # Tessellate every element once, reused for all bounding boxes
        self.element_bounds = GeometryUtils.get_element_bounds(
            ifc_file, GeometryUtils.get_location_elements(ifc_file, self.buildings)
        )
        self.bbox_all = GeometryUtils.get_bbox(
            ifc_file, self.buildings, self.element_bounds
        )
        self.bbox_all_min, self.bbox_all_mid, self.bbox_all_max = self.bbox_all

        # Calculate dimensions (add 2 meters padding in project units)
        self.dim_all_x = self.bbox_all_max[0] - self.bbox_all_min[0] + 2.0 / self.unit_scale
        self.dim_all_y = self.bbox_all_max[1] - self.bbox_all_min[1] + 2.0 / self.unit_scale
        self.dim_all_z = self.bbox_all_max[2] - self.bbox_all_min[2] + 2.0 / self.unit_scale

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
                "GeneratedBy": "endrawing",
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
            "General Arrangement",  # Purpose
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
        dim_x = bbox_max[0] - bbox_min[0] + 2.0 / self.unit_scale
        dim_y = bbox_max[1] - bbox_min[1] + 2.0 / self.unit_scale

        # Get elevation from storey placement
        local_placement = ifcopenshell.util.placement.get_local_placement(
            storey.ObjectPlacement
        )
        elevation = local_placement[2][3]

        # Create camera position (1.8 meters above floor in project units)
        point = self.ifc_file.createIfcCartesianPoint(
            [float(bbox_mid[0]), float(bbox_mid[1]), float(elevation + 1.8 / self.unit_scale)]
        )

        local_placement = self.ifc_file.createIfcLocalPlacement(
            None, self.ifc_file.createIfcAxis2Placement3D(point, None, None)
        )

        # Create annotation (camera volume depth 10 meters in project units)
        annotation = api.root.create_entity(self.ifc_file, ifc_class="IfcAnnotation")
        annotation.Name = storey.Name
        annotation.ObjectType = "DRAWING"
        annotation.ObjectPlacement = local_placement
        annotation.Representation = ShapeCreator.create_camera_shape(
            self.ifc_file, dim_x, dim_y, 10.0 / self.unit_scale
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

        # Update drawing ID for next drawing
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
            # Get space centroid. Spaces without a geometry representation make
            # create_shape raise; skip them rather than aborting the whole run.
            try:
                centroid = GeometryUtils.get_centroid(space)
            except RuntimeError:
                continue

            # Create placement (0.1 meters above floor in project units)
            placement = self.ifc_file.createIfcLocalPlacement(
                None,
                self.ifc_file.createIfcAxis2Placement3D(
                    self.ifc_file.createIfcCartesianPoint(
                        [centroid[0], centroid[1], float(elevation) + 0.1 / self.unit_scale]
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
                properties={
                    "GeneratedBy": "endrawing",
                    "Classes": "header",
                },
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
        dim_x = bbox_max[0] - bbox_min[0] + 2.0 / self.unit_scale
        dim_y = bbox_max[1] - bbox_min[1] + 2.0 / self.unit_scale
        dim_z = bbox_max[2] - bbox_min[2] + 2.0 / self.unit_scale

        # Set up direction-specific parameters (0.5m offset, 1m depth in project units)
        offset = 0.5 / self.unit_scale
        depth = 1.0 / self.unit_scale

        if direction == "NORTH":
            point = self.ifc_file.createIfcCartesianPoint(
                [float(bbox_mid[0]), float(bbox_max[1]) + offset, float(bbox_mid[2])]
            )
            axis_dir = self.ifc_file.createIfcDirection([0.0, 1.0, 0.0])
            ref_dir = self.ifc_file.createIfcDirection([-1.0, 0.0, 0.0])
            camera_dims = (dim_x, dim_z, dim_y - depth)

        elif direction == "SOUTH":
            point = self.ifc_file.createIfcCartesianPoint(
                [float(bbox_mid[0]), float(bbox_min[1]) - offset, float(bbox_mid[2])]
            )
            axis_dir = self.ifc_file.createIfcDirection([0.0, -1.0, 0.0])
            ref_dir = self.ifc_file.createIfcDirection([1.0, 0.0, 0.0])
            camera_dims = (dim_x, dim_z, dim_y - depth)

        elif direction == "WEST":
            point = self.ifc_file.createIfcCartesianPoint(
                [float(bbox_min[0]) - offset, float(bbox_mid[1]), float(bbox_mid[2])]
            )
            axis_dir = self.ifc_file.createIfcDirection([-1.0, 0.0, 0.0])
            ref_dir = self.ifc_file.createIfcDirection([0.0, -1.0, 0.0])
            camera_dims = (dim_y, dim_z, dim_x - depth)

        elif direction == "EAST":
            point = self.ifc_file.createIfcCartesianPoint(
                [float(bbox_max[0]) + offset, float(bbox_mid[1]), float(bbox_mid[2])]
            )
            axis_dir = self.ifc_file.createIfcDirection([1.0, 0.0, 0.0])
            ref_dir = self.ifc_file.createIfcDirection([0.0, 1.0, 0.0])
            camera_dims = (dim_y, dim_z, dim_x - depth)

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

        # Update drawing ID for next drawing
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
        # Create point at center of all buildings, above max height (1 meter in project units)
        point = self.ifc_file.createIfcCartesianPoint(
            [
                float(self.bbox_all_mid[0]),
                float(self.bbox_all_mid[1]),
                float(self.bbox_all_max[2] + 1.0 / self.unit_scale),
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

        # Update drawing ID for next drawing
        drawing_id += 1

        return drawing_id

    def get_references(self, information):
        """Get the document references of an IfcDocumentInformation

        Args:
            information: The IfcDocumentInformation

        Returns:
            List of IfcDocumentReference
        """
        if self.ifc_file.schema == "IFC2X3":
            return list(information.DocumentReferences or [])
        return list(information.HasDocumentReferences)

    def get_information(self, reference):
        """Get the IfcDocumentInformation that a reference belongs to

        Args:
            reference: The IfcDocumentReference

        Returns:
            IfcDocumentInformation, or None
        """
        if self.ifc_file.schema == "IFC2X3":
            return next(iter(reference.ReferenceToDocument), None)
        return reference.ReferencedDocument

    def get_reference_description(self, reference):
        """Get the role of a sheet reference, such as "DRAWING" or "LAYOUT"

        IFC2X3 references have no Description, so Bonsai uses Name instead.

        Args:
            reference: The IfcDocumentReference

        Returns:
            Description string, or None
        """
        if self.ifc_file.schema == "IFC2X3":
            return reference.Name
        return reference.Description

    def is_generated_sheet(self, sheet, drawing_locations):
        """Check whether a sheet was created by endrawing

        A generated sheet is a General Arrangement sheet whose drawings are
        all endrawing drawings. A sheet with any other drawing on it, or with
        none, belongs to the user, whatever its Purpose.

        Args:
            sheet: IfcDocumentInformation
            drawing_locations: Set of SVG locations of endrawing drawings

        Returns:
            True if endrawing created the sheet
        """
        if sheet.Scope != "SHEET" or sheet.Purpose != "General Arrangement":
            return False
        locations = [
            reference.Location
            for reference in self.get_references(sheet)
            if self.get_reference_description(reference) == "DRAWING"
        ]
        return bool(locations) and all(l in drawing_locations for l in locations)

    def cleanup_existing_drawings(self):
        """Remove all endrawing-generated drawings and sheets

        Everything removed is traced from annotations marked GeneratedBy =
        "endrawing": the annotations themselves, the documents and groups of
        the drawings among them, and the sheets holding only those drawings.
        """
        drawings = []
        labels = []
        for annotation in self.ifc_file.by_type("IfcAnnotation"):
            psets = ifcopenshell.util.element.get_psets(annotation)
            if psets.get("EPset_Drawing", {}).get("GeneratedBy") == "endrawing":
                drawings.append(annotation)
            elif psets.get("EPset_Annotation", {}).get("GeneratedBy") == "endrawing":
                labels.append(annotation)

        documents = set()
        groups = set()
        drawing_locations = set()
        for drawing in drawings:
            for rel in drawing.HasAssociations:
                if rel.is_a("IfcRelAssociatesDocument") and rel.RelatingDocument.is_a(
                    "IfcDocumentReference"
                ):
                    drawing_locations.add(rel.RelatingDocument.Location)
                    information = self.get_information(rel.RelatingDocument)
                    if information:
                        documents.add(information)
            for rel in drawing.HasAssignments:
                if (
                    rel.is_a("IfcRelAssignsToGroup")
                    and rel.RelatingGroup.ObjectType == "DRAWING"
                ):
                    groups.add(rel.RelatingGroup)

        # Identify sheets while their drawings still exist
        sheets = [
            sheet
            for sheet in self.ifc_file.by_type("IfcDocumentInformation")
            if self.is_generated_sheet(sheet, drawing_locations)
        ]

        # Removing a drawing's document also removes its reference and the
        # association with the drawing
        for information in documents:
            api.document.remove_information(self.ifc_file, information=information)

        for annotation in drawings + labels:
            api.root.remove_product(self.ifc_file, product=annotation)

        # A drawing group can also hold annotations the user added to the
        # drawing, so it's only removed once it's empty
        for group in groups:
            if not any(rel.RelatedObjects for rel in group.IsGroupedBy):
                api.group.remove_group(self.ifc_file, group=group)

        for sheet in sheets:
            api.document.remove_information(self.ifc_file, information=sheet)

    def generate_drawings(self):
        """Generate all drawings for buildings"""
        self.cleanup_existing_drawings()

        sheet_id = 0

        for building in self.buildings:
            # Create sheet for the building
            sheet_id += 1
            identification = f"A{str(sheet_id).zfill(3)}"
            sheet_info = self.create_sheet_info(identification, building.Name)

            # FIXME should use local building orientation for bbox and cameras
            # Calculate building bounding box and dimensions
            building_bbox = GeometryUtils.get_bbox(
                self.ifc_file, [building], self.element_bounds
            )
            bbox_min, bbox_mid, bbox_max = building_bbox

            # Collect storeys as (elevation, storey) pairs rather than a dict
            # keyed by elevation, so two storeys sharing an elevation
            # (mezzanines, split levels) don't overwrite each other. Sort by
            # elevation separately below.
            storeys = []
            for ifc_storey in ifcopenshell.util.selector.filter_elements(
                self.ifc_file, f'IfcBuildingStorey, location="{building.Name}"'
            ):
                local_placement = ifcopenshell.util.placement.get_local_placement(
                    ifc_storey.ObjectPlacement
                )
                storeys.append((local_placement[2][3], ifc_storey))

            drawing_id = 0

            # Create plan drawings for each storey
            for elevation, storey in sorted(storeys, key=lambda s: s[0]):
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

        # Running in Bonsai BIM - use defaults
        generator = DrawingGenerator(bonsai.tool.Ifc.get())
        generator.generate_drawings()
    except ImportError:
        # Running from command line - parse arguments
        import argparse

        parser = argparse.ArgumentParser(
            description="Generate General Arrangement drawings for IFC buildings"
        )
        parser.add_argument("input", help="Input IFC file")
        parser.add_argument("output", help="Output IFC file")
        parser.add_argument(
            "--scale",
            type=int,
            default=100,
            help="Drawing scale denominator (default: 100 for 1:100)",
        )
        parser.add_argument(
            "--titleblock", default="A2", help="Titleblock size (default: A2)"
        )

        args = parser.parse_args()

        # Process
        ifc_file = ifcopenshell.open(args.input)
        generator = DrawingGenerator(
            ifc_file, scale=args.scale, titleblock=args.titleblock
        )
        generator.generate_drawings()
        ifc_file.write(args.output)
        print(f"Generated drawings and sheets in {args.output}")


if __name__ == "__main__":
    main()
