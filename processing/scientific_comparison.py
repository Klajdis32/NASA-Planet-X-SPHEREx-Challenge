"""Web-safe wrapper around the project's existing scientific analysis modules."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.table import Table
from scipy.ndimage import binary_erosion

from candidate_detection import detect_candidates, save_candidate_figure
from candidate_quality import assess_candidate, get_cutout
from fits_loader import load_spherex_fits
from image_comparison import compare_images
from motion_candidates import find_motion_pairs, plot_motion_pairs
from psf_analysis import analyze_psf
from psf_matching import calculate_kernel_sigma, masked_gaussian_filter, robust_scatter


def _limits(values, percentiles=(2, 98), symmetric=False):
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        return (-1.0, 1.0)
    if symmetric:
        limit = float(np.percentile(np.abs(finite), percentiles[1]))
        return (-max(limit, 1e-12), max(limit, 1e-12))
    low, high = np.percentile(finite, percentiles)
    if high <= low:
        high = low + 1.0
    return float(low), float(high)


def _prepare_matched_images(result):
    """Match image resolution when the stellar measurements support it."""
    image1 = result["image1"].astype(np.float32, copy=True)
    image2 = result["aligned_image2"].astype(np.float32, copy=True)
    valid = result["valid_mask"].copy()
    details = {
        "status": "not_applied",
        "reason": "Too few reliable point sources for automatic PSF matching.",
        "source_count": 0,
        "fwhm_from_pixels": None,
        "fwhm_to_pixels": None,
        "kernel_sigma_pixels": 0.0,
    }

    try:
        fwhm1, fwhm2 = analyze_psf(result, max_sources=60)
        paired = np.isfinite(fwhm1) & np.isfinite(fwhm2)
        fwhm1, fwhm2 = fwhm1[paired], fwhm2[paired]
        details["source_count"] = int(len(fwhm1))
        if len(fwhm1) < 3:
            return image1, image2, valid, details

        width1 = float(np.median(fwhm1))
        width2 = float(np.median(fwhm2))
        details["fwhm_from_pixels"] = width1
        details["fwhm_to_pixels"] = width2
        if not (0.8 <= width1 <= 15 and 0.8 <= width2 <= 15):
            details["reason"] = "Measured PSF widths were outside the safe automatic range."
            return image1, image2, valid, details
        if abs(width1 - width2) < 0.15:
            details.update(status="already_matched", reason="The measured image resolutions already agree.")
            return image1, image2, valid, details

        if width1 < width2:
            kernel_sigma = calculate_kernel_sigma(width1, width2)
            image1 = masked_gaussian_filter(image1, valid, kernel_sigma)
            smoothed = "from"
        else:
            kernel_sigma = calculate_kernel_sigma(width2, width1)
            image2 = masked_gaussian_filter(image2, valid, kernel_sigma)
            smoothed = "to"

        # Convolution is unreliable close to gaps and cutout boundaries.
        margin = max(2, int(np.ceil(3 * kernel_sigma)))
        valid = binary_erosion(valid, iterations=margin, border_value=0)
        valid &= np.isfinite(image1) & np.isfinite(image2)
        details.update(
            status="applied",
            reason=f"The {smoothed} observation was broadened to the common resolution.",
            kernel_sigma_pixels=float(kernel_sigma),
        )
    except (RuntimeError, ValueError, TypeError) as exc:
        details["reason"] = f"Automatic PSF matching was skipped safely: {exc}"

    return image1, image2, valid, details


def _reliability_assessment(valid_percentage, wavelength_median, tolerance, noise_scale, psf):
    checks = {
        "coverage": valid_percentage >= 60.0,
        "wavelength": np.isfinite(wavelength_median) and wavelength_median <= tolerance,
        "noise": np.isfinite(noise_scale) and noise_scale <= 3.0,
        "resolution": psf["status"] in {"applied", "already_matched"},
    }
    passed = sum(checks.values())
    if passed == 4 and valid_percentage >= 80 and noise_scale <= 2:
        level, label = "high", "Strong technical quality"
    elif passed >= 3:
        level, label = "moderate", "Usable with caution"
    else:
        level, label = "low", "Exploratory only"
    return level, label, checks


def run_scientific_comparison(
    first_path, second_path, output_dir,
    wavelength_tolerance=0.005, sigma_threshold=5.0,
):
    """Run existing FLAGS/VARIANCE/WCS-WAVE analysis and save diagnostics."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nSPHEREx Scientific Comparison")
    print("=============================")
    print("Loading with processing/fits_loader.py")
    first = load_spherex_fits(first_path)
    second = load_spherex_fits(second_path)
    print("First:", first["metadata"]["date_obs"], first["metadata"]["filename"])
    print("Second:", second["metadata"]["date_obs"], second["metadata"]["filename"])
    print("ZODI subtraction: enabled")
    print("Quality flags: enabled via processing/quality_control.py")
    print("Variance significance: enabled")
    print("Wavelength tolerance:", wavelength_tolerance, "um")
    print("Candidate threshold:", sigma_threshold, "sigma")
    print("Running processing/image_comparison.py")

    result = compare_images(first, second, wavelength_tolerance=wavelength_tolerance)
    matched_image1, matched_image2, valid, psf_details = _prepare_matched_images(result)
    valid_count = int(np.count_nonzero(valid))
    total_count = int(valid.size)
    if valid_count == 0:
        raise RuntimeError("No spectrally compatible quality pixels remain for comparison.")

    difference = np.full_like(result["difference"], np.nan)
    difference[valid] = matched_image2[valid] - matched_image1[valid]
    background_offset = float(np.nanmedian(difference[valid]))
    corrected_difference = np.full_like(difference, np.nan)
    corrected_difference[valid] = difference[valid] - background_offset
    raw_significance = corrected_difference[valid] / np.sqrt(
        result["combined_variance"][valid]
    )
    # Reprojection and convolution introduce covariance not represented by the
    # per-pixel variance plane. Inflate uncertainty when the residuals show it.
    measured_sigma = robust_scatter(raw_significance)
    noise_scale = max(1.0, measured_sigma) if np.isfinite(measured_sigma) else 1.0
    significance = np.full_like(difference, np.nan)
    significance[valid] = raw_significance / noise_scale
    spectral = result["spectral_difference"][valid]
    brighter_pixels = int(np.count_nonzero(significance[valid] > sigma_threshold))
    dimmer_pixels = int(np.count_nonzero(significance[valid] < -sigma_threshold))
    valid_percentage = 100.0 * valid_count / total_count
    wavelength_median = float(np.nanmedian(spectral))
    reliability_level, reliability_label, reliability_checks = _reliability_assessment(
        valid_percentage, wavelength_median, wavelength_tolerance, noise_scale, psf_details
    )

    summary = {
        "valid_pixels": valid_count,
        "total_pixels": total_count,
        "valid_percentage": valid_percentage,
        "median_wavelength_difference_um": wavelength_median,
        "max_wavelength_difference_um": float(np.nanmax(spectral)),
        "background_offset_mjy_sr": background_offset,
        "significant_pixels_abs_gt_5": brighter_pixels + dimmer_pixels,
        "brighter_pixels_gt_5": brighter_pixels,
        "dimmer_pixels_lt_minus_5": dimmer_pixels,
        "wavelength_tolerance_um": wavelength_tolerance,
        "sigma_threshold": sigma_threshold,
        "uncertainty_scale_factor": float(noise_scale),
        "psf_matching": psf_details,
        "reliability_level": reliability_level,
        "reliability_label": reliability_label,
        "reliability_checks": reliability_checks,
    }

    print("\nScientific summary")
    print("------------------")
    for key, value in summary.items():
        print(f"{key}: {value}")

    image_limits = _limits(np.concatenate([matched_image1[valid], matched_image2[valid]]))
    difference_limits = _limits(corrected_difference[valid], symmetric=True)
    fig, axes = plt.subplots(2, 2, figsize=(11, 10))
    panels = [
        (matched_image1, "From: quality filtered + matched PSF", "gray", image_limits),
        (matched_image2, "To: WCS aligned + matched PSF", "gray", image_limits),
        (corrected_difference, "Background-corrected brightness change", "coolwarm", difference_limits),
        (significance, "Noise-calibrated significance (σ)", "coolwarm", (-5, 5)),
    ]
    for axis, (image, title, cmap, limits) in zip(axes.flat, panels):
        shown = axis.imshow(image, origin="lower", cmap=cmap, vmin=limits[0], vmax=limits[1])
        axis.set_title(title)
        axis.axis("off")
        fig.colorbar(shown, ax=axis, fraction=0.046, pad=0.04)
    fig.tight_layout()
    figure_path = output_dir / "scientific_comparison.png"
    fig.savefig(figure_path, dpi=140, bbox_inches="tight")
    plt.close(fig)

    # A presentation-first view of the same scientifically corrected residual.
    # This is a brightness-change heatmap, not a physical temperature map.
    heatmap_path = output_dir / "change_heatmap.png"
    fig, axis = plt.subplots(figsize=(8.5, 7))
    shown = axis.imshow(
        corrected_difference,
        origin="lower",
        cmap="coolwarm",
        vmin=difference_limits[0],
        vmax=difference_limits[1],
    )
    axis.set_title("Infrared brightness change · To minus From", fontsize=14, pad=12)
    axis.set_xlabel("Blue = dimmer  ·  White = little change  ·  Red = brighter")
    axis.set_xticks([])
    axis.set_yticks([])
    colorbar = fig.colorbar(shown, ax=axis, fraction=0.046, pad=0.04)
    colorbar.set_label("Brightness change (MJy/sr)")
    fig.tight_layout()
    fig.savefig(heatmap_path, dpi=140, bbox_inches="tight", facecolor="#f7f9fb")
    plt.close(fig)

    summary_path = output_dir / "scientific_summary.json"
    print("\nRunning processing/candidate_detection.py")
    try:
        candidates, candidate_score = detect_candidates(
            corrected_difference, valid, threshold=float(sigma_threshold),
            border_distance=max(1, min(8, min(valid.shape) // 10)),
        )
    except ValueError as exc:
        # A perfectly flat residual contains no candidates; it is not a failed
        # scientific comparison and should not break the web result.
        print("Candidate detection returned no usable peaks:", exc)
        candidates = []
        candidate_score = np.full_like(corrected_difference, np.nan)
    # Require both a locally strong peak and propagated, noise-calibrated
    # significance. This prevents visually sharp residuals with weak formal
    # evidence from being promoted as candidates.
    candidates = [
        candidate for candidate in candidates
        if np.isfinite(significance[int(candidate["y"]), int(candidate["x"])])
        and abs(significance[int(candidate["y"]), int(candidate["x"])]) >= sigma_threshold
    ][:50]
    print("Candidate peaks:", len(candidates))
    candidate_overview = output_dir / "candidate_overview.png"
    save_candidate_figure(corrected_difference, candidates, candidate_overview, max_display=50)

    print("Running processing/motion_candidates.py")
    motion_pairs = (
        find_motion_pairs(Table(rows=candidates), max_distance=10.0, min_distance=0.75)
        if candidates else []
    )
    print("Motion-pair hypotheses:", len(motion_pairs))
    motion_figure = None
    if motion_pairs:
        motion_path = output_dir / "motion_hypotheses.png"
        plot_motion_pairs(corrected_difference, motion_pairs, motion_path, max_pairs=20)
        motion_figure = motion_path.name

    motion_keys = set()
    for pair in motion_pairs:
        motion_keys.add((pair["negative_x"], pair["negative_y"]))
        motion_keys.add((pair["positive_x"], pair["positive_y"]))

    print("Running processing/candidate_quality.py")
    candidate_cards = []
    for index, candidate in enumerate(candidates[:12], 1):
        x, y = int(candidate["x"]), int(candidate["y"])
        quality = assess_candidate(
            matched_image1, matched_image2,
            corrected_difference, valid, candidate, radius=8,
        )
        ra, dec = first["wcs"].pixel_to_world_values(x, y)
        if (x, y) in motion_keys:
            classification = "possible_moving_source"
        elif candidate["polarity"] == "positive":
            classification = "brightened_or_transient"
        else:
            classification = "faded_or_disappeared"

        card_path = output_dir / f"candidate_{index:02d}.png"
        cutouts = [
            get_cutout(matched_image1, x, y, 8),
            get_cutout(matched_image2, x, y, 8),
            get_cutout(corrected_difference, x, y, 8),
            get_cutout(significance, x, y, 8),
        ]
        titles = ["Epoch A", "Epoch B", "Difference", "Significance"]
        fig, axes = plt.subplots(1, 4, figsize=(9, 2.5))
        for axis, cutout, title in zip(axes, cutouts, titles):
            axis.imshow(cutout, origin="lower", cmap="gray" if title.startswith("Epoch") else "coolwarm")
            axis.set_title(title, fontsize=9)
            axis.axis("off")
        fig.suptitle(f"Candidate {index} · {candidate['score']:.1f} local σ", fontsize=10)
        fig.tight_layout()
        fig.savefig(card_path, dpi=130, bbox_inches="tight")
        plt.close(fig)

        candidate_cards.append({
            "rank": index, "x": x, "y": y,
            "ra": float(ra), "dec": float(dec),
            "polarity": candidate["polarity"],
            "score": float(candidate["score"]),
            "propagated_significance": float(significance[y, x]),
            "classification": classification,
            "quality_flag": quality["quality_flag"],
            "component_pixels": quality["component_pixels"],
            "valid_fraction": quality["valid_fraction"],
            "figure": card_path.name,
        })

    summary["candidate_count"] = len(candidates)
    summary["motion_pair_count"] = len(motion_pairs)
    summary["candidate_overview"] = candidate_overview.name
    summary["motion_figure"] = motion_figure
    summary["change_heatmap"] = heatmap_path.name
    summary["candidates"] = candidate_cards
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Saved:", candidate_overview)
    if motion_figure:
        print("Saved:", output_dir / motion_figure)
    print("Saved:", figure_path)
    print("Saved:", heatmap_path)
    print("Saved:", summary_path)
    return {**summary, "figure": figure_path.name, "summary_file": summary_path.name}
