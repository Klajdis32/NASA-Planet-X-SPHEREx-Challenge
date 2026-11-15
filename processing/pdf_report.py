"""Generate a polished PDF summary for one SPHEREx web comparison."""

from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


NAVY = colors.HexColor("#071522")
BLUE = colors.HexColor("#1767D2")
CYAN = colors.HexColor("#087FA8")
PALE_BLUE = colors.HexColor("#EAF6FB")
PALE_GRAY = colors.HexColor("#F2F5F7")
MID_GRAY = colors.HexColor("#526273")
RED = colors.HexColor("#B42332")
GREEN = colors.HexColor("#18794E")


def _date(value):
    text = str(value or "")[:10]
    try:
        year, month, day = text.split("-")
        return f"{day}/{month}/{year}"
    except ValueError:
        return text or "Unknown"


def _safe(value):
    return escape(str(value if value is not None else ""))


def _report_image(path, max_width, max_height):
    path = Path(path)
    if not path.is_file():
        return None
    with PILImage.open(path) as source:
        width, height = source.size
    scale = min(max_width / width, max_height / height)
    return Image(str(path), width=width * scale, height=height * scale)


def _footer(canvas, document, page_url):
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(colors.HexColor("#C9D6DF"))
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFillColor(MID_GRAY)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18 * mm, 9.5 * mm, "NASA Planet X - SPHEREx hackathon analysis")
    page_text = f"Page {document.page}"
    canvas.drawRightString(width - 18 * mm, 9.5 * mm, page_text)
    if page_url:
        display = page_url if len(page_url) <= 75 else page_url[:72] + "..."
        text_width = stringWidth(display, "Helvetica", 7.5)
        x = (width - text_width) / 2
        canvas.setFillColor(CYAN)
        canvas.drawString(x, 9.5 * mm, display)
        canvas.linkURL(page_url, (x, 8 * mm, x + text_width, 12 * mm), relative=0)
    canvas.restoreState()


