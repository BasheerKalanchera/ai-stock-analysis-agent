import datetime
import re
import argparse
import os
import json
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
import io

def clean_and_format_text(text):
    """
    Converts Markdown-like text to valid ReportLab XML.
    """
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    # Convert headers to bold
    text = re.sub(r'#+\s*(.*?)\n', r'<b>\1</b>\n', text)
    # Convert bold markers
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    
    # Use regex to find all bullet variations (*, -, etc.)
    text = re.sub(r'^\s*[\*\-]\s+', '---BULLET---', text, flags=re.MULTILINE)
    return text


def parse_markdown_table(md_table: str):
    lines = [l.strip() for l in md_table.strip().split("\n") if l.strip()]
    if not lines or "|" not in lines[0]:
        return None

    rows = []
    for line in lines:
        # Skip separator lines (e.g., |---|---|)
        if set(line.replace("|", "").strip()) <= set("-:"):
            continue
        parts = [c.strip() for c in line.strip("|").split("|")]
        rows.append(parts)
    return rows


def make_pdf_table(rows, body_style, available_width):
    """
    Creates a PDF table with proportional widths and text wrapping.
    """
    if not rows:
        return None
    
    # --- Robust Row Cleaning Logic ---
    data = []
    for row in rows:
        new_row = []
        for cell in row:
            cell_text = str(cell)
            
            # 1. Clean **bold**
            cell_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', cell_text)
            
            # 2. Convert ALL bullet types to a placeholder
            cell_text = re.sub(r'^\s*[\*\-]\s+', '---BULLET---', cell_text, flags=re.MULTILINE)

            # 3. Neutralize all newlines from the AI (replace with a space)
            cell_text = cell_text.replace('\n', ' ')

            # 4. Replace the FIRST bullet with just a bullet (no line break)
            cell_text = cell_text.replace('---BULLET---', '&bull; ', 1)

            # 5. Replace all OTHER bullets with a line break + bullet
            cell_text = cell_text.replace('---BULLET---', '<br/>&bull; ')
            
            # 6. Final cleanup for parser
            cell_text = cell_text.replace('<br>', '<br/>')
            cell_text = re.sub(r'\s*<br/>\s*', '<br/>', cell_text)
            
            new_row.append(Paragraph(cell_text, body_style))
        data.append(new_row)
    # --- END FIX ---

    # --- Proportional column widths ---
    num_cols = len(rows[0])
    
    if num_cols == 3:
        # For 3-col tables (like QoQ), give more space to analysis
        col_widths = [available_width * 0.25, available_width * 0.375, available_width * 0.375]
    elif num_cols == 2:
        col_widths = [available_width * 0.30, available_width * 0.70]
    else:
        col_widths = [available_width / num_cols] * num_cols

    table = Table(data, colWidths=col_widths, hAlign="LEFT")
    
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), 
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4)
    ])
    table.setStyle(style)
    return table


