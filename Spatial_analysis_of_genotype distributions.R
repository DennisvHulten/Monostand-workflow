## ============================================================================
## Clonal assessment & spatial distribution workflow
## Part of: https://github.com/DennisvHulten/Monostand-workflow
##
## What this script does:
##   1. Loads a pairwise genetic distance (IBS) matrix and sample metadata.
##   2. Helps you choose a clonal-distance cutoff by inspecting per-site
##      dendrograms (and, optionally, known genotyping-replicate pairs).
##   3. Cuts the tree at that cutoff to assign clone lineages, merging
##      singleton samples into one placeholder group for plotting.
##   4. Calculates, per clone, how spatially spread out its samples are
##      (distance from each sample to its clone's spatial centroid).
##   5. Produces a combined figure: coloured dendrogram + spatial-spread
##      panel, side by side, ready to save as a vector figure.
##   6. Optionally, produces a genotype map per site: orthomosaic background,
##      monostand/patch outlines, sample points coloured by clone lineage,
##      and minimum-spanning-tree connector lines linking ramets of the
##      same clone.
##
## This script is written to be adapted to your own data: everything you
## need to change lives in the "USER SETTINGS" block below. You shouldn't
## need to edit anything past that point unless you want to change the
## analysis itself.
## ============================================================================

library(sparcl)      # ColorDendrogram()
library(readr)        # read_csv()
library(dendextend)   # dendrogram colouring helpers
library(ggdendro)     # dendrogram -> data frame conversion for ggplot
library(ggplot2)
library(patchwork)    # combine ggplot panels
library(RColorBrewer)
library(ggtree)
library(ape)
library(dplyr)
library(tibble)
library(colorspace)
library(terra)        # raster (orthomosaic) handling
library(tidyterra)     # geom_spatraster() for plotting rasters with ggplot
library(sf)            # vector (monostand outline) handling
library(randomcoloR)   # distinctColorPalette()
library(igraph)        # minimum spanning tree for within-clone connector lines
library(purrr)         # map_dfr()
library(ggrepel)       # optional point labelling on genotype maps


## ============================================================================
## USER SETTINGS -- edit this block for your own dataset
## ============================================================================

# --- Input files ------------------------------------------------------------
# A single-column text file listing sample IDs in the same order as the rows
# and columns of the IBS matrix below.
bam_order_file <- "path/to/sample_names_bam_order.txt"

# Pairwise genetic distance (IBS) matrix, e.g. produced by ANGSD.
ibs_matrix_file <- "path/to/data.ibsMat"

# Sample metadata, must contain a sample ID column plus x/y/z spatial
# coordinates for each sample (e.g. from a photogrammetry model).
metadata_file <- "path/to/metadata.csv"

# --- Output ------------------------------------------------------------------
output_dir <- "path/to/figures"
dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)

# --- Column names in your metadata file --------------------------------------
# The script joins tree tips to metadata rows using these columns.
id_column <- "Sample_id"
x_column  <- "world_x"
y_column  <- "world_y"
z_column  <- "world_z"

# --- Sample ID handling -------------------------------------------------------
# If your sample IDs carry a suffix that should be ignored when matching
# physical samples to metadata (e.g. a tissue-replicate or extraction-batch
# tag), give a regex here to strip it. Leave as "" to skip this step.
# Example: "_(SHA|HEL)$" strips a trailing "_SHA" or "_HEL" tag.
id_suffix_pattern <- ""

# How to derive a site/location code from each sample ID, used only for the
# exploratory per-site clustering step below. This default takes whatever
# follows the final underscore (e.g. "SAMPLE01_REEF_SNA" -> "SNA"). If your
# site information instead lives in a metadata column, replace this with a
# join to that column.
get_location <- function(sample_ids) sub(".*_", "", sample_ids)

# --- Clonal distance cutoff ---------------------------------------------------
# Distance threshold below which two samples are considered the same clone.
# Start with a rough guess, inspect the per-site dendrograms and (if
# supplied) known replicate pairs below, then adjust before the final run.
clonal_cutoff <- 0.0156

# --- Known genotyping replicates (optional) -----------------------------------
# If you re-extracted/re-sequenced any samples as a deliberate check (i.e.
# you *know* these pairs are the same physical individual), list them here
# as a list of character vectors. This is used only to sanity-check your
# chosen cutoff -- it does not affect clone assignment itself. Leave as an
# empty list if you have none.
#
# Example:
# known_replicate_pairs <- list(
#   c("SAMPLE01_A", "SAMPLE01_B"),
#   c("SAMPLE14_A", "SAMPLE14_B")
# )
known_replicate_pairs <- list()

