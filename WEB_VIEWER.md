# SPHEREx Sky Time-Lapse Web Viewer

Small local Flask viewer for current SPHEREx DR1 + QR3 observations. It reuses
`processing/sky_cutout.py`; it does not duplicate the astronomy processing in
the web layer.

## Run locally

From the `NasaPlanetX` directory:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m webapp.app
```

Open <http://127.0.0.1:5050> and try:

- RA: `133.805`
- Dec: `-8.770`
- Cutout size: `128`

The landing page shows the official DR1 `Norder3/Allsky.png` overview containing
all 768 order-3 HEALPix sky tiles. It supports zoom, pan, tile selection, and
switching among all 102 spectral channels. A click selects the corresponding
HEALPix tile center as RA/Dec; the numeric fields can then refine the target.
**Find current data** then queries the live NASA/IPAC IRSA
TAP archive for every released observation covering that position in the chosen
SPHEREx detector band, including wide and deep-field collections. All available
dates are searched by default, but any From/To pair can be chosen. The
server downloads small IRSA cutouts, caches them, aligns them to one WCS, and
builds the animation. Full parent FITS files are never downloaded.
The application waits for the TAP response without imposing a client-side
search timeout and does not switch to another discovery API.

The first and last usable frames also run through the project's scientific
analysis modules: `fits_loader.py`, `quality_control.py`,
`spectral_matching.py`, and `image_comparison.py`. The web result includes
ZODI-subtracted and WCS-aligned frames, a background-corrected difference,
variance-based significance, wavelength diagnostics, and a visible terminal
log containing the pipeline output.
The user can set a 3–10 sigma candidate threshold. The result reuses
`candidate_detection.py`, `candidate_quality.py`, and `motion_candidates.py` to
show residual candidates, four-panel candidate cards, quality labels, and
preliminary positive/negative motion-pair hypotheses.

Archive search results are cached in memory for ten minutes. Matching cutouts
are downloaded with up to three workers, and the default animation uses six
recent frames. Repeating the same request reuses both search and FITS caches.
The archive query can return the complete available period or be constrained
before results are returned. Quick choices cover all data, the last day, week,
month, three months, or year; custom From/To dates remain available.

Internet access is required for the first search and first use of each cutout.
Cached cutouts live in `data/cache/spherex_cutouts/`. The archive search returns
up to 5,000 matching observations. Each animation processes only the two
explicitly selected From and To observations; intermediate dates are not used.

If an individual IRSA cutout is temporarily unavailable, it is retried once and
then skipped. The animation continues with the remaining frames as long as at
least two observations are usable.

Each request is written to its own directory under
`data/processed/web_viewer/`, so two browser requests cannot overwrite each
other. This is a local hackathon prototype; the generated request directories
can be removed manually when they are no longer needed.

## Command-line generator

The existing command still works:

```bash
python processing/sky_cutout.py --ra 133.805 --dec -8.770 --size 128
```

Valid scientific ranges are RA `[0, 360)`, Dec `[-90, 90]`, and size
`16`–`1024` pixels. Entering `999999` in both coordinate fields activates the
two-file local D5 demo at RA 133.805°, Dec −8.770°.
