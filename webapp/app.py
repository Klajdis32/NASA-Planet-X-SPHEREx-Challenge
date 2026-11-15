from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
import json
import os
import shutil
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from astropy.time import Time
from astropy.io import fits
from astropy import units as u
from astropy_healpix import HEALPix
from uuid import uuid4

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)


BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSING_DIR = BASE_DIR / "processing"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(PROCESSING_DIR) not in sys.path:
    sys.path.insert(0, str(PROCESSING_DIR))

from processing.sky_cutout import (  # noqa: E402
    create_sky_preview,
    generate_cutouts,
    preview_pixel_to_sky,
)
from processing.pdf_report import generate_pdf_report  # noqa: E402
from processing.spherex_archive import (  # noqa: E402
    ArchiveError,
    BANDS,
    download_cutout,
    search_observations,
)
from scientific_comparison import run_scientific_comparison  # noqa: E402


OUTPUT_ROOT = BASE_DIR / "data" / "processed" / "web_viewer"
ARCHIVE_CACHE = BASE_DIR / "data" / "cache" / "spherex_cutouts"
SEARCH_CACHE_TTL = 10 * 60
_search_cache = {}
_search_cache_lock = threading.Lock()
_history_lock = threading.Lock()
ALL_SKY_ORDER = 3
ALL_SKY_COLUMNS = 27
ALL_SKY_ROWS = 29
ALL_SKY_TILE_COUNT = 12 * (4 ** ALL_SKY_ORDER)
_all_sky_healpix = HEALPix(nside=2 ** ALL_SKY_ORDER, order="nested", frame="icrs")
ALL_SKY_HIPS_ROOT = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube"
DEMO_SENTINEL = 999999.0
DEMO_RA = 133.805
DEMO_DEC = -8.770
DEMO_JOB_ID = "d" * 32
DEMO_CACHE_VERSION = "20261115-v1"
DEMO_SIZE = 128
DEMO_SIGMA_THRESHOLD = 5.0
DEMO_FILES = (
    BASE_DIR / "data" / "raw" / "level2_2025W19_1B_0181_3D5_spx_l2b-v27-2026-197.fits",
    BASE_DIR / "data" / "raw" / "level2_2026W20_1A_1166_1D5_spx_l2b-v27-2026-246.fits",
)


def read_history(output_root):
    history_file = Path(output_root) / "history.json"
    if not history_file.is_file():
        return []
    try:
        entries = json.loads(history_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return entries if isinstance(entries, list) else []


def write_history(output_root, entries):
    history_file = Path(output_root) / "history.json"
    temporary = history_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(entries[:100], indent=2), encoding="utf-8")
    temporary.replace(history_file)


def record_history(output_root, job_id, metadata):
    """Keep a local index of completed comparisons and their exports."""
    observations = metadata.get("observations") or []
    scientific = metadata.get("scientific") or {}
    entry = {
        "id": uuid4().hex,
        "job_id": job_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ra": metadata.get("ra"),
        "dec": metadata.get("dec"),
        "band": metadata.get("band"),
        "from_observation": observations[0].get("date") if observations else None,
        "to_observation": observations[-1].get("date") if observations else None,
        "pdf": metadata.get("pdf_report"),
        "json": scientific.get("summary_file"),
        "gif": metadata.get("gif"),
        "offline_demo": bool(metadata.get("demo_mode")),
    }
    with _history_lock:
        entries = read_history(output_root)
        entries.insert(0, entry)
        write_history(output_root, entries)


def load_precomputed_demo(output_root, size, sigma_threshold):
    """Return the stable presentation result when its settings match."""
    if size != DEMO_SIZE or sigma_threshold != DEMO_SIGMA_THRESHOLD:
        return None
    cache_file = Path(output_root) / DEMO_JOB_ID / "demo_result.json"
    if not cache_file.is_file():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("cache_version") != DEMO_CACHE_VERSION:
        return None
    return payload.get("metadata")


