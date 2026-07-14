"""
Grid Marker Placement Script for Agisoft Metashape

Creates a grid of markers projected onto a point cloud or mesh, within a
bounding box defined by one of several sources:
  - Four corner markers (TL, TR, BL, BR)
  - The current Region box
  - A shape you draw on the spot (opens a small window, you draw a polygon,
    click Capture — the shape is used for the grid, then deleted)
  - An existing shape already in the chunk's Shapes layer

Author: Dennis van Hulten
Date: 2025-09
Version: 0.3
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


def point_in_polygon(x, y, polygon):
    """
    Standard even-odd rule (ray casting) point-in-polygon test. Works for
    any simple polygon — convex, concave, or a many-vertex approximation of
    a circle/organic shape. `polygon` is a list of (x, y) tuples.
    """
    n = len(polygon)
    inside = False
    xj, yj = polygon[-1]
    for xi, yi in polygon:
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        xj, yj = xi, yi
    return inside


def get_shape_geometry(chunk, shape):
    """
    Returns (bbox, polygon_xy) for a drawn shape:
      - bbox: (xmin, ymin, zmin, xmax, ymax, zmax) in the same frame used
        throughout this script (via chunk.world_crs) — used to size the
        candidate grid.
      - polygon_xy: list of (x, y) tuples for the shape's vertices in that
        same frame, for point-in-polygon testing. None if the shape has
        fewer than 3 vertices (can't form an area to test against).

    See get_bbox_from_shape's docstring (kept below for the coordinate
    system conversion this relies on).
    """
    bbox = get_bbox_from_shape(chunk, shape)
    if bbox is None:
        return None, None

    shapes_crs = chunk.shapes.crs
    world_crs = chunk.world_crs

    raw_points = []

    def _flatten(seq):
        for item in seq:
            if isinstance(item, Metashape.Vector):
                raw_points.append(item)
            else:
                _flatten(item)

    _flatten(shape.geometry.coordinates)

    if len(raw_points) < 3:
        return bbox, None

    coords = [Metashape.CoordinateSystem.transform(p, shapes_crs, world_crs) for p in raw_points]
    polygon_xy = [(c.x, c.y) for c in coords]

    return bbox, polygon_xy


def get_bbox_from_shape(chunk, shape):
    """
    Compute bounding box from a drawn shape's geometry (e.g. a polygon drawn
    in the ortho/model view).

    Shape vertices are stored in the Shapes layer's own coordinate system
    (chunk.shapes.crs), NOT in the chunk's internal coordinates. Following
    Agisoft's own reference scripts (see agisoft-llc/metashape-scripts,
    detect_objects.py), the correct conversion is:
        shape coord (shapes.crs) -> chunk.world_crs
    which lands in the same frame this script already uses for markers and
    region (i.e. transform.mulp(internal_coord)), so no further conversion
    is needed afterwards. This also works for unreferenced/local chunks,
    since shapes.crs and world_crs then both refer to the same local frame.
    """
    if shape is None or shape.geometry is None:
        Metashape.app.messageBox("The selected shape has no geometry.")
        return None

    if chunk.shapes is None or chunk.shapes.crs is None:
        Metashape.app.messageBox(
            "This chunk's Shapes layer has no coordinate system set, so shape "
            "geometry can't be resolved. Try a different bounding box source."
        )
        return None

    shapes_crs = chunk.shapes.crs
    world_crs = chunk.world_crs

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

    coords = [Metashape.CoordinateSystem.transform(p, shapes_crs, world_crs) for p in raw_points]

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
    SOURCE_DRAW_SHAPE = "draw_shape"
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
        self.draw_shape_btn = QtWidgets.QRadioButton("Draw a new shape now")
        self.draw_shape_btn.setToolTip(
            "Opens a small window that stays open while you draw a polygon "
            "(Model menu -> Draw Shape -> Polygon) around your area of "
            "interest. The shape is used for the grid, then deleted."
        )
        self.shape_btn = QtWidgets.QRadioButton("Use an existing shape")

        target_layout.addWidget(self.marker_btn)
        target_layout.addWidget(self.region_btn)
        target_layout.addWidget(self.draw_shape_btn)

        shape_row = QtWidgets.QHBoxLayout()
        shape_row.addWidget(self.shape_btn)
        self.shape_combo = QtWidgets.QComboBox()
        self._populate_shapes()
        shape_row.addWidget(self.shape_combo)
        target_layout.addLayout(shape_row)

        self.clip_checkbox = QtWidgets.QCheckBox("Clip to shape outline (not just its bounding box)")
        self.clip_checkbox.setToolTip(
            "When checked, only grid points inside the shape's actual outline are "
            "kept — useful for circles or other non-rectangular shapes. When "
            "unchecked, the shape's rectangular bounding box is used instead, "
            "matching the old behavior."
        )
        self.clip_checkbox.setChecked(True)
        target_layout.addWidget(self.clip_checkbox)

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
        elif self.draw_shape_btn.isChecked():
            source = self.SOURCE_DRAW_SHAPE
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
            "clip_to_shape": self.clip_checkbox.isChecked(),
            "use_mesh": self.mesh_btn.isChecked(),
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_grid_placement(chunk, bbox, spacing, margin, prefix, use_mesh, polygon_xy=None):
    """
    Given a bounding box (in the transform.mulp(...) frame used throughout
    this script), raycast a grid and add markers at the hits. Shared by both
    the immediate sources (markers/region/shape) and the deferred draw-shape
    capture flow.

    If polygon_xy is given (a list of (x, y) tuples), candidate points are
    first tested with point_in_polygon() and anything outside the polygon
    is skipped before raycasting — this lets circular/organic shapes clip
    the grid to their actual outline rather than just their bounding box.
    """
    doc = Metashape.app.document
    transform = chunk.transform.matrix
    transform_inv = transform.inv()

    xmin, ymin, zmin, xmax, ymax, zmax = bbox

    nx = int((xmax - xmin) / spacing) + 1
    ny = int((ymax - ymin) / spacing) + 1
    estimated = nx * ny

    if estimated <= 0:
        Metashape.app.messageBox("The computed bounding box is empty — nothing to place.")
        return

    clip_note = (
        " Candidates outside the shape's outline will be skipped before raycasting."
        if polygon_xy else ""
    )
    proceed = QtWidgets.QMessageBox.question(
        None,
        "Confirm grid",
        f"This will test up to {estimated} candidate points "
        f"({nx} x {ny}) and add a marker at every hit.{clip_note}\n\nContinue?",
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
    skipped = 0
    placed = 0

    for i in range(nx):
        for j in range(ny):
            idx += 1
            x = xmin + i * spacing
            y = ymin + j * spacing

            if polygon_xy is not None and not point_in_polygon(x, y, polygon_xy):
                skipped += 1
                continue

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
                print(f"Processed {idx}/{estimated} candidates, {skipped} outside shape, {placed} markers placed...")

    doc.save()
    print(f"Done. Placed {placed} markers out of {estimated} candidates ({skipped} skipped as outside the shape).")
    Metashape.app.messageBox(f"Placed {placed} markers.")


class DrawShapeCaptureDialog(QtWidgets.QDialog):
    """
    Small non-modal window (.show(), not .exec_(), so the viewport stays
    interactive) that lets you draw a new shape using Metashape's own
    vectorization tools, then use it for the grid and clean it up
    afterwards.

    Workflow:
      1. Draw a polygon around your area of interest yourself, via
         Model menu -> Draw Shape -> Polygon (or the toolbar icon).
      2. Click "Refresh" here so the new shape shows up in the list.
      3. Pick it (it's pre-selected as the most recently added shape) and
         click "Capture Shape".
      4. The grid is generated from that shape's bounding box, and (if the
         checkbox is ticked) the shape is deleted afterwards, leaving no
         trace in your Shapes layer.
    """

    def __init__(self, chunk, spacing, margin, prefix, use_mesh, clip_to_shape=True):
        super().__init__()
        self.chunk = chunk
        self.spacing = spacing
        self.margin = margin
        self.prefix = prefix
        self.use_mesh = use_mesh

        self.setWindowTitle("Draw & Capture Shape")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        layout = QtWidgets.QVBoxLayout(self)

        info = QtWidgets.QLabel(
            "This window stays open so you can still use the viewport.\n\n"
            "1. Draw a polygon around your area of interest: Model menu -> "
            "Draw Shape -> Polygon (or the toolbar icon).\n"
            "2. Finish the shape (double-click / right-click to close it).\n"
            "3. Click \"Refresh\", pick your shape below, then \"Capture Shape\"."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        combo_row = QtWidgets.QHBoxLayout()
        self.shape_combo = QtWidgets.QComboBox()
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        combo_row.addWidget(self.shape_combo, 1)
        combo_row.addWidget(self.refresh_btn)
        layout.addLayout(combo_row)

        self.clip_checkbox = QtWidgets.QCheckBox("Clip to shape outline (not just its bounding box)")
        self.clip_checkbox.setToolTip(
            "When checked, only grid points inside the shape's actual outline are "
            "kept — useful for circles or other non-rectangular shapes."
        )
        self.clip_checkbox.setChecked(clip_to_shape)
        layout.addWidget(self.clip_checkbox)

        self.delete_checkbox = QtWidgets.QCheckBox("Delete this shape after placing markers")
        self.delete_checkbox.setChecked(True)
        layout.addWidget(self.delete_checkbox)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QtWidgets.QHBoxLayout()
        self.capture_btn = QtWidgets.QPushButton("Capture Shape")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        button_row.addWidget(self.capture_btn)
        button_row.addWidget(self.cancel_btn)
        layout.addLayout(button_row)

        self.refresh_btn.clicked.connect(self.refresh_shapes)
        self.capture_btn.clicked.connect(self.on_capture)
        self.cancel_btn.clicked.connect(self.close)

        self.refresh_shapes()

    def refresh_shapes(self):
        self.shape_combo.clear()
        shapes = list(self.chunk.shapes.shapes) if self.chunk.shapes else []
        if not shapes:
            self.shape_combo.addItem("(no shapes yet - draw one, then Refresh)")
            return
        for s in shapes:
            self.shape_combo.addItem(s.label or "(unnamed shape)", s)
        # Default to the most recently added shape, since that's almost
        # always the one just drawn.
        self.shape_combo.setCurrentIndex(self.shape_combo.count() - 1)

    def on_capture(self):
        shape = self.shape_combo.currentData()
        if shape is None:
            self.status_label.setText(
                "No shape available yet. Draw one, click Refresh, then try again."
            )
            return

        bbox, polygon_xy = get_shape_geometry(self.chunk, shape)
        if bbox is None:
            self.status_label.setText("Couldn't read that shape's geometry — see the message above.")
            return
        if not self.clip_checkbox.isChecked():
            polygon_xy = None

        self.status_label.setText("Shape captured — placing markers...")
        QtWidgets.QApplication.processEvents()
        self.hide()

        run_grid_placement(
            self.chunk, bbox, self.spacing, self.margin, self.prefix, self.use_mesh,
            polygon_xy=polygon_xy,
        )

        if self.delete_checkbox.isChecked():
            try:
                self.chunk.shapes.remove(shape)
            except Exception as e:
                print(f"[grid marker tool] Could not delete temporary shape: {e}")

        self.close()


# Keep a module-level reference so the non-modal capture window isn't
# garbage-collected the moment main() returns.
_active_capture_dialog = None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _active_capture_dialog

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
    source = values["source"]

    if use_mesh and not chunk.model:
        Metashape.app.messageBox("This chunk has no mesh. Choose Point Cloud instead, or build a mesh first.")
        return
    if not use_mesh and not chunk.point_cloud:
        Metashape.app.messageBox("This chunk has no point cloud. Choose Mesh instead, or build a point cloud first.")
        return

    clip_to_shape = values.get("clip_to_shape", True)

    if source == GridMarkerDialog.SOURCE_DRAW_SHAPE:
        # Deferred flow: show a non-modal window, let the user draw a shape
        # in the still-interactive viewport, and generate the grid only once
        # they click "Capture Shape".
        _active_capture_dialog = DrawShapeCaptureDialog(
            chunk, spacing, margin, prefix, use_mesh, clip_to_shape
        )
        _active_capture_dialog.show()
        return

    # Immediate flow: bounding box is already fully determined right now.
    polygon_xy = None
    if source == GridMarkerDialog.SOURCE_MARKERS:
        bbox = get_bbox_from_markers(chunk)
    elif source == GridMarkerDialog.SOURCE_REGION:
        bbox = get_bbox_from_region(chunk)
    else:
        bbox, shape_polygon = get_shape_geometry(chunk, values["shape"])
        if clip_to_shape:
            polygon_xy = shape_polygon

    if bbox is None:
        return

    run_grid_placement(chunk, bbox, spacing, margin, prefix, use_mesh, polygon_xy=polygon_xy)


if __name__ == "__main__":
    main()