# --- Manual sample exclusions (optional) ---------------------------------------
# Any sample IDs (after suffix stripping, if used above) to drop before the
# final clonal assignment -- e.g. a sample flagged during QC as mislabelled
# or otherwise unreliable. Leave as character(0) if none.
exclude_samples <- character(0)

# --- Orthomosaic genotype maps (optional) ---------------------------------------
# Column in your metadata identifying which site/plot each sample belongs
# to. Used to match samples to the right orthomosaic below.
site_column <- "Site"

# One entry per site/plot you want a genotype map for, named to match the
# values in `site_column` above. Each entry needs:
#   ortho   -- path to the orthomosaic .tif
#   outline -- path to a vector file (e.g. .gpkg) of monostand/patch outlines
#   bbox    -- optional crop extent as c(xmin, xmax, ymin, ymax), in the
#              orthomosaic's own coordinates. NULL keeps the full extent.
# Leave the list empty (as below) to skip this step entirely. Use
# preview_orthomosaic() further down to check an orthomosaic's full extent
# before deciding on a crop bbox.
#
# Example:
# orthomosaic_sites <- list(
#   "Jicaral" = list(
#     ortho = "path/to/mex_jic_ortho.tif",
#     outline = "path/to/mex_jic_monostands.gpkg",
#     bbox = c(-10, 17.5, -27.5, 7.5)
#   )
# )
orthomosaic_sites <- list()


## ============================================================================
## HELPER FUNCTIONS -- shouldn't need editing below this point
## ============================================================================

#' Cut a dendrogram at a distance cutoff and assign clone lineages.
#'
#' Singleton groups (samples with no genetic match within the cutoff) are
#' merged into a single placeholder group for plotting purposes, since
#' plotting dozens of one-sample "clusters" as separate colours isn't
#' informative. The ID of that placeholder group is returned alongside the
#' assignment so it can be excluded from downstream per-clone analyses
#' (a group of singletons has no meaningful "clone", so it doesn't belong
#' in a per-clone spatial spread calculation, for example).
#'
#' @param hc hclust object.
#' @param cutoff Distance cutoff to cut the tree at.
#' @return A list with:
#'   assignment        -- named integer vector, one entry per sample.
#'   singleton_group_id -- the group ID used for the merged singletons.
assign_clonal_groups <- function(hc, cutoff) {
  cc <- cutree(hc, h = cutoff)
  group_sizes <- table(cc)
  singleton_ids <- as.numeric(names(group_sizes)[group_sizes == 1])
  
  singleton_group_id <- NA_real_
  if (length(singleton_ids) > 0) {
    singleton_group_id <- singleton_ids[1]
    cc[cc %in% singleton_ids] <- singleton_group_id
  }
  
  list(assignment = cc, singleton_group_id = singleton_group_id)
}

#' Build a colour palette for a set of clonal groups.
#'
#' @param groups Integer vector of group assignments (as returned by
#'   assign_clonal_groups()$assignment).
#' @return Named character vector mapping each group ID to a hex colour.
make_group_colors <- function(groups) {
  group_levels <- sort(unique(groups))
  n_groups <- length(group_levels)
  palette <- colorRampPalette(brewer.pal(min(8, n_groups), "Set2"))(n_groups)
  setNames(palette, group_levels)
}

#' Plot a dendrogram coloured by clonal group, with the cutoff marked.
#'
#' @param hc hclust object.
#' @param groups Named integer vector of group assignments.
#' @param colors Named vector mapping group IDs to colours.
#' @param cutoff Distance cutoff to draw as a dashed line.
#' @param main Plot title.
#' @param branchlength Passed to ColorDendrogram(); controls the length of
#'   the coloured bars beneath each leaf.
#' @param save_path Optional file path (e.g. ending in .svg) to also save
#'   the plot to, via svglite. If NULL, the plot is only drawn to the
#'   current graphics device.
#' @param width,height Figure dimensions in inches, used only if save_path
#'   is given.
plot_clonal_dendrogram <- function(hc, groups, colors, cutoff, main = "",
                                   branchlength = 0.0022, save_path = NULL,
                                   width = 8, height = 8) {
  sample_colors <- colors[as.character(groups)]
  
  draw <- function() {
    ColorDendrogram(hc, y = sample_colors, labels = FALSE,
                    branchlength = branchlength, main = main)
    abline(h = cutoff, col = "red", lty = 3)
  }
  
  if (!is.null(save_path)) {
    svglite::svglite(save_path, width = width, height = height, bg = "transparent")
    draw()
    dev.off()
  }
  draw()
}

