
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from astropy.table import Table
from reproject import reproject_interp

from fits_loader import load_spherex_fits
from quality_control import create_quality_mask
from spectral_matching import create_wavelength_map


def compare_images(data1, data2, wavelength_tolerance=0.005):
    """
    Compare two SPHEREx observations in the same sky frame.

    wavelength_tolerance is in micrometers.
    It is a provisional analysis threshold.
    """

    # Use zodiacal-light-subtracted images when fits_loader provides them.
    image1 = data1.get("science_image", data1["image"])
    image2 = data2.get("science_image", data2["image"])

    variance1 = data1["variance"]
    variance2 = data2["variance"]

    # 1. Quality masks
    quality1, _ = create_quality_mask(data1)
    quality2, _ = create_quality_mask(data2)

    # 2. Align second image to first image
    aligned_image2, footprint = reproject_interp(
        (image2, data2["wcs"]),
        data1["wcs"],
        shape_out=image1.shape
    )

    # 3. Align variance (approximation)
    aligned_variance2, _ = reproject_interp(
        (variance2, data2["wcs"]),
        data1["wcs"],
        shape_out=image1.shape
    )

    # 4. Align quality mask
    aligned_quality2, _ = reproject_interp(
        (quality2.astype(np.float32), data2["wcs"]),
        data1["wcs"],
        shape_out=image1.shape,
        order="nearest-neighbor"
    )

    # 5. Compare wavelengths at same sky positions
    wave1 = create_wavelength_map(data1)
    wave2 = create_wavelength_map(data2)

    aligned_wave2, _ = reproject_interp(
        (wave2, data2["wcs"]),
        data1["wcs"],
        shape_out=image1.shape
    )

    spectral_difference = np.abs(
        wave1 - aligned_wave2
    )


    # -----------------------------------
    # Diagnostic masks
    # -----------------------------------

    spatial = (
        (footprint > 0)
        & np.isfinite(image1)
        & np.isfinite(aligned_image2)
    )

    quality = (
        quality1
        & (aligned_quality2 > 0.5)
    )

    variance_valid = (
        np.isfinite(variance1)
        & np.isfinite(aligned_variance2)
        & (variance1 > 0)
        & (aligned_variance2 > 0)
    )

    spectral_finite = np.isfinite(
        spectral_difference
    )

    spectral_valid = (
        spectral_finite
        & (spectral_difference <= wavelength_tolerance)
    )

    print("\n--- Comparison diagnostics ---")
    print("Total pixels:", image1.size)
    print("Spatial overlap:", np.count_nonzero(spatial))
    print("Quality valid:", np.count_nonzero(spatial & quality))
    print(
        "Variance valid:",
        np.count_nonzero(spatial & quality & variance_valid)
    )
    print(
        "Spectral map finite:",
        np.count_nonzero(spatial & spectral_finite)
    )
    print(
        "Spectral compatible:",
        np.count_nonzero(spatial & spectral_valid)
    )

    pre_spectral = spatial & quality & variance_valid

    print(
        "Valid before spectral filtering:",
        np.count_nonzero(pre_spectral)
    )
    print(
        "Final valid:",
        np.count_nonzero(pre_spectral & spectral_valid)
    )

    spectral_values = spectral_difference[
        spatial & spectral_finite
    ]

    if spectral_values.size > 0:
        print("\nWavelength differences (um):")
        print("Minimum:", float(np.min(spectral_values)))
        print("Median:", float(np.median(spectral_values)))
        print("Maximum:", float(np.max(spectral_values)))

        for tolerance in [0.005, 0.01, 0.02, 0.05]:
            count = np.count_nonzero(
                pre_spectral
                & spectral_finite
                & (spectral_difference <= tolerance)
            )
            print(
                f"Pixels within {tolerance} um:",
                count
            )


    # 6. Combined validity mask
    valid = (
        quality1
        & (aligned_quality2 > 0.5)
        & (footprint > 0)
        & np.isfinite(image1)
        & np.isfinite(aligned_image2)
        & np.isfinite(variance1)
        & np.isfinite(aligned_variance2)
        & (variance1 > 0)
        & (aligned_variance2 > 0)
        & np.isfinite(spectral_difference)
        & (spectral_difference <= wavelength_tolerance)
    )

    # 7. Difference map
    difference = np.full(
        image1.shape, np.nan, dtype=np.float32
    )

    difference[valid] = (
        aligned_image2[valid] - image1[valid]
    )

    # 8. Approximate significance map
    significance = np.full(
        image1.shape, np.nan, dtype=np.float32
    )

    combined_variance = np.full(
        image1.shape, np.nan, dtype=np.float32
    )
    combined_variance[valid] = (
        variance1[valid] + aligned_variance2[valid]
    )

    significance[valid] = (
        difference[valid] / np.sqrt(combined_variance[valid])
    )

    return {
        "image1": image1,
        "aligned_image2": aligned_image2,
        "difference": difference,
        "significance": significance,
        "combined_variance": combined_variance,
        "valid_mask": valid,
        "spectral_difference": spectral_difference,
    }


