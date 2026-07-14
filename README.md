# Grid Projection in Metashape Pro

![License](https://img.shields.io/badge/license-GPL--3.0-blue)
![Metashape](https://img.shields.io/badge/Metashape%20Pro-%E2%89%A5%202.2.1-teal)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)

Repository for the workflow presented in **van Hulten et al. (in prep)** [link]

This workflow supports the creation of **spatially explicit sampling designs** for locally dominant or monostand-forming marine organisms. It uses Structure-from-Motion (SfM) photogrammetry in [Agisoft Metashape Pro](https://www.agisoft.com/) to reconstruct a 3D model of a reef area, then projects a regular grid of sampling points onto that model — giving a systematic, spatially referenced sampling scheme across dense, boundary-less coral stands that would otherwise be very difficult to sample rigorously.

---

## Repository contents

| File | Description |
|---|---|
| `project_grid_metashape.py` | Metashape Python script that generates a grid of markers projected onto a point cloud or mesh, within a bounding box defined by markers or the current region. |
| `Monostand_workflow.ipynb` | [ONE-LINE DESCRIPTION NEEDED — e.g. "Post-processing notebook for linking projected grid coordinates to genotype/sample metadata and generating stand composition maps."] |
| `images/` | Example figures referenced in this README. |
| `LICENSE` | GNU General Public License v3.0. |

---

## Requirements

- [Agisoft Metashape Pro](https://www.agisoft.com/) ≥ version **2.2.1**
- PySide2 (bundled with Metashape Pro's Python environment — no separate install needed)
- No external Python dependencies beyond the Metashape Python API for `project_grid_metashape.py`
- For `Monostand_workflow.ipynb`: [LIST NOTEBOOK DEPENDENCIES HERE — e.g. numpy, pandas, matplotlib, geopandas]

---

## Workflow

1. **Import images** into Agisoft Metashape Pro (≥ version **2.2.1**) and align photos.
2. **Check alignment** and build a **dense cloud**.
3. **Scale the model** with scale bars and align the **z-axis** with the gravitational up vector by assigning a z value to ground control points.
4. *(Optional)* Build the **DEM** and **Orthomosaic** for higher resolution imagery.
   - Best results for orthomosaics are based on the **DEM**, not the point cloud.
   - Example comparison:

     ![Ortho vs Point Cloud](images/ortho_vs_pointcloud.png)

5. Run the script:
   - `Tools -> Run Script...`
   - Select **`project_grid_metashape.py`**
   - Leave arguments blank.
6. **Choose parameters** in the dialog:
   - **Spacing** — distance between grid points in meters (float).
   - **Target region** — either the full region or a sub-area defined by 4 markers (`TL`, `TR`, `BL`, `BR`).
   - **Source** — whether to use the **Point Cloud** or the **Mesh** for point projection.

   Example result:

   ![Projected Grid Result](images/Example_area_projection.jpg)

---

## Notes

- No external dependencies are required beyond Metashape Pro's bundled Python environment.
- The script automatically **saves your project** after each run.
- On repeated runs, previously projected grid markers (`G_###`) are deleted.
  - If you want to keep markers, **save or rename them** before re-running.

---

## Citation

If you use this workflow in your research, please cite:

> van Hulten, D., Yuval, M., Liggins, L., Sewell, M. A., & Bongaerts, P. (in prep). *[Full paper title]*. [DOI/link once published]

A citable, versioned snapshot of this repository is also available via Zenodo: [DOI badge/link once archived]

---

## License

This repository is released under the [GNU General Public License v3.0 (GPL-3.0)](LICENSE).

## Contact

Questions or issues? Open a [GitHub Issue](../../issues) or contact Dennis van Hulten at dvanhulten@calacademy.org.