def store_precomputed_demo(output_root, source_dir, metadata):
    """Save one reusable copy of the default offline presentation."""
    target = Path(output_root) / DEMO_JOB_ID
    target.mkdir(parents=True, exist_ok=True)
    for source in Path(source_dir).iterdir():
        if source.is_file():
            shutil.copy2(source, target / source.name)
    payload = {"cache_version": DEMO_CACHE_VERSION, "metadata": metadata}
    (target / "demo_result.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def local_demo_observations():
    observations = []
    for index, path in enumerate(DEMO_FILES):
        if not path.is_file():
            continue
        with fits.open(path, memmap=True) as hdul:
            header = hdul["IMAGE"].header
            date = header.get("DATE-OBS")
        if not date:
            continue
        mjd = float(Time(date).mjd)
        observations.append({
            "id": f"local-demo-{index + 1}",
            "uri": "",
            "local_path": str(path),
            "mjd": mjd,
            "date": Time(mjd, format="mjd").isot,
            "band": "SPHEREx-D5",
            "version": "local-file",
            "collection": "local_demo",
            "filename": path.name,
        })
    return sorted(observations, key=lambda item: item["mjd"])


def cached_observation_search(ra, dec, band, from_date=None, to_date=None):
    if float(ra) == DEMO_SENTINEL and float(dec) == DEMO_SENTINEL:
        return local_demo_observations(), False, "local demo files"
    start_mjd = float(Time(from_date).mjd) if from_date else None
    # Include the complete To date by querying up to the following midnight.
    end_mjd = float(Time(to_date).mjd) + 1 if to_date else None
    key = (
        round(float(ra), 6), round(float(dec), 6), str(band),
        from_date or "", to_date or "",
    )
    now = time.monotonic()
    with _search_cache_lock:
        cached = _search_cache.get(key)
        if cached and now - cached[0] < SEARCH_CACHE_TTL:
            return cached[1], True, cached[2]
    source = "live IRSA TAP"
    observations = search_observations(
        ra, dec, band, start_mjd=start_mjd, end_mjd=end_mjd
    )
    with _search_cache_lock:
        _search_cache[key] = (now, observations, source)
    return observations, False, source


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        OUTPUT_ROOT=OUTPUT_ROOT,
        ARCHIVE_CACHE=ARCHIVE_CACHE,
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    @app.template_filter("greek_date")
    def greek_date(value):
        try:
            year, month, day = str(value)[:10].split("-")
            return f"{day}/{month}/{year}"
        except (TypeError, ValueError):
            return str(value)

    @app.after_request
    def disable_browser_cache(response):
        if response.mimetype in {"text/html", "text/css", "application/javascript"}:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            values={"ra": "133.805", "dec": "-8.770", "size": "128"},
            bands=BANDS,
        )

    @app.get("/latest-sky-preview.png")
    def latest_sky_preview():
        preview_path = Path(app.config["OUTPUT_ROOT"]) / "latest_sky_preview.png"
        if not preview_path.is_file():
            create_sky_preview(preview_path)
        return send_file(preview_path, mimetype="image/png", max_age=0)

    @app.get("/api/preview-pixel-to-sky")
    def preview_pixel_to_sky_api():
        try:
            ra, dec = preview_pixel_to_sky(
                request.args["x"],
                request.args["y"],
                request.args["width"],
                request.args["height"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=str(exc) or "Invalid preview coordinates."), 400
        except (FileNotFoundError, RuntimeError) as exc:
            return jsonify(error=str(exc)), 422
        return jsonify(ra=ra, dec=dec)

    @app.get("/api/all-sky-tile")
    def all_sky_tile_api():
        """Map a click in the official HiPS Allsky atlas to a HEALPix tile."""
        try:
            x = float(request.args["x"])
            y = float(request.args["y"])
            width = float(request.args["width"])
            height = float(request.args["height"])
            if width <= 0 or height <= 0 or not (0 <= x < width and 0 <= y < height):
                raise ValueError("The selected point is outside the all-sky atlas.")
            column = min(ALL_SKY_COLUMNS - 1, int(x / width * ALL_SKY_COLUMNS))
            row = min(ALL_SKY_ROWS - 1, int(y / height * ALL_SKY_ROWS))
            tile = row * ALL_SKY_COLUMNS + column
            if tile >= ALL_SKY_TILE_COUNT:
                raise ValueError("Select a tile containing SPHEREx sky data.")
            lon, lat = _all_sky_healpix.healpix_to_lonlat(tile)
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=str(exc) or "Invalid all-sky selection."), 400
        return jsonify(
            tile=tile,
            order=ALL_SKY_ORDER,
            ra=float(lon.to_value(u.deg) % 360),
            dec=float(lat.to_value(u.deg)),
        )

    @app.get("/all-sky/channel/<int:channel>.png")
    def all_sky_channel(channel):
        """Cache and serve one lightweight overview frame of the 102-plane cube."""
        if not 2 <= channel <= 102:
            abort(404)
        cache_dir = Path(app.config["ARCHIVE_CACHE"]) / "all_sky_channels"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"channel-{channel}.png"
        if not target.is_file() or target.stat().st_size < 1024:
            url = f"{ALL_SKY_HIPS_ROOT}/Norder3/Allsky_{channel - 1}.png"
            temporary = target.with_suffix(".part")
            try:
                req = Request(url, headers={"User-Agent": "NasaPlanetX/1.0"})
                with urlopen(req, timeout=45) as response, temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                if temporary.stat().st_size < 1024:
                    raise RuntimeError("IRSA returned an empty all-sky frame.")
                temporary.replace(target)
            except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
                temporary.unlink(missing_ok=True)
                app.logger.warning("All-sky channel %s unavailable: %s", channel, exc)
                return jsonify(error=f"Channel {channel} is temporarily unavailable."), 502
        return send_file(target, mimetype="image/png", max_age=86400)

    @app.get("/api/observations")
    def observations_api():
        try:
            ra = float(request.args["ra"])
            dec = float(request.args["dec"])
            band = request.args.get("band", "SPHEREx-D5")
            demo_mode = request.args.get("demo") == "1"
            from_date = request.args.get("from_date", "")
            to_date = request.args.get("to_date", "")
            if bool(from_date) != bool(to_date):
                raise ValueError("Choose both From and To, or leave both empty for all data.")
            if from_date and from_date > to_date:
                raise ValueError("Choose a valid From/To date period.")
            if demo_mode:
                observations, cache_hit, source = (
                    local_demo_observations(), True, "local demo files"
                )
            else:
                observations, cache_hit, source = cached_observation_search(
                    ra, dec, band, from_date, to_date
                )
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=str(exc) or "Invalid archive search."), 400
        except ArchiveError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(
            observations=[
                {key: value for key, value in item.items() if key != "local_path"}
                for item in observations
            ],
            count=len(observations),
            truncated=len(observations) == 5000,
            cache_hit=cache_hit,
            source=source,
        )

    @app.get("/api/history")
    def history_api():
        entries = []
        for stored in read_history(app.config["OUTPUT_ROOT"]):
            job_id = stored.get("job_id", "")
            if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
                continue
            entry = dict(stored)
            for key in ("pdf", "json", "gif"):
                filename = entry.get(key)
                entry[f"{key}_url"] = (
                    url_for("output_file", job_id=job_id, filename=filename)
                    if filename else None
                )
            entries.append(entry)
        return jsonify(entries=entries, count=len(entries))

    @app.route("/api/history/<entry_id>", methods=["PATCH", "DELETE"])
    def history_entry_api(entry_id):
        if len(entry_id) != 32 or any(c not in "0123456789abcdef" for c in entry_id):
            abort(404)
        with _history_lock:
            entries = read_history(app.config["OUTPUT_ROOT"])
            matching = next(
                (entry for entry in entries if entry.get("id") == entry_id), None
            )
            if matching is None:
                abort(404)
            if request.method == "DELETE":
                write_history(
                    app.config["OUTPUT_ROOT"],
                    [entry for entry in entries if entry.get("id") != entry_id],
                )
                return jsonify(deleted=True, id=entry_id)
            payload = request.get_json(silent=True) or {}
            name = str(payload.get("name", "")).strip()
            if not name:
                return jsonify(error="Enter a name for this analysis."), 400
            if len(name) > 80:
                return jsonify(error="The name must be 80 characters or fewer."), 400
            matching["name"] = name
            write_history(app.config["OUTPUT_ROOT"], entries)
        return jsonify(updated=True, id=entry_id, name=name)

    @app.post("/generate")
    def generate():
        values = {
            "ra": request.form.get("ra", "").strip(),
            "dec": request.form.get("dec", "").strip(),
            "size": request.form.get("size", "").strip(),
            "band": request.form.get("band", "SPHEREx-D5").strip(),
            "start_id": request.form.get("start_id", "").strip(),
            "end_id": request.form.get("end_id", "").strip(),
            "max_frames": request.form.get("max_frames", "12").strip(),
            "from_date": request.form.get("from_date", "").strip(),
            "to_date": request.form.get("to_date", "").strip(),
            "sigma_threshold": request.form.get("sigma_threshold", "5").strip(),
            "demo_mode": request.form.get("demo_mode", "").strip(),
        }

        try:
            ra = float(values["ra"])
            dec = float(values["dec"])
            demo_mode = (
                values["demo_mode"] == "1"
                or (ra == DEMO_SENTINEL and dec == DEMO_SENTINEL)
            )
            effective_ra = DEMO_RA if demo_mode else ra
            effective_dec = DEMO_DEC if demo_mode else dec
            if demo_mode:
                values["band"] = "SPHEREx-D5"
            size = int(values["size"])
            sigma_threshold = float(values["sigma_threshold"])
            if not 3 <= sigma_threshold <= 10:
                raise ValueError("Sigma threshold must be between 3 and 10.")
        except (TypeError, ValueError):
            return render_template(
                "index.html",
                values=values,
                bands=BANDS,
                error="Enter numeric RA/Dec values and a whole-number cutout size.",
            ), 400

        try:
            if demo_mode:
                available, search_cache_hit, search_source = (
                    local_demo_observations(), True, "local demo files"
                )
            else:
                available, search_cache_hit, search_source = cached_observation_search(
                    ra, dec, values["band"], values["from_date"], values["to_date"]
                )
            if not available:
                raise RuntimeError("No current IRSA observations cover this position and band.")
            start_id = values["start_id"] or available[0]["id"]
            end_id = values["end_id"] or available[-1]["id"]
            by_id = {item["id"]: item for item in available}
            if start_id not in by_id or end_id not in by_id:
                raise ValueError("The selected observations are no longer available.")
            if start_id == end_id:
                raise ValueError("Choose two different From and To observations.")
            selected = sorted(
                [by_id[start_id], by_id[end_id]],
                key=lambda item: item["mjd"],
            )
            if demo_mode:
                cached_demo = load_precomputed_demo(
                    app.config["OUTPUT_ROOT"], size, sigma_threshold
                )
                if cached_demo:
                    cached_demo["demo_cache_hit"] = True
                    try:
                        record_history(
                            app.config["OUTPUT_ROOT"], DEMO_JOB_ID, cached_demo
                        )
                    except (OSError, TypeError, ValueError):
                        app.logger.exception("Analysis history could not be updated")
                    return render_template(
                        "index.html",
                        values=values,
                        bands=BANDS,
                        result=cached_demo,
                        job_id=DEMO_JOB_ID,
                    )
            job_id = uuid4().hex
            job_dir = Path(app.config["OUTPUT_ROOT"]) / job_id
            def fetch_cutout(observation):
                try:
                    if observation.get("local_path"):
                        return Path(observation["local_path"])
                    return download_cutout(
                        observation,
                        effective_ra,
                        effective_dec,
                        size,
                        app.config["ARCHIVE_CACHE"],
                        timeout=60,
                        max_attempts=2,
                    )
                except ArchiveError as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=min(3, len(selected))) as executor:
                download_results = list(executor.map(fetch_cutout, selected))

            cutout_files = []
            usable_observations = []
            skipped_observations = []
            for observation, download_result in zip(selected, download_results):
                if isinstance(download_result, Exception):
                    app.logger.warning("Skipping unavailable cutout: %s", download_result)
                    skipped_observations.append({
                        "date": observation["date"],
                        "filename": observation["filename"],
                        "reason": str(download_result),
                    })
                    continue
                cutout_files.append(download_result)
                usable_observations.append(observation)

            if len(cutout_files) < 2:
                raise RuntimeError(
                    "One of the two specifically selected observations could not be "
                    "loaded. No intermediate or alternative observation was used."
                )
            paired = sorted(
                zip(usable_observations, cutout_files),
                key=lambda pair: pair[0]["mjd"],
            )
            usable_observations = [pair[0] for pair in paired]
            cutout_files = [pair[1] for pair in paired]
            metadata = generate_cutouts(
                effective_ra,
                effective_dec,
                size,
                job_dir,
                files=cutout_files,
                archive_metadata=usable_observations,
            )
            metadata["available_count"] = len(available)
            metadata["selected_count"] = len(usable_observations)
            metadata["requested_count"] = len(selected)
            metadata["skipped_count"] = len(skipped_observations)
            metadata["skipped_observations"] = skipped_observations
            metadata["band"] = values["band"]
            metadata["search_cache_hit"] = search_cache_hit
            metadata["search_source"] = search_source
            metadata["demo_mode"] = demo_mode
            terminal_buffer = StringIO()
            with redirect_stdout(terminal_buffer):
                scientific = run_scientific_comparison(
                    cutout_files[0],
                    cutout_files[-1],
                    job_dir,
                    sigma_threshold=sigma_threshold,
                )
            metadata["scientific"] = scientific
            metadata["terminal_output"] = terminal_buffer.getvalue()
            data_url = url_for(
                "output_file",
                job_id=job_id,
                filename=scientific["summary_file"],
                _external=True,
            )
            try:
                metadata["pdf_report"] = generate_pdf_report(
                    metadata,
                    job_dir,
                    page_url=request.url_root,
                    data_url=data_url,
                )
            except Exception:
                app.logger.exception("PDF report generation failed")
                metadata["pdf_report"] = None
            metadata["demo_cache_hit"] = False
            if (
                demo_mode
                and size == DEMO_SIZE
                and sigma_threshold == DEMO_SIGMA_THRESHOLD
            ):
                try:
                    store_precomputed_demo(
                        app.config["OUTPUT_ROOT"], job_dir, metadata
                    )
                except (OSError, TypeError, ValueError):
                    app.logger.exception("Offline demo cache could not be saved")
            try:
                record_history(app.config["OUTPUT_ROOT"], job_id, metadata)
            except (OSError, TypeError, ValueError):
                app.logger.exception("Analysis history could not be updated")
        except ValueError as exc:
            return render_template(
                "index.html", values=values, bands=BANDS, error=str(exc)
            ), 400
        except (ArchiveError, FileNotFoundError, RuntimeError) as exc:
            app.logger.warning("Cutout generation failed: %s", exc)
            return render_template(
                "index.html", values=values, bands=BANDS, error=str(exc)
            ), 422
        except Exception:
            app.logger.exception("Unexpected cutout generation error")
            return render_template(
                "index.html",
                values=values,
                bands=BANDS,
                error="The cutout could not be generated. Check the server log.",
            ), 500

        return render_template(
            "index.html", values=values, bands=BANDS, result=metadata, job_id=job_id
        )

    @app.get("/outputs/<job_id>/<path:filename>")
    def output_file(job_id, filename):
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            abort(404)
        return send_from_directory(
            Path(app.config["OUTPUT_ROOT"]) / job_id, filename
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG") == "1",
        use_reloader=False,
        threaded=True,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5050")),
    )
