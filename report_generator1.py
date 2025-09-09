import datetime
import re
import argparse
import os
from reportlab.lib.pagesizes import letter
# --- NEW: Import the Image class ---
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors


def clean_and_format_text(text):
    """
    Converts Markdown-like text to valid ReportLab XML.
    """
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    text = re.sub(r'#+\s*(.*?)\n', r'<b>\1</b>\n', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = text.replace('* ', '---BULLET---')
    return text


def parse_markdown_table(md_table: str):
    lines = [l.strip() for l in md_table.strip().split("\n") if l.strip()]
    if not lines or "|" not in lines[0]:
        return None

    rows = []
    for line in lines:
        if set(line.replace("|", "").strip()) <= set("-:"):
            continue  # skip separator line
        parts = [c.strip() for c in line.strip("|").split("|")]
        rows.append(parts)
    return rows


def make_pdf_table(rows):
    if not rows:
        return None
    table = Table(rows, hAlign="LEFT")
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
    ])
    table.setStyle(style)
    return table


def create_pdf_report(ticker, company_name, quant_results, qual_results, final_report, file_path):
    """
    Generates a professional-looking PDF report from the analysis results.
    """
    doc = SimpleDocTemplate(file_path, pagesize=letter)
    styles = getSampleStyleSheet()

    # --- Custom Styles ---
    title_style = ParagraphStyle('Title', parent=styles['h1'], fontName='Helvetica-Bold', fontSize=20, alignment=TA_CENTER, textColor=colors.navy)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['h2'], fontName='Helvetica', fontSize=12, alignment=TA_CENTER, textColor=colors.black)
    heading_style = ParagraphStyle('Heading2', parent=styles['h2'], fontName='Helvetica-Bold', fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.navy)
    sub_heading_style = ParagraphStyle('SubHeading', parent=styles['h3'], fontName='Helvetica-Bold', fontSize=12, spaceBefore=10, spaceAfter=4, textColor=colors.black)
    body_style = ParagraphStyle('BodyText', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=TA_JUSTIFY, spaceAfter=6, leading=14)
    bullet_style = ParagraphStyle('Bullet', parent=body_style, firstLineIndent=0, leftIndent=20, spaceBefore=2)

    story = []

    # --- Helper function to add content to the story ---
    def add_content(text, style):
        cleaned_text = clean_and_format_text(text)
        blocks = cleaned_text.split("\n\n")  # split into chunks

        for block in blocks:
            rows = parse_markdown_table(block)
            if rows:
                tbl = make_pdf_table(rows)
                if tbl:
                    story.append(tbl)
                story.append(Spacer(1, 12))
            else:
                for line in block.split("\n"):
                    if line.strip().startswith('---BULLET---'):
                        bullet_text = line.replace('---BULLET---', '&bull; ')
                        story.append(Paragraph(bullet_text, bullet_style))
                    elif line.strip():
                        story.append(Paragraph(line, style))

    # --- Build the Story ---
    story.append(Paragraph(f"Investment Analysis Report: {company_name or ticker}", title_style))
    story.append(Paragraph(f"Generated on: {datetime.datetime.now().strftime('%d-%B-%Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 24))

    if final_report:
        story.append(Paragraph("Comprehensive Investment Summary", heading_style))
        add_content(final_report, body_style)
        story.append(HRFlowable(width="100%", thickness=1, color=colors.navy))
        story.append(Spacer(1, 12))

    # --- Quantitative Analysis ---
    if quant_results:
        story.append(Paragraph("Quantitative Analysis", heading_style))

        if isinstance(quant_results, list):
            for item in quant_results:
                item_type = item.get("type")
                content = item.get("content")

                if item_type == "text" and content:
                    add_content(content, body_style)
                    story.append(Spacer(1, 6))
                elif item_type == "chart" and content and os.path.exists(content):
                    story.append(Image(content, width=450, height=250))
                    story.append(Spacer(1, 12))
        else:
            add_content(quant_results, body_style)

        story.append(Spacer(1, 12))

    if qual_results and isinstance(qual_results, dict):
        story.append(Paragraph("Qualitative Analysis", heading_style))
        for key, value in qual_results.items():
            if value:
                section_title = key.replace('_', ' ').title()
                story.append(Paragraph(section_title, sub_heading_style))
                add_content(str(value), body_style)
        story.append(Spacer(1, 12))

    try:
        doc.build(story)
        print(f"Successfully created PDF report at: {file_path}")
        return True
    except Exception as e:
        print(f"Error creating PDF report: {e}")
        return False


# --- (The rest of the file remains the same) ---
def parse_md_report(md_content):
    # ... (no changes needed here)
    pass

if __name__ == '__main__':
    # ... (no changes needed here)
    pass