#' Highlight known replicate pairs on a dendrogram (black/red), as a visual
#' check that your chosen cutoff comfortably separates true replicates from
#' everything else. Purely diagnostic -- does not feed into clone assignment.
#'
#' @param hc hclust object.
#' @param sample_ids Character vector of sample IDs in the same order used
#'   to build hc.
#' @param replicate_pairs List of character vectors, each giving the sample
#'   IDs belonging to one known-replicate group.
#' @param cutoff Distance cutoff to draw as a dashed line.
plot_replicate_check <- function(hc, sample_ids, replicate_pairs, cutoff,
                                 branchlength = 0.0022) {
  if (length(replicate_pairs) == 0) {
    message("No known_replicate_pairs supplied -- skipping replicate check plot.")
    return(invisible(NULL))
  }
  replicate_samples <- unlist(replicate_pairs)
  sample_colors <- rep("black", length(sample_ids))
  sample_colors[sample_ids %in% replicate_samples] <- "red"
  
  ColorDendrogram(hc, y = sample_colors, labels = FALSE, branchlength = branchlength,
                  main = "Known replicate pairs (red) vs. all other samples (black)")
  abline(h = cutoff, col = "red", lty = 3)
}

#' Add, per group, each sample's distance from its group's spatial centroid.
#'
#' @param df Data frame containing one row per sample, with a grouping
#'   column and x/y/z coordinate columns.
#' @param group_col Name of the grouping column (e.g. clone lineage).
#' @param x_col,y_col,z_col Names of the coordinate columns.
#' @return df with centroid_x, centroid_y, centroid_z, and centroid_dist
#'   columns added.
add_centroid_distances <- function(df, group_col, x_col, y_col, z_col) {
  df %>%
    group_by(.data[[group_col]]) %>%
    mutate(
      centroid_x = mean(.data[[x_col]], na.rm = TRUE),
      centroid_y = mean(.data[[y_col]], na.rm = TRUE),
      centroid_z = mean(.data[[z_col]], na.rm = TRUE),
      centroid_dist = sqrt(
        (.data[[x_col]] - centroid_x)^2 +
          (.data[[y_col]] - centroid_y)^2 +
          (.data[[z_col]] - centroid_z)^2
      )
    ) %>%
    ungroup()
}

#' Build the combined "dendrogram + spatial spread" figure.
#'
#' Left panel: the dendrogram, branches coloured by clone lineage.
#' Right panel: each sample's distance from its clone's spatial centroid,
#' plotted against the same vertical (tip) ordering as the tree, so the two
#' panels line up sample-for-sample.
#'
#' @param hc hclust object.
#' @param tip_metadata Data frame with one row per sample, containing at
#'   least id_col, group_col, and a centroid_dist column (see
#'   add_centroid_distances()).
#' @param id_col Name of the sample ID column in tip_metadata.
#' @param group_col Name of the clone-lineage column in tip_metadata.
#' @param colors Optional named vector mapping group values to colours. If
#'   NULL, a palette is generated automatically.
#' @return A patchwork object (tree panel + distance panel).
make_tree_distance_plot <- function(hc, tip_metadata, id_col, group_col, colors = NULL) {
  tree <- ggtree(hc)
  tree_data <- tree$data
  
  tip_map <- tree_data %>%
    filter(isTip) %>%
    mutate(label = as.character(label)) %>%
    left_join(tip_metadata, by = setNames(id_col, "label"))
  
  tip_map[[group_col]] <- as.character(tip_map[[group_col]])
  tip_map[[group_col]][is.na(tip_map[[group_col]])] <- "Unassigned"
  tip_map[[group_col]] <- factor(tip_map[[group_col]])
  
  clone_pos <- tip_map %>%
    group_by(.data[[group_col]]) %>%
    summarise(y_tree = median(y, na.rm = TRUE), .groups = "drop")
  
  if (is.null(colors)) {
    group_levels <- sort(unique(tip_map[[group_col]]))
    colors <- setNames(
      qualitative_hcl(length(group_levels), palette = "Dark 3"),
      group_levels
    )
  }
  
  plot_dat <- tip_metadata %>%
    mutate(!!group_col := as.factor(.data[[group_col]])) %>%
    left_join(clone_pos, by = group_col)
  
  p_tree <- tree %<+% tip_map +
    geom_tree(aes(color = .data[[group_col]]), linewidth = 0.2) +
    scale_color_manual(values = colors) +
    theme_tree2() +
    theme(legend.position = "none")
  
  p_dist <- ggplot(plot_dat, aes(x = centroid_dist, y = y_tree)) +
    geom_line(aes(group = .data[[group_col]], color = .data[[group_col]]), linewidth = 0.2) +
    geom_point(aes(color = .data[[group_col]]), size = 1) +
    scale_color_manual(values = colors) +
    theme_minimal() +
    theme(axis.title.y = element_blank(), legend.position = "none")
  
  p_tree + p_dist + plot_layout(widths = c(1, 1.2))
}

