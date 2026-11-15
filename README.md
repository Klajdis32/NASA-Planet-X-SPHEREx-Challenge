# NASA Planet X — SPHEREx Sky Time-Lapse Viewer

## Live demos

### [Static GitHub Pages demo](https://klajdis32.github.io/NASA-Planet-X-SPHEREx-Challenge/)

The static demo is a reliable, server-free presentation of the final precomputed
SPHEREx results. It includes the two observation frames, time-lapse controls,
brightness-change heatmap, scientific validation, candidate review, PDF, JSON,
and GIF downloads.

> **Important:** The static version does **not** represent 100% of the application's
> functionality. It is intended only to present the final prepared data and analysis.
> It cannot search IRSA, download new FITS observations, select different dates, or
> run the Python scientific pipeline.

### [Dynamic Flask demo](https://chatty-quail-45.loca.lt/)

The dynamic version demonstrates the complete application workflow: interactive sky
selection, current IRSA observation search, From/To selection, FITS processing,
scientific analysis, downloadable reports, and local history. This temporary demo is
available only while the Flask server and public tunnel are running.

---

An accessible web application for exploring current **SPHEREx** observations and comparing how infrared brightness changes between two dates.

This project was built as a focused hackathon prototype. A user can select a position on a 360° sky map, search observations available through NASA/IPAC IRSA, choose an exact **From** and **To** observation, and generate an aligned two-epoch comparison with scientific quality checks.

> This application identifies **candidates for follow-up**, not confirmed planets, transients, or moving objects.

## What the project does

- Displays an interactive all-sky SPHEREx map with spectral channels 2–102.
- Lets the user select a sky position visually or enter RA/Dec manually.
- Searches current SPHEREx DR1 and QR3 observations through the IRSA archive.
- Supports quick date periods and custom From/To dates.
- Downloads and processes only the two observations explicitly selected by the user.
- Creates aligned observation frames, a comparison view, and an animated GIF.
- Uses the live IRSA TAP service directly for released observation searches.
- Includes an offline demonstration using two downloaded D5 FITS files.
- Presents scientific results in both plain language and an expandable technical view.
- Exports each completed comparison as a styled PDF report and machine-readable JSON data.
- Keeps a local header history with execution time, editable names, removable entries,
  and direct PDF, JSON, and GIF downloads.
- Uses an accessible, high-contrast interface with keyboard focus indicators, screen-reader status messages, large controls, and reduced-motion support.

## Scientific comparison

The pipeline performs a conservative two-epoch difference analysis:

1. **FITS validation** — requires `IMAGE`, `FLAGS`, `VARIANCE`, and `WCS-WAVE` data.
2. **Zodiacal-light subtraction** — uses `IMAGE - ZODI` when the ZODI extension is available.
3. **Quality filtering** — rejects invalid variance values and pixels affected by selected SPHEREx quality flags.
4. **Sky alignment** — reprojects the second observation onto the celestial WCS of the first.
5. **Spectral matching** — compares only pixels within the configured wavelength tolerance.
6. **PSF matching** — estimates stellar FWHM and, when enough reliable point sources exist, broadens the sharper observation to a common resolution.
7. **Edge protection** — excludes uncertain pixels near convolution boundaries and missing data.
8. **Background correction** — removes the common median brightness offset between epochs.
9. **Uncertainty calibration** — combines the two variance maps and conservatively inflates uncertainty when the measured residual noise is larger than expected.
10. **Candidate detection** — requires both a strong local residual and propagated, noise-calibrated significance.

The result includes:

- a background-corrected infrared brightness-change map;
- a noise-calibrated significance map;
- usable coverage and wavelength diagnostics;
- a comparison reliability level;
- candidate cards with coordinates, polarity, significance, and quality information;
- preliminary positive/negative motion-pair hypotheses.

The blue–white–red image is a **brightness-change heatmap, not a temperature map**:

- **Blue:** dimmer in the To observation;
- **White:** little measured change;
- **Red:** brighter in the To observation.

