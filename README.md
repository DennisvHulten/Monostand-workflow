# Grid Projection in Metashape Pro

Repository for the workflow presented in **van Hulten et al., 2025** [link]  
This workflow is designed to create spatially explicit sampling designs for locally dominant or monostand-forming organisms.

---

## Workflow

1. **Import images** into [Agisoft Metashape Pro](https://www.agisoft.com/) (≥ version **2.2.1**) and align photos.  
2. **Check alignment** and build a **dense cloud**.  
3. **Scale the model** with scale bars and align the **z-axis** with the gravitational up vector by assigning a z value to ground control points.  
4. *(Optional)* Build the **DEM** and **Orthomosaic** for higher resolution imagery.  
   - Best results for orthomosaics are based on the **DEM**, not the point cloud.  
   - Example comparison:  
     ![Ortho vs Point Cloud](path/to/ortho_vs_pointcloud.png)  
5. Run the script:  
   - `Tools -> Run Script...`  
   - Select **`project_grid_metashape.py`**  
   - Leave arguments blank.  
6. **Choose parameters** in the dialog:  
   - **Spacing** — distance between grid points in meters (float).  
   - **Target region** — either the full region or a sub-area defined by 4 markers (`TL`, `TR`, `BL`, `BR`).  
   - **Source** — whether to use the **Point Cloud** or the **Mesh** for point projection.  

- Example result:

  ![Projected Grid Result](/images/Example_area_projection.jpg)


---

## Notes

- No external dependencies are required — only **Metashape Pro**.  
- The script automatically **saves your project** after each run.  
- On repeated runs, previously projected grid points (`G_###`) are deleted.  
  - If you want to keep markers, **save or rename them** before re-running.  

---

## Citation

If you use this workflow in your research, please cite:  

> van Hulten et al. (2025). *Title of the paper*. [link]

---

## License

This repository is released under the [MIT License](LICENSE).
     
