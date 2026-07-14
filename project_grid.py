"""
Grid Marker Placement Script for Agisoft Metashape

Creates a grid of markers projected onto a point cloud or mesh, within a
bounding box defined by one of several sources:
  - Four corner markers (TL, TR, BL, BR)
  - The current Region box
  - A manual point-cloud selection (Rectangle/Free-form select tool)
  - A drawn shape/polygon (Shapes layer)

Author: Dennis van Hulten
Date: 2025-09
Version: 0.2
"""

import Metashape
from PySide2 import QtWidgets, QtCore


# ---------------------------------------------------------------------------
# Bounding box helpers
# ---------------------------------------------------------------------------

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
        Metashape.app.messageBox(
            "Need 4 markers labeled TL, TR, BL and BR, each with a position defined.\n"
            "Place/label them first, or choose a different bounding box source."
        )
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


def get_bbox_from_selection(chunk):
    """
    Compute bounding box from currently *selected points* in the point cloud.
    Use the Rectangle or Free-form selection tool in the Model / Point Cloud
    view to select an area first, then run the script.

    NOTE: in Metashape 2.x the dense/sparse cloud may live under
    `chunk.tie_points` instead of `chunk.point_cloud` depending on what you're
    selecting on. If this raises an AttributeError, try swapping
    `chunk.point_cloud` for `chunk.tie_points` (or vice versa) for your version.
    """
    pc = chunk.point_cloud
    if pc is None:
        Metashape.app.messageBox("This chunk has no point cloud to select from.")
        return None

    transform = chunk.transform.matrix
    coords = [transform.mulp(p.coord) for p in pc.points if p.valid and p.selected]

    if len(coords) < 3:
        Metashape.app.messageBox(
            "No point selection found.\n\n"
            "Use the Rectangle or Free-form selection tool in the Point Cloud "
            "view to select an area, then run the script again."
        )
        return None

    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    zs = [c.z for c in coords]

    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def get_bbox_from_shape(chunk, shape):
    """
    Compute bounding box from a drawn shape's geometry (e.g. a polygon drawn
    in the ortho/model view).

    NOTE on coordinate systems: this assumes the chunk uses a *local*
    (non-georeferenced) coordinate system, which is the common case for
    lab/object scans that also use TL/TR/BL/BR corner markers. If your chunk
    IS georeferenced (has a real CRS), shape coordinates may be stored in
    that CRS and would need reprojecting into the chunk's local frame before
    this will line up correctly. Test on one small shape before trusting the
    output; if markers land in the wrong place, that's the likely culprit.
    """
    if shape is None or shape.geometry is None:
        Metashape.app.messageBox("The selected shape has no geometry.")
        return None

    transform = chunk.transform.matrix

    raw_points = []

    def _flatten(seq):
        for item in seq:
            if isinstance(item, Metashape.Vector):
                raw_points.append(item)
            else:
                _flatten(item)

    _flatten(shape.geometry.coordinates)

    if not raw_points:
        Metashape.app.messageBox("Could not read any points from that shape's geometry.")
        return None

    # Assumes shape coordinates are already in the chunk's local/internal
    # coordinate system (see note above).
    coords = [transform.mulp(p) for p in raw_points]

    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    zs = [c.z for c in coords]

    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class GridMarkerDialog(QtWidgets.QDialog):
    """
    GUI dialog to configure grid marker generation.
    """

    SOURCE_MARKERS = "markers"
    SOURCE_REGION = "region"
    SOURCE_SELECTION = "selection"
    SOURCE_SHAPE = "shape"

    def __init__(self, chunk):
        super().__init__()
        self.chunk = chunk
        self.setWindowTitle("Place Grid Markers")

        layout = QtWidgets.QVBoxLayout(self)

        # --- Grid spacing ---
        form = QtWidgets.QFormLayout()
        self.spacing_input = QtWidgets.QLineEdit("1.0")
        self.spacing_input.setToolTip("Distance between grid points, in chunk units.")
        form.addRow("Grid spacing:", self.spacing_input)

        self.margin_input = QtWidgets.QLineEdit("5.0")
        self.margin_input.setToolTip(
            "Extra height added above/below the bounding box when raycasting.\n"
            "Increase this if your source (e.g. a flat selection or shape) has "
            "little to no height of its own."
        )
        form.addRow("Raycast margin:", self.margin_input)

        self.prefix_input = QtWidgets.QLineEdit("G_")
        self.prefix_input.setToolTip("Label prefix for generated markers. Existing markers with this prefix are replaced.")
        form.addRow("Marker prefix:", self.prefix_input)

        layout.addLayout(form)

        # --- Bounding box source ---
        self.target_box = QtWidgets.QGroupBox("Bounding box from")
        target_layout = QtWidgets.QVBoxLayout(self.target_box)

        self.marker_btn = QtWidgets.QRadioButton("Marker positions (TL, TR, BL, BR)")
        self.region_btn = QtWidgets.QRadioButton("Region")
        self.selection_btn = QtWidgets.QRadioButton("Manual point selection")
        self.shape_btn = QtWidgets.QRadioButton("Drawn shape")

        target_layout.addWidget(self.marker_btn)
        target_layout.addWidget(self.region_btn)
        target_layout.addWidget(self.selection_btn)

        shape_row = QtWidgets.QHBoxLayout()
        shape_row.addWidget(self.shape_btn)
        self.shape_combo = QtWidgets.QComboBox()
        self._populate_shapes()
        shape_row.addWidget(self.shape_combo)
        target_layout.addLayout(shape_row)

        layout.addWidget(self.target_box)

        # --- Model to project onto ---
        self.model_box = QtWidgets.QGroupBox("Project onto")
        model_layout = QtWidgets.QVBoxLayout(self.model_box)
        self.pcd_btn = QtWidgets.QRadioButton("Point Cloud")
        self.mesh_btn = QtWidgets.QRadioButton("Mesh")
        model_layout.addWidget(self.pcd_btn)
        model_layout.addWidget(self.mesh_btn)
        layout.addWidget(self.model_box)

        # --- Buttons ---
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

        # Defaults
        self.region_btn.setChecked(True)
        self.pcd_btn.setChecked(True)
        self.shape_combo.setEnabled(self.shape_btn.isChecked())
        self.shape_btn.toggled.connect(self.shape_combo.setEnabled)

    def _populate_shapes(self):
        self.shape_combo.clear()
        shapes = list(self.chunk.shapes.shapes) if self.chunk.shapes else []
        if not shapes:
            self.shape_combo.addItem("(no shapes in chunk)")
            self.shape_combo.setEnabled(False)
            self.shape_btn.setEnabled(False)
            return
        for s in shapes:
            self.shape_combo.addItem(s.label or "(unnamed shape)", s)

    def get_values(self):
        """
        Return dialog values as a dictionary. Raises ValueError on bad input.
        """
        try:
            spacing = float(self.spacing_input.text())
        except ValueError:
            raise ValueError("Grid spacing must be a number.")
        if spacing <= 0:
            raise ValueError("Grid spacing must be greater than zero.")

        try:
            margin = float(self.margin_input.text())
        except ValueError:
            raise ValueError("Raycast margin must be a number.")
        if margin < 0:
            raise ValueError("Raycast margin can't be negative.")

        prefix = self.prefix_input.text().strip()
        if not prefix:
            raise ValueError("Marker prefix can't be empty.")

        if self.marker_btn.isChecked():
            source = self.SOURCE_MARKERS
        elif self.region_btn.isChecked():
            source = self.SOURCE_REGION
        elif self.selection_btn.isChecked():
            source = self.SOURCE_SELECTION
        else:
            source = self.SOURCE_SHAPE

        shape = self.shape_combo.currentData() if source == self.SOURCE_SHAPE else None
        if source == self.SOURCE_SHAPE and shape is None:
            raise ValueError("No shape selected.")

        return {
            "spacing": spacing,
            "margin": margin,
            "prefix": prefix,
            "source": source,
            "shape": shape,
            "use_mesh": self.mesh_btn.isChecked(),
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    doc = Metashape.app.document
    chunk = doc.chunk
    if chunk is None:
        Metashape.app.messageBox("No active chunk.")
        return

    dialog = GridMarkerDialog(chunk)
    if not dialog.exec_():
        print("Cancelled.")
        return

    try:
        values = dialog.get_values()
    except ValueError as e:
        Metashape.app.messageBox(str(e))
        return

    spacing = values["spacing"]
    margin = values["margin"]
    prefix = values["prefix"]
    use_mesh = values["use_mesh"]

    if use_mesh and not chunk.model:
        Metashape.app.messageBox("This chunk has no mesh. Choose Point Cloud instead, or build a mesh first.")
        return
    if not use_mesh and not chunk.point_cloud:
        Metashape.app.messageBox("This chunk has no point cloud. Choose Mesh instead, or build a point cloud first.")
        return

    transform = chunk.transform.matrix
    transform_inv = transform.inv()

    # Get bounding box from the chosen source
    if values["source"] == GridMarkerDialog.SOURCE_MARKERS:
        bbox = get_bbox_from_markers(chunk)
    elif values["source"] == GridMarkerDialog.SOURCE_REGION:
        bbox = get_bbox_from_region(chunk)
    elif values["source"] == GridMarkerDialog.SOURCE_SELECTION:
        bbox = get_bbox_from_selection(chunk)
    else:
        bbox = get_bbox_from_shape(chunk, values["shape"])

    if bbox is None:
        return

    xmin, ymin, zmin, xmax, ymax, zmax = bbox

    nx = int((xmax - xmin) / spacing) + 1
    ny = int((ymax - ymin) / spacing) + 1
    estimated = nx * ny

    if estimated <= 0:
        Metashape.app.messageBox("The computed bounding box is empty — nothing to place.")
        return

    proceed = QtWidgets.QMessageBox.question(
        None,
        "Confirm grid",
        f"This will raycast up to {estimated} candidate points "
        f"({nx} x {ny}) and add a marker at every hit.\n\nContinue?",
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
    )
    if proceed != QtWidgets.QMessageBox.Yes:
        print("Cancelled.")
        return

    # Remove old grid markers with this prefix
    to_remove = [m for m in list(chunk.markers) if m.label.startswith(prefix)]
    for marker in to_remove:
        chunk.remove(marker)

    z_top = zmax + margin
    z_bottom = zmin - margin

    pad = len(str(estimated))
    idx = 0
    placed = 0

    for i in range(nx):
        for j in range(ny):
            idx += 1
            x = xmin + i * spacing
            y = ymin + j * spacing

            origin_internal = transform_inv.mulp(Metashape.Vector([x, y, z_top]))
            target_internal = transform_inv.mulp(Metashape.Vector([x, y, z_bottom]))

            if use_mesh:
                hit_internal = chunk.model.pickPoint(origin_internal, target_internal)
            else:
                hit_internal = chunk.point_cloud.pickPoint(origin_internal, target_internal)

            if hit_internal:
                placed += 1
                marker = chunk.addMarker(hit_internal)
                marker.label = f"{prefix}{placed:0{pad}d}"

            # Keep the UI responsive on large grids
            if idx % 50 == 0:
                Metashape.app.update()
                QtWidgets.QApplication.processEvents()
                print(f"Processed {idx}/{estimated} candidates, {placed} markers placed...")

    doc.save()
    print(f"Done. Placed {placed} markers out of {estimated} candidates.")
    Metashape.app.messageBox(f"Placed {placed} markers.")


if __name__ == "__main__":
    main()