## Reliability levels

Each comparison is summarized as one of the following:

| Level | Meaning |
| --- | --- |
| **Strong technical quality** | Coverage, wavelength, noise, and image-resolution checks agree. Strong features are suitable for follow-up inspection. |
| **Usable with caution** | The comparison is useful, but one or more checks require additional care. |
| **Exploratory only** | The technical evidence is not strong enough for a scientific claim. |

Even a high-quality result is not a discovery confirmation. Confirmation requires repeated detections, catalogue cross-matching, photometric validation, and ideally independent observations.

## Architecture

```text
Browser UI
   │
   ├── 360° sky map and accessible controls
   ├── observation/date selection
   └── asynchronous result display
          │
          ▼
Flask web application
   │
   ├── IRSA TAP observation search
   ├── cached FITS cutout downloads
   └── per-request output directory
          │
          ▼
Scientific processing
   ├── FITS loading and quality masks
   ├── WCS and wavelength alignment
   ├── PSF/background/noise correction
   └── candidate and motion-hypothesis review
```

The Flask layer reuses the modules in `processing/`; the astronomy logic is not duplicated in the web code.

## Project structure

```text
NasaPlanetX/
├── webapp/
│   ├── app.py                  # Flask routes and archive workflow
│   ├── templates/index.html    # Main accessible interface
│   └── static/                 # CSS, JavaScript, sky assets, loading image
├── processing/
│   ├── spherex_archive.py      # IRSA search, fallback, and cutout cache
│   ├── sky_cutout.py           # Frame generation and GIF creation
│   ├── fits_loader.py          # SPHEREx FITS loading
│   ├── quality_control.py      # Flag and variance filtering
│   ├── spectral_matching.py    # Wavelength-map generation
│   ├── image_comparison.py     # WCS-aligned image comparison
│   ├── scientific_comparison.py# End-to-end scientific web analysis
│   ├── pdf_report.py           # Downloadable scientific PDF report
│   ├── psf_analysis.py         # Point-source width measurement
│   ├── psf_matching.py         # Resolution matching
│   ├── candidate_detection.py  # Local residual detection
│   ├── candidate_quality.py    # Candidate quality assessment
│   └── motion_candidates.py    # Preliminary motion-pair hypotheses
├── data/
│   ├── raw/                    # Two FITS files used by the offline demo
│   └── cache/                  # Reusable downloaded cutouts
├── spherex_observations.csv    # Local archive-search fallback
├── requirements.txt
└── README.md
```

Generated jobs are written under `data/processed/web_viewer/`. The directory is created automatically and is ignored by Git.

## Installation

Python 3.11 or newer is recommended.

```bash
git clone https://github.com/Klajdis32/NASA-Planet-X-SPHEREx-Challenge.git
cd NASA-Planet-X-SPHEREx-Challenge

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\activate
```

## Run the web viewer

```bash
source .venv/bin/activate
python -m webapp.app
```