#' Quickly plot a full orthomosaic to help you choose a crop bbox.
#'
#' @param ortho_path Path to the orthomosaic .tif.
#' @param grayscale If TRUE (default), converts to greyscale, which usually
#'   makes coloured genotype points/lines much easier to read against a
#'   busy reef image than the raw colour orthomosaic.
#' @return The ggplot object (also drawn to the current device).
preview_orthomosaic <- function(ortho_path, grayscale = TRUE) {
  ortho <- terra::rast(ortho_path)
  terra::crs(ortho) <- NA
  
  if (grayscale) {
    ortho <- 0.2989 * ortho[[1]] + 0.5870 * ortho[[2]] + 0.1140 * ortho[[3]]
  }
  
  p <- ggplot() + tidyterra::geom_spatraster(data = ortho, maxcell = 2e6)
  if (grayscale) p <- p + scale_fill_gradient(low = "black", high = "white", guide = "none")
  print(p)
  p
}

#' Build a genotype map: orthomosaic background, monostand/patch outlines,
#' sample points coloured by clone lineage, and connector lines linking
#' ramets of the same clone (drawn as a minimum spanning tree, so clones
#' with many ramets don't turn into an unreadable tangle of pairwise lines).
#'
#' @param ortho_path Path to the orthomosaic .tif.
#' @param outline_path Path to a vector file of stand/patch outlines (e.g. a
#'   .gpkg produced by tracing polygons in Metashape or QGIS).
#' @param site_metadata Data frame of samples for this site/plot, with x/y
#'   coordinate columns and a clone-lineage column. Should include samples
#'   with lineage 0 (unique genotypes, see STEP 4) if you want them shown.
#' @param group_col Name of the clone-lineage column in site_metadata.
#' @param x_col,y_col Names of the coordinate columns in site_metadata.
#' @param bbox Optional crop extent as c(xmin, xmax, ymin, ymax). NULL keeps
#'   the full orthomosaic extent.
#' @param grayscale If TRUE (default), the orthomosaic is converted to
#'   greyscale so coloured points/lines stand out clearly.
#' @param colors Optional named vector mapping clone-lineage values to
#'   colours. If NULL, a distinct palette is generated automatically, with
#'   lineage 0 (unique genotypes) forced to black.
#' @param label_col Optional column name in site_metadata to label points
#'   with (e.g. a monostand/patch ID). NULL (default) draws no labels.
#' @param save_path Optional file path (e.g. ending in .svg) to save the
#'   figure to, via svglite.
#' @return The ggplot object.
make_genotype_map <- function(ortho_path, outline_path, site_metadata,
                              group_col, x_col, y_col, bbox = NULL,
                              grayscale = TRUE, colors = NULL, label_col = NULL,
                              save_path = NULL, width = 8, height = 8) {
  ortho <- terra::rast(ortho_path)
  outlines <- terra::vect(outline_path)
  
  # Orthomosaics from local (non-georeferenced) photogrammetry chunks often
  # carry no meaningful CRS; stripping it avoids terra/sf trying to
  # reconcile a CRS mismatch between the raster, the outlines, and the
  # world_x/world_y sample coordinates, which also have no real-world CRS.
  terra::crs(ortho) <- NA
  terra::crs(outlines) <- NA
  
  if (grayscale) {
    ortho <- 0.2989 * ortho[[1]] + 0.5870 * ortho[[2]] + 0.1140 * ortho[[3]]
  }
  if (!is.null(bbox)) {
    ortho <- terra::crop(ortho, terra::ext(bbox))
  }
  
  outlines_sf <- sf::st_as_sf(outlines)
  
  # Colour palette. Lineage 0 marks samples not assigned to a multi-sample
  # clone (see STEP 4) and is always forced to black, so "this one is a
  # singleton" reads consistently across every map.
  group_values <- site_metadata[[group_col]]
  if (is.null(colors)) {
    group_levels <- sort(unique(group_values))
    colors <- randomcoloR::distinctColorPalette(length(group_levels))
    names(colors) <- group_levels
  }
  if (0 %in% group_values) colors[as.character(0)] <- "black"
  
  # Within-clone connector lines: for each clone with more than one sample,
  # connect its ramets with a minimum spanning tree.
  connector_lines <- site_metadata %>%
    filter(.data[[group_col]] != 0) %>%
    group_split(.data[[group_col]]) %>%
    purrr::map_dfr(function(df) {
      coords <- as.matrix(df[, c(x_col, y_col)])
      if (nrow(coords) < 2) return(NULL)
      
      d <- as.matrix(dist(coords))
      g <- igraph::graph_from_adjacency_matrix(d, mode = "undirected",
                                               weighted = TRUE, diag = FALSE)
      mst_g <- igraph::mst(g, weights = igraph::E(g)$weight)
      
      edgelist <- igraph::as_edgelist(mst_g)
      edgelist <- matrix(as.numeric(edgelist), ncol = 2)
      
      data.frame(
        x = coords[edgelist[, 1], 1], y = coords[edgelist[, 1], 2],
        xend = coords[edgelist[, 2], 1], yend = coords[edgelist[, 2], 2],
        group = df[[group_col]][1]
      )
    })
  
  p <- ggplot() + tidyterra::geom_spatraster(data = ortho, maxcell = 2e6)
  if (grayscale) p <- p + scale_fill_gradient(low = "black", high = "white", guide = "none")
  
  p <- p +
    geom_segment(
      data = connector_lines,
      aes(x = x, y = y, xend = xend, yend = yend, color = factor(group)),
      alpha = 0.5, linewidth = 0.7
    ) +
    geom_sf(data = outlines_sf, fill = NA, color = "black", linewidth = 1) +
    geom_point(
      data = site_metadata,
      aes(x = .data[[x_col]], y = .data[[y_col]], color = factor(.data[[group_col]])),
      size = 3
    ) +
    scale_color_manual(values = colors, name = paste0("Genotype (", group_col, ")")) +
    coord_sf() +
    labs(x = "X", y = "Y") +
    theme(axis.title.y = element_text(angle = 0, vjust = 0.5))
  
  if (!is.null(label_col)) {
    p <- p + ggrepel::geom_label_repel(
      data = site_metadata,
      aes(x = .data[[x_col]], y = .data[[y_col]], label = .data[[label_col]]),
      size = 3
    )
  }
  
  if (!is.null(save_path)) {
    svglite::svglite(save_path, width = width, height = height, bg = "transparent")
    print(p)
    dev.off()
  }
  
  print(p)
  p
}