def generate_pdf_report(metadata, output_dir, page_url, data_url=None):
    """Create a static PDF report from existing web-analysis outputs."""
    output_dir = Path(output_dir)
    output_path = output_dir / "spherex_analysis_report.pdf"
    scientific = metadata.get("scientific") or {}
    observations = metadata.get("observations") or []

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
        title="SPHEREx Scientific Comparison Report",
        author="NASA Planet X Hackathon Prototype",
        subject="Two-epoch SPHEREx infrared brightness comparison",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=24, leading=28, textColor=NAVY, spaceAfter=5 * mm,
    ))
    styles.add(ParagraphStyle(
        name="Subtitle", parent=styles["Normal"], fontSize=11, leading=16,
        textColor=MID_GRAY, spaceAfter=6 * mm,
    ))
    styles.add(ParagraphStyle(
        name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=15, leading=19, textColor=NAVY, spaceBefore=5 * mm,
        spaceAfter=3 * mm, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="BodyReadable", parent=styles["BodyText"], fontSize=9.5,
        leading=14, textColor=colors.HexColor("#263746"), spaceAfter=2.5 * mm,
    ))
    styles.add(ParagraphStyle(
        name="Small", parent=styles["BodyText"], fontSize=7.7,
        leading=10.5, textColor=colors.HexColor("#33495C"),
    ))
    styles.add(ParagraphStyle(
        name="Metric", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=13, leading=16, textColor=CYAN, alignment=TA_CENTER,
    ))

    story = []
    story.append(Paragraph("SPHEREx Scientific Comparison", styles["ReportTitle"]))
    story.append(Paragraph(
        "Two-epoch infrared brightness analysis with quality filtering, wavelength matching, "
        "WCS alignment, PSF validation and conservative noise calibration.",
        styles["Subtitle"],
    ))

    overview = [
        ["Sky position", f"RA {metadata.get('ra', 0):.6f} deg / Dec {metadata.get('dec', 0):.6f} deg"],
        ["Spectral band", _safe(metadata.get("band", "Unknown"))],
        ["Cutout", f"{metadata.get('size_pixels', 'Unknown')} x {metadata.get('size_pixels', 'Unknown')} pixels"],
        ["Comparison", f"{_date(observations[0].get('date')) if observations else 'Unknown'} to {_date(observations[-1].get('date')) if observations else 'Unknown'}"],
        ["Data source", _safe(metadata.get("search_source", "Unknown"))],
    ]
    overview_table = Table(overview, colWidths=[38 * mm, 132 * mm], hAlign="LEFT")
    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), NAVY),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("BACKGROUND", (1, 0), (1, -1), PALE_GRAY),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#C4D1DA")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(overview_table)

    if page_url:
        story.append(Spacer(1, 4 * mm))
        links = f'<b>Web application:</b> <link href="{_safe(page_url)}" color="#087FA8">{_safe(page_url)}</link>'
        if data_url:
            links += f'<br/><b>Machine-readable analysis:</b> <link href="{_safe(data_url)}" color="#087FA8">scientific_summary.json</link>'
        story.append(Paragraph(links, styles["BodyReadable"]))

    story.append(Paragraph("Selected observations", styles["Section"]))
    observation_rows = [["Epoch", "Date", "File", "Valid coverage"]]
    for index, observation in enumerate(observations, 1):
        observation_rows.append([
            f"{index}",
            _date(observation.get("date")),
            Paragraph(_safe(observation.get("filename", "Unknown")), styles["Small"]),
            f"{100 * float(observation.get('valid_fraction', 0)):.1f}%",
        ])
    observation_table = Table(observation_rows, colWidths=[15 * mm, 28 * mm, 105 * mm, 25 * mm], repeatRows=1)
    observation_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CYAN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.8),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#C4D1DA")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_GRAY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(observation_table)

    comparison_image = _report_image(output_dir / metadata.get("comparison", ""), 170 * mm, 72 * mm)
    if comparison_image:
        story.append(Spacer(1, 4 * mm))
        story.append(comparison_image)

    story.append(PageBreak())
    story.append(Paragraph("Scientific validation", styles["Section"]))
    reliability = scientific.get("reliability_label", "Not available")
    reliability_level = scientific.get("reliability_level", "low")
    reliability_color = GREEN if reliability_level == "high" else (colors.HexColor("#9A6700") if reliability_level == "moderate" else RED)
    reliability_box = Table([[Paragraph("Comparison reliability", styles["Small"]), Paragraph(f"<b>{_safe(reliability)}</b>", styles["BodyReadable"]) ]], colWidths=[48 * mm, 122 * mm])
    reliability_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F8FA")),
        ("BOX", (0, 0), (-1, -1), 1.2, reliability_color),
        ("TEXTCOLOR", (1, 0), (1, 0), reliability_color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(reliability_box)
    story.append(Spacer(1, 4 * mm))

    metric_rows = [[
        Paragraph(f"{float(scientific.get('valid_percentage', 0)):.1f}%", styles["Metric"]),
        Paragraph(str(scientific.get("candidate_count", 0)), styles["Metric"]),
        Paragraph(str(scientific.get("motion_pair_count", 0)), styles["Metric"]),
        Paragraph(f"{float(scientific.get('uncertainty_scale_factor', 1)):.2f}x", styles["Metric"]),
    ], [
        "usable area", "candidate features", "motion hypotheses", "noise correction",
    ]]
    metrics_table = Table(metric_rows, colWidths=[42.5 * mm] * 4)
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), .8, colors.HexColor("#AFC9D8")),
        ("INNERGRID", (0, 0), (-1, -1), .5, colors.HexColor("#C4D6E0")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 1), (-1, 1), 7.5),
        ("TEXTCOLOR", (0, 1), (-1, 1), MID_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "The heatmap shows infrared brightness change (To minus From), not physical temperature. "
        "Blue regions became dimmer, white regions changed little, and red regions became brighter.",
        styles["BodyReadable"],
    ))
    heatmap = _report_image(output_dir / scientific.get("change_heatmap", ""), 170 * mm, 120 * mm)
    if heatmap:
        story.append(heatmap)

    story.append(Paragraph("Technical measurements", styles["Section"]))
    technical = [
        ["Valid pixels", f"{scientific.get('valid_pixels', 0):,} / {scientific.get('total_pixels', 0):,}"],
        ["Median wavelength difference", f"{float(scientific.get('median_wavelength_difference_um', 0)):.6f} um"],
        ["Background offset", f"{float(scientific.get('background_offset_mjy_sr', 0)):.6f} MJy/sr"],
        ["Candidate threshold", f"{float(scientific.get('sigma_threshold', 5)):.1f} sigma"],
        ["Pixels above threshold", str(scientific.get("brighter_pixels_gt_5", 0))],
        ["Pixels below negative threshold", str(scientific.get("dimmer_pixels_lt_minus_5", 0))],
    ]
    technical_table = Table(technical, colWidths=[72 * mm, 98 * mm])
    technical_table.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [PALE_GRAY, colors.white]),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#CDD7DE")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(technical_table)

    diagnostic = _report_image(output_dir / scientific.get("figure", ""), 170 * mm, 118 * mm)
    if diagnostic:
        story.append(PageBreak())
        story.append(Paragraph("Aligned comparison and significance", styles["Section"]))
        story.append(diagnostic)

    candidates = scientific.get("candidates") or []
    story.append(Paragraph("Candidate review", styles["Section"]))
    if candidates:
        candidate_rows = [["#", "RA", "Dec", "Class", "Local", "Variance", "Quality"]]
        for candidate in candidates:
            candidate_rows.append([
                candidate.get("rank", ""),
                f"{float(candidate.get('ra', 0)):.5f}",
                f"{float(candidate.get('dec', 0)):.5f}",
                Paragraph(_safe(str(candidate.get("classification", "")).replace("_", " ")), styles["Small"]),
                f"{float(candidate.get('score', 0)):.2f}",
                f"{float(candidate.get('propagated_significance', 0)):.2f}",
                Paragraph(_safe(str(candidate.get("quality_flag", "")).replace("_", " ")), styles["Small"]),
            ])
        candidate_table = Table(candidate_rows, colWidths=[8 * mm, 23 * mm, 23 * mm, 46 * mm, 18 * mm, 20 * mm, 32 * mm], repeatRows=1)
        candidate_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_GRAY]),
            ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#C4D1DA")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(candidate_table)
    else:
        story.append(Paragraph("No candidate passed both the local and propagated significance checks.", styles["BodyReadable"]))

    psf = scientific.get("psf_matching") or {}
    story.append(Paragraph("Method and limitations", styles["Section"]))
    method_blocks = [
        "The comparison uses zodiacal-light-subtracted data, SPHEREx quality flags, positive variance, celestial WCS alignment and per-pixel wavelength compatibility.",
        f"PSF/resolution assessment: {_safe(psf.get('reason', 'Not available'))}",
        "Candidate features are screening results, not confirmed astronomical objects. Bright stars, detector artifacts, residual alignment errors and correlated noise can create similar patterns.",
        "A credible discovery requires repeat detections, catalogue cross-matching, multi-epoch photometry and independent confirmation.",
    ]
    for block in method_blocks:
        story.append(Paragraph(block, styles["BodyReadable"]))

    story.append(Spacer(1, 4 * mm))
    disclaimer = Table([[Paragraph(
        "<b>Scientific scope:</b> This PDF documents a hackathon difference-imaging analysis. "
        "It is suitable for transparent review and presentation, but it is not a peer-reviewed discovery report.",
        styles["BodyReadable"],
    )]], colWidths=[170 * mm])
    disclaimer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF4D6")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#C28B00")),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(disclaimer)

    document.build(
        story,
        onFirstPage=lambda canvas, doc: _footer(canvas, doc, page_url),
        onLaterPages=lambda canvas, doc: _footer(canvas, doc, page_url),
    )
    return output_path.name
