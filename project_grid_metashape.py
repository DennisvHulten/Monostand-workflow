"""
Grid Marker Placement Script for Agisoft Metashape

This script allows a user to create a grid of markers projected onto
a point cloud or mesh in Metashape, within a bounding box defined
either by markers or the region box.

Author: Dennis van Hulten
Date: 2025-09
Version: 0.1
"""

import Metashape
from PySide2 import QtWidgets


class GridMarkerDialog(QtWidgets.QDialog):
    """
    GUI dialog to configure grid marker generation.
    """

    def __init__(self):
        super().__init__()

        layout = QtWidgets.QVBoxLayout(self)

        # Grid spacing input
        self.spacing_input = QtWidgets.QLineEdit("1.0")
        layout.addWidget(QtWidgets.QLabel("Grid spacing (m):"))
        layout.addWidget(self.spacing_input)

        # Bounding box options
        self.target_box = QtWidgets.QGroupBox("Bounding box from")
        target_layout = QtWidgets.QVBoxLayout(self.target_box)
        self.marker_btn = QtWidgets.QRadioButton("Marker positions (TL, TR, BL, BR)")
        self.region_btn = QtWidgets.QRadioButton("Region")
        target_layout.addWidget(self.marker_btn)
        target_layout.addWidget(self.region_btn)
        layout.addWidget(self.target_box)

        # Model selection
        self.model_box = QtWidgets.QGroupBox("Model")
        model_layout = QtWidgets.QVBoxLayout(self.model_box)
        self.pcd_btn = QtWidgets.QRadioButton("Point Cloud")
        self.mesh_btn = QtWidgets.QRadioButton("Mesh")
        model_layout.addWidget(self.pcd_btn)
        model_layout.addWidget(self.mesh_btn)
        layout.addWidget(self.model_box)

        # Window buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

        # Default selections
        self.region_btn.setChecked(True)
        self.pcd_btn.setChecked(True)

    def get_values(self):
        """
        Return dialog values as dictionary.
        """
        return {
            "spacing": float(self.spacing_input.text()),
            "bbox_use_markers": self.marker_btn.isChecked(),
            "use_mesh": self.mesh_btn.isChecked()
        }


def get_bbox_from_markers(chunk):
    """
    Compute bounding box from four markers: TL, TR, BL, BR.
    """
    transform = chunk.transform.matrix
    required_markers = {"TL", "TR", "BL", "BR"}
    coords = [
        m.position for m in chunk.markers
        if m.position and m.label in required_markers
    ]

    if len(coords) < 4:
        Metashape.app.messageBox("Error: Need 4 markers with positions defined.")
        return None

    coords = [transform.mulp(c) for c in coords]
    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    zs = [c.z for c in coords]

    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def get_bbox_from_region(chunk):
    """
    Compute bounding box from the current region.
    """
    region = chunk.region
    transform = chunk.transform.matrix

    corners = [
        region.center
        + region.size.x / 2 * region.rot.col(0)
        + region.size.y / 2 * region.rot.col(1)
        + region.size.z / 2 * region.rot.col(2),

        region.center
        - region.size.x / 2 * region.rot.col(0)
        - region.size.y / 2 * region.rot.col(1)
        - region.size.z / 2 * region.rot.col(2),
    ]
    corners = [transform.mulp(c) for c in corners]

    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]

    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def main():
    """
    Main function to run the grid marker placement tool.
    """
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    dialog = GridMarkerDialog()
    if not dialog.exec_():
        print("Cancelled.")
        return

    values = dialog.get_values()
    spacing = values["spacing"]
    bbox_use_markers = values["bbox_use_markers"]

    doc = Metashape.app.document
    chunk = doc.chunk
    transform = chunk.transform.matrix
    transform_inv = transform.inv()

    # Get bounding box
    if bbox_use_markers:
        bbox = get_bbox_from_markers(chunk)
    else:
        bbox = get_bbox_from_region(chunk)

    if bbox is None:
        return

    xmin, ymin, zmin, xmax, ymax, zmax = bbox

    # Remove old grid markers
    to_remove = [m for m in list(chunk.markers) if m.label.startswith("G_")]
    for marker in to_remove:
        chunk.remove(marker)

    # Define top and bottom z planes for raycasting
    z_top = zmax + 5
    z_bottom = zmin - 5

    nx = int((xmax - xmin) / spacing) + 1
    ny = int((ymax - ymin) / spacing) + 1

    idx = 0
    for i in range(nx):
        for j in range(ny):
            x = xmin + i * spacing
            y = ymin + j * spacing
            z = z_top

            world_point = Metashape.Vector([x, y, z])

            origin_internal = transform_inv.mulp(world_point)
            target_internal = transform_inv.mulp(Metashape.Vector([x, y, z_bottom]))

            hit_internal = chunk.point_cloud.pickPoint(origin_internal, target_internal)

            if hit_internal:
                idx += 1
                marker = chunk.addMarker(hit_internal)
                marker.label = f"G_{idx:03d}"

    doc.save()


if __name__ == "__main__":
    main()