def create_pdf_report(
    ticker, 
    company_name, 
    quant_results, 
    qual_results, 
    strategy_results, 
    risk_results, 
    valuation_results, 
    final_report, 
    file_path
):
    """
    Generates a professional-looking PDF report from ALL analysis results.
    Order: Executive Summary -> Valuation -> Strategy -> Quant -> Qual -> Risk
    """
    doc = SimpleDocTemplate(file_path, pagesize=letter)
    available_width = doc.width
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['h1'], fontName='Helvetica-Bold', fontSize=20, alignment=TA_CENTER, textColor=colors.navy)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['h2'], fontName='Helvetica', fontSize=12, alignment=TA_CENTER, textColor=colors.black)
    heading_style = ParagraphStyle('Heading2', parent=styles['h2'], fontName='Helvetica-Bold', fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.navy)
    sub_heading_style = ParagraphStyle('SubHeading', parent=styles['h3'], fontName='Helvetica-Bold', fontSize=12, spaceBefore=10, spaceAfter=4, textColor=colors.black)
    body_style = ParagraphStyle('BodyText', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=TA_JUSTIFY, spaceAfter=6, leading=14, allowWidows=1, allowOrphans=1, allowBreaks=1)
    bullet_style = ParagraphStyle('Bullet', parent=body_style, firstLineIndent=0, leftIndent=20, spaceBefore=2)

    story = []

    def add_content(text, style):
        """
        Nested function to process all MARKDOWN content (text, bullets, tables).
        """
        # Strip out markdown code block wrappers
        text = re.sub(r'```markdown\n', '', str(text), flags=re.IGNORECASE)
        text = text.replace('```', '')
        
        cleaned_text = clean_and_format_text(text)
        blocks = cleaned_text.split("\n\n")

        for block in blocks:
            if not block.strip():
                continue
                
            rows = parse_markdown_table(block)
            if rows:
                # Handle Markdown Tables
                tbl = make_pdf_table(rows, body_style, available_width)
                if tbl:
                    story.append(tbl)
                story.append(Spacer(1, 12))
            else:
                # Handle Prose and Bullets
                for line in block.split("\n"):
                    if not line.strip():
                        continue
                    if line.strip().startswith('---BULLET---'):
                        bullet_text = line.replace('---BULLET---', '&bull; ')
                        story.append(Paragraph(bullet_text, bullet_style))
                    elif line.strip():
                        story.append(Paragraph(line, style))

    # --- 1. Title & Summary ---
    story.append(Paragraph(f"Investment Analysis Report: {company_name or ticker}", title_style))
    story.append(Paragraph(f"Generated on: {datetime.datetime.now().strftime('%d-%B-%Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 24))

    # --- Section 1: EXECUTIVE SUMMARY (Synthesis) ---
    if final_report:
        story.append(Paragraph("1. Executive Summary & Synthesis", heading_style))
        add_content(final_report, body_style)
        story.append(HRFlowable(width="100%", thickness=1, color=colors.navy))
        story.append(Spacer(1, 12))

    # --- Section 2: VALUATION ANALYSIS (Requested Order #1) ---
    if valuation_results:
        story.append(Paragraph("2. Valuation & Governance Analysis", heading_style))
        
        val_text = ""
        if isinstance(valuation_results, dict):
            val_text = valuation_results.get('content', '')
        else:
            val_text = str(valuation_results)
            
        add_content(val_text, body_style)
        story.append(Spacer(1, 12))

    # --- Section 3: STRATEGY ANALYSIS (Requested Order #2) ---
    if strategy_results:
        story.append(Paragraph("3. Strategic Outlook & Alpha Analysis", heading_style))
        add_content(strategy_results, body_style)
        story.append(Spacer(1, 12))

    # --- Section 4: QUANTITATIVE ANALYSIS (Requested Order #3) ---
    if quant_results:
        story.append(Paragraph("4. Quantitative Financial Analysis", heading_style))
        if isinstance(quant_results, list):
            for item in quant_results:
                item_type = item.get("type")
                content = item.get("content")

                if item_type == "text" and content:
                    add_content(content, body_style)
                    story.append(Spacer(1, 6))
                elif item_type == "chart" and content:
                    try:
                        if isinstance(content, io.BytesIO):
                            content.seek(0) # Reset pointer
                            story.append(Image(content, width=450, height=250))
                            story.append(Spacer(1, 12))
                        elif isinstance(content, str) and os.path.exists(content):
                            story.append(Image(content, width=450, height=250))
                            story.append(Spacer(1, 12))
                    except Exception as e:
                        story.append(Paragraph(f"<i>[Chart could not be rendered: {str(e)}]</i>", body_style))
        else:
            add_content(quant_results, body_style)
        story.append(Spacer(1, 12))

    # --- Section 5: QUALITATIVE ANALYSIS (Requested Order #4) ---
    if qual_results and isinstance(qual_results, dict):
        story.append(Paragraph("5. Qualitative & Management Analysis", heading_style))
        
        for key, value in qual_results.items():
            if not value:
                continue

            section_title = key.replace('_', ' ').title()
            story.append(Paragraph(section_title, sub_heading_style))

            if key == "qoq_comparison":
                # --- JSON TABLE LOGIC ---
                try:
                    match = re.search(r'\[.*\]', str(value), re.DOTALL)
                    if match:
                        cleaned_value = match.group(0)
                        parsed_data = json.loads(cleaned_value)
                        if isinstance(parsed_data, list):
                            rows = []
                            rows.append(list(parsed_data[0].keys())) 
                            for item in parsed_data:
                                rows.append(list(item.values()))
                            
                            tbl = make_pdf_table(rows, body_style, available_width)
                            if tbl:
                                story.append(tbl)
                            story.append(Spacer(1, 12))
                        else:
                             add_content(str(value), body_style)
                    else:
                        add_content(str(value), body_style)
                except Exception:
                    add_content(str(value), body_style)
            else:
                add_content(str(value), body_style)
        
        story.append(Spacer(1, 12))

    # --- Section 6: RISK ANALYSIS (Requested Order #5) ---
    if risk_results:
        story.append(Paragraph("6. Risk & Credit Profile", heading_style))
        add_content(risk_results, body_style)
        story.append(Spacer(1, 12))

    # --- Build PDF ---
    try:
        doc.build(story)
        print(f"Successfully created PDF report at: {file_path}")
        return True
    except Exception as e:
        print(f"Error creating PDF report: {e}")
        return False

if __name__ == '__main__':
    pass