Open [http://127.0.0.1:5050](http://127.0.0.1:5050).

To use another port:

```bash
PORT=5052 python -m webapp.app
```

If a port is already in use, choose a different value rather than starting a second server on the same port.

## Basic workflow

1. Select a position on the sky map or enter RA and Dec.
2. Select a SPHEREx detector band.
3. Choose all dates, a quick period, or a custom date interval.
4. Select **Find current data**.
5. Choose one exact From observation and one exact To observation.
6. Set the candidate threshold; `5σ` is the default conservative starting point.
7. Select **Generate time-lapse**.
8. Review the two frames, brightness-change map, reliability label, and candidate details.
9. Download the complete PDF report or the underlying scientific JSON data.

Dates are displayed in `DD/MM/YYYY` format in the interface.
The PDF includes the selected observations, coordinates, measurements, plots, candidates,
scientific limitations, and a clickable link back to the running web application.

## Offline demo

To run the application without a successful live IRSA request, use the
**Offline demo** button next to **Find current data**.
It automatically selects the two local D5 FITS files, fills in the real target centre,
and uses the saved default analysis for an immediate presentation result:

```text
RA:  133.805°
Dec: −8.770°
```

Entering `999999` in both coordinate fields remains available only for compatibility
with older local demonstrations.

## Static GitHub Pages presentation

The `docs/` directory contains a standalone static presentation that works without
Flask, IRSA, Python, or a running laptop. It includes the prepared D5 offline dataset,
two-frame viewer, timeline controls, scientific plots, candidate review, PDF/JSON/GIF
downloads, and browser-local history.

To publish it with GitHub Pages:

1. Push the `docs/` directory to the `main` branch.
2. Open the repository **Settings → Pages**.
3. Select **Deploy from a branch**.
4. Select branch **main** and folder **/docs**.
5. Save and wait for the Pages deployment to complete.

The expected project URL is:

```text
https://klajdis32.github.io/NASA-Planet-X-SPHEREx-Challenge/
```

This version intentionally does not perform live observation searches or FITS
processing. Its purpose is a fast, reliable hackathon presentation of the real
precomputed analysis.

## Command-line cutout generator

The original processing workflow remains available:

```bash
python processing/sky_cutout.py --ra 133.805 --dec -8.770 --size 128
```

Accepted ranges:

- RA: `0 ≤ RA < 360` degrees;
- Dec: `−90 ≤ Dec ≤ 90` degrees;
- cutout size: `16–1024` pixels;
- candidate threshold: `3–10σ` in the web interface.

## Archive and caching behaviour

- Live searches use NASA/IPAC IRSA TAP directly. The client does not impose a search timeout or switch to another discovery API.
- Search results are kept in memory for ten minutes.
- FITS cutouts are cached under `data/cache/spherex_cutouts/`.
- Repeating the same request can reuse the existing cached cutout.
- The local CSV catalogue is used when live archive search fails.
- An unavailable selected observation is retried and then reported clearly; the application never silently replaces it with an intermediate date.
- Full parent FITS products are not downloaded during normal online use.

Internet access is required for a new live search or a cutout that is not already cached.

## Accessibility

The interface includes:

- high-contrast text, surfaces, fields, and status messages;
- a readable base font size and comfortable line spacing;
- minimum 48-pixel interactive controls;
- visible keyboard focus outlines;
- a skip-to-content link;
- semantic labels and live status announcements for assistive technology;
- text labels in addition to colour coding;
- responsive mobile layouts;
- `prefers-reduced-motion` and `prefers-contrast` support.

These choices substantially improve accessibility but do not represent a formal WCAG certification. Manual testing with multiple screen readers and users remains an important future step.

## Scientific limitations

This is a hackathon screening pipeline, not a publication-ready discovery system. Current limitations include:

- only two selected epochs are compared at a time;
- PSF matching is skipped safely when too few suitable point sources exist;
- reprojection creates correlated noise that is handled conservatively but not modelled with a full covariance matrix;
- no automatic catalogue cross-match is performed;
- no forced multi-epoch photometry is performed;
- motion pairs are hypotheses, not orbital solutions;
- detector artifacts and residual alignment errors can resemble real variability.

The application should be used to prioritize interesting regions for deeper analysis—not as the sole evidence for an astronomical claim.

## Data acknowledgement

This project uses SPHEREx data products and services provided by NASA/IPAC IRSA. SPHEREx is a NASA Astrophysics mission. This repository is an independent hackathon project and is not an official NASA or IRSA application.

- [SPHEREx mission](https://spherex.caltech.edu/)
- [NASA/IPAC Infrared Science Archive](https://irsa.ipac.caltech.edu/)

## Future improvements

- Catalogue cross-matching for known stars, galaxies, variables, and Solar System objects.
- Three-or-more-epoch confirmation before presenting motion candidates.
- Forced photometry with uncertainty histories.
- Better spatially varying PSF models.
- Downloadable scientific reports and machine-readable candidate tables.
- Automated accessibility auditing and screen-reader testing.

