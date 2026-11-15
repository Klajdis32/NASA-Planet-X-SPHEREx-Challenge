"""Programmatic access to current SPHEREx data at NASA/IPAC IRSA."""

import csv
import hashlib
import io
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from astropy.time import Time


TAP_URL = "https://irsa.ipac.caltech.edu/TAP/sync"
SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
IRSA_BASE_URL = "https://irsa.ipac.caltech.edu/"
BANDS = tuple(f"SPHEREx-D{number}" for number in range(1, 7))
MAX_RESULTS = 5000
LOCAL_CATALOG = Path(__file__).resolve().parent.parent / "spherex_observations.csv"
CURRENT_COLLECTIONS = (
    "spherex_dr1",
    "spherex_dr1_deep",
    "spherex_qr3",
    "spherex_qr3_deep",
)


class ArchiveError(RuntimeError):
    pass


def _request_text(url, *, payload=None, timeout=None, max_attempts=1, service="IRSA"):
    """Read a small IRSA response with bounded retries for transient failures."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            request = Request(
                url,
                data=payload,
                headers={
                    "User-Agent": "NasaPlanetX/1.0 (SPHEREx hackathon viewer)",
                    "Accept": "text/csv, text/plain, */*",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8-sig")
        except HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == max_attempts:
                break
        except (TimeoutError, URLError, ConnectionError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
        if attempt < max_attempts:
            time.sleep(min(4, 2 ** attempt))
    raise ArchiveError(f"{service} search failed: {last_error}") from last_error


def _validate_position(ra, dec):
    ra = float(ra)
    dec = float(dec)
    if not 0 <= ra < 360 or not -90 <= dec <= 90:
        raise ValueError("RA/Dec are outside their valid ranges.")
    return ra, dec


def search_observations(
    ra,
    dec,
    band="SPHEREx-D5",
    timeout=None,
    max_attempts=1,
    start_mjd=None,
    end_mjd=None,
):
    """Return current IRSA spectral images covering a sky position."""
    ra, dec = _validate_position(ra, dec)
    if band not in BANDS:
        raise ValueError(f"Unsupported SPHEREx band: {band}")

    time_constraints = ""
    if start_mjd is not None:
        time_constraints += f" AND p.time_bounds_lower >= {float(start_mjd):.6f}"
    if end_mjd is not None:
        time_constraints += f" AND p.time_bounds_lower < {float(end_mjd):.6f}"

    query = f"""
        SELECT TOP {MAX_RESULTS}
            a.uri,
            p.time_bounds_lower AS mjd,
            p.energy_bandpassname AS band,
            p.provenance_version AS version,
            o.collection
        FROM spherex.artifact a
        JOIN spherex.plane p ON a.planeid = p.planeid
        JOIN spherex.observation o ON o.obsid = p.obsid
        WHERE 1 = CONTAINS(POINT('ICRS', {ra:.9f}, {dec:.9f}), p.poly)
          AND p.energy_bandpassname = '{band}'
          AND o.collection IN ({", ".join(repr(value) for value in CURRENT_COLLECTIONS)})
          {time_constraints}
        ORDER BY p.time_bounds_lower
    """
    payload = urlencode({
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "csv",
        "QUERY": query,
    }).encode("utf-8")

    text = _request_text(
        TAP_URL,
        payload=payload,
        timeout=timeout,
        max_attempts=max_attempts,
        service="IRSA TAP",
    )

    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            mjd = float(row["mjd"])
        except (KeyError, TypeError, ValueError):
            continue
        uri = row.get("uri", "")
        if not uri.startswith("ibe/data/spherex/"):
            continue
        rows.append({
            "id": hashlib.sha256(uri.encode()).hexdigest()[:16],
            "uri": uri,
            "mjd": mjd,
            "date": Time(mjd, format="mjd").isot,
            "band": row.get("band", band),
            "version": row.get("version", ""),
            "collection": row.get("collection", ""),
            "filename": Path(uri).name,
        })

    # Keep every current exposure, but remove exact duplicates returned by TAP.
    unique = {}
    for row in rows:
        unique[(row["uri"], row["mjd"])] = row
    return sorted(unique.values(), key=lambda item: item["mjd"])


def _spherex_uri(access_url):
    """Normalize an absolute or relative SIA access URL to an IRSA data URI."""
    access_url = str(access_url or "").strip()
    if not access_url:
        return ""
    parsed = urlparse(access_url)
    uri = parsed.path.lstrip("/") if parsed.scheme else access_url.lstrip("/")
    return uri if uri.startswith("ibe/data/spherex/") else ""


def _spherex_band(row):
    value = str(row.get("energy_bandpassname") or row.get("band") or "").strip()
    if value in BANDS:
        return value
    filename = Path(_spherex_uri(row.get("access_url"))).name
    match = re.search(r"_[123]D([1-6])_", filename)
    return f"SPHEREx-D{match.group(1)}" if match else ""


def search_sia_observations(
    ra,
    dec,
    band="SPHEREx-D5",
    timeout=25,
    start_mjd=None,
    end_mjd=None,
):
    """Search the official SIA2 image service when the TAP service fails."""
    ra, dec = _validate_position(ra, dec)
    if band not in BANDS:
        raise ValueError(f"Unsupported SPHEREx band: {band}")

    parameters = [("COLLECTION", collection) for collection in CURRENT_COLLECTIONS]
    parameters.extend([
        ("POS", f"CIRCLE {ra:.9f} {dec:.9f} 0.0001"),
        ("DPTYPE", "image"),
        ("RESPONSEFORMAT", "CSV"),
        ("MAXREC", str(MAX_RESULTS)),
    ])
    if start_mjd is not None or end_mjd is not None:
        low = float(start_mjd) if start_mjd is not None else "-Inf"
        high = float(end_mjd) if end_mjd is not None else "+Inf"
        parameters.append(("TIME", f"{low} {high}"))

    url = f"{SIA_URL}?{urlencode(parameters)}"
    text = _request_text(url, timeout=timeout, service="IRSA SIA2")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "access_url" not in reader.fieldnames:
        raise ArchiveError("IRSA SIA2 returned an unexpected response.")

    rows = []
    for row in reader:
        if _spherex_band(row) != band:
            continue
        try:
            mjd = float(row["t_min"])
        except (KeyError, TypeError, ValueError):
            continue
        # Apply strict local bounds as SIA TIME uses interval-overlap semantics.
        if start_mjd is not None and mjd < float(start_mjd):
            continue
        if end_mjd is not None and mjd >= float(end_mjd):
            continue
        uri = _spherex_uri(row.get("access_url"))
        if not uri:
            continue
        collection = row.get("obs_collection") or row.get("collection") or ""
        rows.append({
            "id": hashlib.sha256(uri.encode()).hexdigest()[:16],
            "uri": uri,
            "mjd": mjd,
            "date": Time(mjd, format="mjd").isot,
            "band": band,
            "version": row.get("provenance_version") or "SIA2",
            "collection": collection,
            "filename": Path(uri).name,
        })

    unique = {(row["uri"], row["mjd"]): row for row in rows}
    return sorted(unique.values(), key=lambda item: item["mjd"])


def search_local_catalog(ra, dec, band="SPHEREx-D5", start_mjd=None, end_mjd=None):
    """Search the saved SIA snapshot when the live IRSA proxy is unavailable."""
    ra, dec = _validate_position(ra, dec)
    if band not in BANDS:
        raise ValueError(f"Unsupported SPHEREx band: {band}")
    if not LOCAL_CATALOG.is_file():
        return []

    def separation_deg(ra1, dec1, ra2, dec2):
        ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
        cosine = (
            math.sin(dec1) * math.sin(dec2)
            + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
        )
        return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))

    rows = []
    with LOCAL_CATALOG.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("energy_bandpassname") != band:
                continue
            try:
                mjd = float(row["t_min"])
                center_ra = float(row["s_ra"])
                center_dec = float(row["s_dec"])
                radius = float(row.get("s_fov") or 3.48) / 2 + 0.15
            except (TypeError, ValueError, KeyError):
                continue
            if start_mjd is not None and mjd < float(start_mjd):
                continue
            if end_mjd is not None and mjd >= float(end_mjd):
                continue
            if separation_deg(ra, dec, center_ra, center_dec) > radius:
                continue
            access_url = row.get("access_url", "")
            marker = "irsa.ipac.caltech.edu/"
            uri = access_url.split(marker, 1)[-1] if marker in access_url else ""
            if not uri.startswith("ibe/data/spherex/"):
                continue
            rows.append({
                "id": hashlib.sha256(uri.encode()).hexdigest()[:16],
                "uri": uri,
                "mjd": mjd,
                "date": Time(mjd, format="mjd").isot,
                "band": band,
                "version": "local-catalog",
                "collection": row.get("obs_collection", "spherex_dr1"),
                "filename": Path(uri).name,
            })
    unique = {(row["uri"], row["mjd"]): row for row in rows}
    return sorted(unique.values(), key=lambda item: item["mjd"])


def select_time_range(observations, start_id, end_id, max_frames=12):
    by_id = {item["id"]: item for item in observations}
    if start_id not in by_id or end_id not in by_id:
        raise ValueError("The selected observations are no longer available.")
    low, high = sorted((by_id[start_id]["mjd"], by_id[end_id]["mjd"]))
    selected = [item for item in observations if low <= item["mjd"] <= high]
    max_frames = max(2, min(int(max_frames), 24))
    if len(selected) > max_frames:
        indexes = [round(i * (len(selected) - 1) / (max_frames - 1)) for i in range(max_frames)]
        selected = [selected[index] for index in indexes]
    return selected


def download_cutout(
    observation,
    ra,
    dec,
    size_pixels,
    cache_dir,
    timeout=120,
    max_attempts=4,
):
    """Download and cache a small multi-extension FITS cutout."""
    ra, dec = _validate_position(ra, dec)
    uri = observation["uri"]
    if not uri.startswith("ibe/data/spherex/") or "?" in uri or ".." in uri:
        raise ValueError("IRSA returned an invalid data URL.")

    # SPHEREx pixels are approximately 6.15 arcsec. Add a small WCS margin.
    size_deg = max(0.04, min(2.0, int(size_pixels) * 6.15 / 3600 * 1.15))
    url = IRSA_BASE_URL + uri + "?" + urlencode({
        "center": f"{ra:.8f},{dec:.8f}d",
        "size": f"{size_deg:.6f}",
    })
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode()).hexdigest()
    target = cache_dir / f"{digest}.fits"
    if target.is_file() and target.stat().st_size > 1024:
        return target

    temporary = target.with_suffix(".part")
    last_error = None
    for attempt in range(1, max_attempts + 1):
        temporary.unlink(missing_ok=True)
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "NasaPlanetX/1.0 (SPHEREx hackathon viewer)",
                    "Accept": "application/fits, application/octet-stream",
                },
            )
            with urlopen(request, timeout=timeout) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if temporary.stat().st_size <= 1024:
                raise ArchiveError("IRSA returned an empty cutout.")
            temporary.replace(target)
            return target
        except HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == max_attempts:
                break
            retry_after = exc.headers.get("Retry-After")
            try:
                delay = min(30.0, float(retry_after)) if retry_after else 2 ** attempt
            except ValueError:
                delay = 2 ** attempt
            time.sleep(delay)
        except (TimeoutError, URLError, ConnectionError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            time.sleep(2 ** attempt)
        except Exception as exc:
            last_error = exc
            break

    temporary.unlink(missing_ok=True)
    if isinstance(last_error, ArchiveError):
        raise last_error
    if isinstance(last_error, HTTPError) and last_error.code == 503:
        message = "IRSA remained temporarily unavailable after automatic retries"
    else:
        message = str(last_error)
    raise ArchiveError(
        f"Could not download {observation['filename']}: {message}. Please try again shortly."
    ) from last_error
