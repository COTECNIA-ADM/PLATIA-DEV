"""Documentos generados: propuesta en DOCX y PDF, presentación PPTX y CV a medida (Capítulo 15).

Se generan sin plantillas externas para que funcionen en cualquier instalación:
estilos sobrios y el contenido tal como lo dejó la persona (lo editado a mano
manda sobre lo que escribió la IA).
"""
import io
from xml.sax.saxutils import escape

from docx import Document as DocxDocument
from docx.shared import Pt
from pptx import Presentation
from pptx.util import Inches
from pptx.util import Pt as PptPt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..models import Proposal


def euros(value) -> str:
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def proposal_meta(proposal: Proposal) -> list[tuple[str, str]]:
    opp = proposal.opportunity
    meta = [("Oportunidad", opp.title if opp else ""),
            ("Cliente", opp.client.name if opp and opp.client else (opp.contracting_entity or "—") if opp else "—"),
            ("Tipo de propuesta", proposal.proposal_type),
            ("Versión", str(proposal.version_number))]
    if proposal.total_amount_eur is not None:
        meta.append(("Importe total", euros(proposal.total_amount_eur)))
    return meta


def sections(proposal: Proposal) -> list[tuple[str, str]]:
    return [(s.title, (s.final_content or "").strip())
            for s in sorted((s for s in proposal.sections if s.is_active), key=lambda s: s.position)]


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]


# ------------------------------------------------------------------ Propuesta
def proposal_docx(proposal: Proposal) -> bytes:
    doc = DocxDocument()
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(proposal.title, level=0)
    table = doc.add_table(rows=0, cols=2)
    for label, value in proposal_meta(proposal):
        row = table.add_row().cells
        row[0].text, row[1].text = label, value
    for title, text in sections(proposal):
        doc.add_heading(title, level=1)
        for paragraph in paragraphs(text):
            doc.add_paragraph(paragraph)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _pdf_safe(text: str) -> str:
    """Las fuentes estándar del PDF cubren Latin-1 y el euro; el resto se sustituye."""
    out = []
    for ch in text:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append("?")
    return escape("".join(out)).replace("\n", "<br/>")


def _pdf_doc(buffer, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(buffer, pagesize=A4, title=title, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                             topMargin=2 * cm, bottomMargin=2 * cm)


def _page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - 2.2 * cm, 1.2 * cm, f"{doc.page}")
    canvas.restoreState()


def _meta_table(meta: list[tuple[str, str]]) -> Table:
    styles = getSampleStyleSheet()
    rows = [[Paragraph(f"<b>{_pdf_safe(k)}</b>", styles["BodyText"]), Paragraph(_pdf_safe(v), styles["BodyText"])]
            for k, v in meta]
    table = Table(rows, colWidths=[4.5 * cm, 12 * cm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, "#cccccc")]))
    return table


def proposal_pdf(proposal: Proposal) -> bytes:
    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    story = [Paragraph(_pdf_safe(proposal.title), styles["Title"]), _meta_table(proposal_meta(proposal)),
             Spacer(1, 0.6 * cm)]
    for title, text in sections(proposal):
        story.append(Paragraph(_pdf_safe(title), styles["Heading2"]))
        for paragraph in paragraphs(text) or ["—"]:
            story.append(Paragraph(_pdf_safe(paragraph), styles["BodyText"]))
            story.append(Spacer(1, 0.2 * cm))
    _pdf_doc(buffer, proposal.title).build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return buffer.getvalue()


def default_slides(proposal: Proposal) -> list[dict]:
    """Diapositivas sin IA: el primer párrafo de cada sección, en viñetas cortas."""
    slides = []
    for title, text in sections(proposal):
        bullets = []
        for paragraph in paragraphs(text)[:4]:
            sentence = paragraph.split(". ")[0].strip()
            bullets.append(sentence[:160] + ("…" if len(sentence) > 160 else ""))
        slides.append({"title": title, "bullets": bullets or ["(sin contenido)"]})
    return slides


def proposal_pptx(proposal: Proposal, slides: list[dict]) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    cover = prs.slides.add_slide(prs.slide_layouts[0])
    cover.shapes.title.text = proposal.title[:150]
    opp = proposal.opportunity
    cover.placeholders[1].text = " · ".join(filter(None, [
        opp.client.name if opp and opp.client else (opp.contracting_entity if opp else None),
        euros(proposal.total_amount_eur) if proposal.total_amount_eur is not None else None]))
    for item in slides[:20]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = str(item.get("title") or "")[:120]
        body = slide.placeholders[1].text_frame
        body.clear()
        for i, bullet in enumerate((item.get("bullets") or [])[:6]):
            paragraph = body.paragraphs[0] if i == 0 else body.add_paragraph()
            paragraph.text = str(bullet)[:200]
            paragraph.font.size = PptPt(20)
        if item.get("notes"):
            slide.notes_slide.notes_text_frame.text = str(item["notes"])[:2000]
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


# ------------------------------------------------------------------ CV a medida
def cv_docx(cv: dict) -> bytes:
    doc = DocxDocument()
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(cv["name"], level=0)
    if cv.get("headline"):
        doc.add_paragraph(cv["headline"]).runs[0].bold = True
    if cv.get("summary"):
        doc.add_heading("Perfil", level=1)
        doc.add_paragraph(cv["summary"])
    if cv.get("skills"):
        doc.add_heading("Competencias clave", level=1)
        for skill in cv["skills"]:
            doc.add_paragraph(skill, style="List Bullet")
    if cv.get("experiences"):
        doc.add_heading("Experiencia relevante", level=1)
        for exp in cv["experiences"]:
            head = doc.add_paragraph()
            head.add_run(" · ".join(filter(None, [exp.get("role"), exp.get("company")]))).bold = True
            if exp.get("period"):
                head.add_run(f"  ({exp['period']})")
            if exp.get("description"):
                doc.add_paragraph(exp["description"])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def cv_pdf(cv: dict) -> bytes:
    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    story = [Paragraph(_pdf_safe(cv["name"]), styles["Title"])]
    if cv.get("headline"):
        story.append(Paragraph(f"<b>{_pdf_safe(cv['headline'])}</b>", styles["BodyText"]))
    if cv.get("summary"):
        story += [Paragraph("Perfil", styles["Heading2"]), Paragraph(_pdf_safe(cv["summary"]), styles["BodyText"])]
    if cv.get("skills"):
        story.append(Paragraph("Competencias clave", styles["Heading2"]))
        story.append(ListFlowable([ListItem(Paragraph(_pdf_safe(s), styles["BodyText"])) for s in cv["skills"]],
                                  bulletType="bullet"))
    if cv.get("experiences"):
        story.append(Paragraph("Experiencia relevante", styles["Heading2"]))
        for exp in cv["experiences"]:
            head = " · ".join(filter(None, [exp.get("role"), exp.get("company")]))
            period = f" ({exp['period']})" if exp.get("period") else ""
            story.append(Paragraph(f"<b>{_pdf_safe(head)}</b>{_pdf_safe(period)}", styles["BodyText"]))
            if exp.get("description"):
                story.append(Paragraph(_pdf_safe(exp["description"]), styles["BodyText"]))
            story.append(Spacer(1, 0.2 * cm))
    _pdf_doc(buffer, cv["name"]).build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return buffer.getvalue()