## ============================================================================
## STEP 1: Load data
## ============================================================================

bams <- read.table(bam_order_file, header = FALSE)
sample_ids <- bams$V1

if (nzchar(id_suffix_pattern)) {
  sample_ids <- gsub(id_suffix_pattern, "", sample_ids)
}

ma <- as.matrix(read.table(ibs_matrix_file))
dimnames(ma) <- list(sample_ids, sample_ids)

metadata <- read_csv(metadata_file)


## ============================================================================
## STEP 2: Exploratory per-site clustering
##
## Purpose: get a feel for where a sensible clonal-distance cutoff sits
## before committing to one for the whole dataset. This step only plots to
## the screen -- nothing is saved here.
## ============================================================================

location <- get_location(sample_ids)
print(table(location))

for (loc in unique(location)) {
  keep <- location == loc
  site_hc <- hclust(as.dist(ma[keep, keep]), method = "ave")
  
  plot(site_hc, main = paste("Location:", loc), cex = 0.6)
  abline(h = clonal_cutoff, col = "red", lty = 3)
}

# If you have known genotyping replicates, this overlays them on the full
# dendrogram (black = everything else, red = known replicate pairs) so you
# can confirm your cutoff separates them cleanly from non-replicate pairs.
hc_full <- hclust(as.dist(ma), method = "ave")
plot_replicate_check(hc_full, sample_ids, known_replicate_pairs, clonal_cutoff)