def save_comparison_figure(result, output_path):

    image1 = result["image1"]
    image2 = result["aligned_image2"]
    difference = result["difference"]
    significance = result["significance"]

    fig, axes = plt.subplots(
        2, 2, figsize=(14, 12)
    )

    axes[0, 0].imshow(
        image1, origin="lower",
        cmap="gray", vmin=0, vmax=1
    )
    axes[0, 0].set_title("SPHEREx Image 1")

    axes[0, 1].imshow(
        image2, origin="lower",
        cmap="gray", vmin=0, vmax=1
    )
    axes[0, 1].set_title("SPHEREx Image 2 (Aligned)")

    axes[1, 0].imshow(
        difference, origin="lower",
        cmap="coolwarm", vmin=-0.5, vmax=0.5
    )
    axes[1, 0].set_title("Difference Map")

    axes[1, 1].imshow(
        significance, origin="lower",
        cmap="coolwarm", vmin=-5, vmax=5
    )
    axes[1, 1].set_title("Approximate Significance Map")

    for ax in axes.flat:
        ax.set_xlabel("X pixel")
        ax.set_ylabel("Y pixel")

    plt.tight_layout()
    plt.savefig(
        output_path, dpi=150, bbox_inches="tight"
    )
    plt.close(fig)


if __name__ == "__main__":

    base_dir = Path(__file__).resolve().parent.parent
    raw_dir = base_dir / "data" / "raw"
    output_dir = base_dir / "data" / "processed"

    output_dir.mkdir(
        parents=True, exist_ok=True
    )

    pairs = Table.read(
        base_dir / "data" / "candidate_pairs.csv",
        format="csv"
    )

    pair = pairs[0]

    filename1 = str(pair["url_1"]).split("/")[-1]
    filename2 = str(pair["url_2"]).split("/")[-1]

    print("\nLoading SPHEREx images...")

    data1 = load_spherex_fits(
        raw_dir / filename1
    )

    data2 = load_spherex_fits(
        raw_dir / filename2
    )

    print("Image 1:", filename1)
    print("Image 2:", filename2)

    print("\nRunning image comparison...")

    result = compare_images(data1, data2)



    # -----------------------------------
    # Background offset diagnostic
    # -----------------------------------

    valid = result["valid_mask"]
    difference = result["difference"]

    background_offset = float(
        np.median(difference[valid])
    )

    corrected_difference = np.full(
        difference.shape, np.nan, dtype=np.float32
    )

    corrected_difference[valid] = (
        difference[valid] - background_offset
    )

    # Reuse the same approximate variance model
    # to isolate the effect of offset subtraction.
    original_significance = result["significance"]

    corrected_significance = np.full(
        difference.shape, np.nan, dtype=np.float32
    )

    original_noise = np.divide(
        difference[valid],
        original_significance[valid],
        out=np.full(
            np.count_nonzero(valid),
            np.nan,
            dtype=np.float32
        ),
        where=original_significance[valid] != 0
    )

    noise_valid = np.isfinite(original_noise) & (
        original_noise > 0
    )

    corrected_values = corrected_significance[valid]
    corrected_values[noise_valid] = (
        corrected_difference[valid][noise_valid]
        / original_noise[noise_valid]
    )
    corrected_significance[valid] = corrected_values

    print("\nBackground Correction Diagnostics")
    print("---------------------------------")

    print(
        "Estimated background offset:",
        background_offset,
        "MJy/sr"
    )

    print(
        "Corrected median difference:",
        float(np.median(corrected_difference[valid]))
    )

    corrected_s = corrected_significance[
        np.isfinite(corrected_significance)
    ]

    print(
        "Corrected significance median:",
        float(np.median(corrected_s))
    )

    print(
        "Corrected significance std:",
        float(np.std(corrected_s))
    )

    print(
        "Corrected pixels with |S| > 5:",
        int(np.count_nonzero(np.abs(corrected_s) > 5))
    )

    valid = result["valid_mask"]
    difference = result["difference"]
    significance = result["significance"]

    valid_difference = difference[valid]
    valid_significance = significance[valid]

    print("\nDifference Diagnostics")
    print("----------------------")

    print(
        "Median difference:",
        float(np.median(valid_difference)),
        "MJy/sr"
    )

    print(
        "Mean difference:",
        float(np.mean(valid_difference)),
        "MJy/sr"
    )

    print(
        "Median significance:",
        float(np.median(valid_significance))
    )

    print(
        "Significance standard deviation:",
        float(np.std(valid_significance))
    )

    for threshold in [3, 5, 10]:
        count = np.count_nonzero(
            np.abs(valid_significance) > threshold
        )

        print(
            f"Pixels with |S| > {threshold}:",
            count
        )


    valid = result["valid_mask"]
    significance = result["significance"]

    print("\nImage Comparison Results")
    print("------------------------")

    print(
        "Valid pixels:",
        np.count_nonzero(valid)
    )

    print(
        "Valid percentage:",
        round(100 * np.mean(valid), 2),
        "%"
    )

    print(
        "Pixels with |significance| > 5:",
        np.count_nonzero(
            np.abs(significance[valid]) > 5
        )
    )

    output_path = (
        output_dir / "image_comparison.png"
    )

    save_comparison_figure(
        result, output_path
    )

    print("\nSaved figure:", output_path)
    print("Image comparison completed.")