# Look at the plots above, adjust `clonal_cutoff` in USER SETTINGS if needed,
# and re-run from here before moving on to the final assignment below.


## ============================================================================
## STEP 3: Final clonal assignment across the full dataset
## ============================================================================

result <- assign_clonal_groups(hc_full, clonal_cutoff)
cc <- result$assignment
singleton_group_id <- result$singleton_group_id
group_colors <- make_group_colors(cc)

plot_clonal_dendrogram(
  hc_full, cc, group_colors, clonal_cutoff,
  main = "All samples, coloured by clonal group",
  save_path = file.path(output_dir, "clone_dendrogram.svg")
)

# Histogram of pairwise node heights, with the cutoff marked -- a useful
# diagnostic for whether the cutoff sits in a clear gap between "same
# clone" and "different individual" distances.
svglite::svglite(file.path(output_dir, "node_height_histogram.svg"),
                 width = 8, height = 8, bg = "transparent")
hist(hc_full$height, breaks = 50,
     main = "Histogram of pairwise node heights",
     xlab = "Node height", col = "blue", border = "white")
abline(v = clonal_cutoff, col = "red", lty = 3)
dev.off()


## ============================================================================
## STEP 4: Merge clone assignments into metadata
## ============================================================================

pop_with_lineage <- tibble(
  !!id_column := names(cc),
  Clone_lineage = as.integer(cc)
)

# Samples in the merged-singleton placeholder group aren't a real "clone" --
# each is its own individual -- so they're marked as unassigned (0) here
# rather than lumped together in downstream per-clone analyses.
if (!is.na(singleton_group_id)) {
  pop_with_lineage$Clone_lineage[pop_with_lineage$Clone_lineage == singleton_group_id] <- 0
}

metadata <- left_join(metadata, pop_with_lineage, by = id_column)

meta_filtered <- metadata %>%
  filter(!Clone_lineage %in% c(0)) %>%
  filter(!is.na(Clone_lineage))

if (length(exclude_samples) > 0) {
  meta_filtered <- meta_filtered %>% filter(!.data[[id_column]] %in% exclude_samples)
}


## ============================================================================
## STEP 5: Spatial centroid distance analysis
## ============================================================================

meta_centroid <- add_centroid_distances(
  meta_filtered, group_col = "Clone_lineage",
  x_col = x_column, y_col = y_column, z_col = z_column
)


## ============================================================================
## STEP 6: Combined tree + spatial-spread figure
## ============================================================================

combined_plot <- make_tree_distance_plot(
  hc_full, meta_centroid,
  id_col = id_column, group_col = "Clone_lineage",
  colors = group_colors
)

print(combined_plot)

svglite::svglite(file.path(output_dir, "clone_tree_and_spatial_spread.svg"),
                 width = 8, height = 8, bg = "transparent")
print(combined_plot + theme(legend.position = "none"))
dev.off()


## ============================================================================
## STEP 7: Genotype maps on orthomosaics (optional)
##
## Skipped automatically if orthomosaic_sites is empty. Note this uses
## `metadata` (post clone-lineage merge, but before the STEP 4 filtering
## that dropped lineage-0/singleton samples) rather than `meta_centroid`,
## so unique genotypes still show up on the map -- coloured black, per the
## STEP 4 convention.
## ============================================================================

for (site_name in names(orthomosaic_sites)) {
  site_cfg <- orthomosaic_sites[[site_name]]
  
  site_data <- metadata %>%
    filter(!is.na(Clone_lineage), .data[[site_column]] == site_name)
  
  if (nrow(site_data) == 0) {
    warning("No samples found for site '", site_name, "' -- check site_column/orthomosaic_sites names match. Skipping.")
    next
  }
  
  make_genotype_map(
    ortho_path = site_cfg$ortho,
    outline_path = site_cfg$outline,
    site_metadata = site_data,
    group_col = "Clone_lineage",
    x_col = x_column, y_col = y_column,
    bbox = site_cfg$bbox,
    save_path = file.path(output_dir, paste0("genotype_map_", site_name, ".svg"))
  )
}

message("Done. Figures written to: ", output_dir)