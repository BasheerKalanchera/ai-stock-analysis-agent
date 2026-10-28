import datetime
import re
import argparse
import os
import json
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
import io

def sanitize_for_reportlab(text):
    """
    Escapes XML special characters (&, <, >) while preserving
    ReportLab-supported markup tags: <b>, </b>, <i>, </i>, <br/>, <a ...>, </a>.
    """
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    # 1. Temporarily replace allowed tags with unique tokens
    tokens = {}
    def repl_tag(m):
        tok = f"__RLTAG_{len(tokens)}__"
        tokens[tok] = m.group(0)
        return tok

    tag_pattern = r'<\/?(?:b|i|br\s*\/|br|a(?:\s+[^>]+)?)>'
    text = re.sub(tag_pattern, repl_tag, text, flags=re.IGNORECASE)

    # 2. Escape & that is not already part of an XML entity
    text = re.sub(r'&(?!(?:amp|bull|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)', '&amp;', text)

    # 3. Escape remaining raw < and >
    text = text.replace('<', '&lt;').replace('>', '&gt;')

    # 4. Restore preserved tags
    for tok, original in tokens.items():
        if original.lower() == '<br>':
            original = '<br/>'
        text = text.replace(tok, original)

    return text

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
    return sanitize_for_reportlab(text)


def parse_markdown_table(md_table_lines):
    """
    Parses a list of table strings into a list of lists (rows).
    """
    rows = []
    for line in md_table_lines:
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
            cell_text = sanitize_for_reportlab(cell_text)
            
            new_row.append(Paragraph(cell_text, body_style))
        data.append(new_row)

    # --- Proportional column widths ---
    num_cols = len(rows[0])
    
    if num_cols == 3:
        # For 3-col tables (like QoQ), give more space to analysis
        col_widths = [available_width * 0.25, available_width * 0.375, available_width * 0.375]
    elif num_cols == 2:
        col_widths = [available_width * 0.30, available_width * 0.70]
    elif num_cols == 4:
        col_widths = [available_width * 0.20, available_width * 0.26, available_width * 0.27, available_width * 0.27]
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
    file_path,
    workflow_mode=None
):
    """
    Generates a professional-looking PDF report from analysis results.
    Includes a dynamic Table of Contents tailored to whichever mode was run.
    """
    doc = SimpleDocTemplate(file_path, pagesize=letter)
    available_width = doc.width
    styles = getSampleStyleSheet()

    # --- Styles ---
    title_style = ParagraphStyle('Title', parent=styles['h1'], fontName='Helvetica-Bold', fontSize=20, alignment=TA_CENTER, textColor=colors.navy)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['h2'], fontName='Helvetica', fontSize=12, alignment=TA_CENTER, textColor=colors.black)
    heading_style = ParagraphStyle('Heading2', parent=styles['h2'], fontName='Helvetica-Bold', fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.navy)
    toc_link_style = ParagraphStyle('TOCLink', parent=styles['Normal'], fontName='Helvetica', fontSize=11, spaceAfter=4, textColor=colors.blue)
    sub_heading_style = ParagraphStyle('SubHeading', parent=styles['h3'], fontName='Helvetica-Bold', fontSize=12, spaceBefore=10, spaceAfter=4, textColor=colors.black)
    body_style = ParagraphStyle('BodyText', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=TA_JUSTIFY, spaceAfter=6, leading=14, allowWidows=1, allowOrphans=1, allowBreaks=1)
    bullet_style = ParagraphStyle('Bullet', parent=body_style, firstLineIndent=0, leftIndent=20, spaceBefore=2)

    story = []

    def add_content(text, style):
        """
        Nested function to process markdown content. 
        Crucially, it separates Tables from Text if the LLM merges them.
        """
        # Strip code blocks
        text = re.sub(r'```markdown\n', '', str(text), flags=re.IGNORECASE)
        text = text.replace('```', '')
        
        cleaned_text = clean_and_format_text(text)
        blocks = cleaned_text.split("\n\n")

        for block in blocks:
            if not block.strip():
                continue
            
            lines = block.split('\n')
            
            # --- HYBRID PARSER: Detect Tables vs Text ---
            if "|" in lines[0]: 
                table_lines = []
                text_lines = []
                capture_mode = "TABLE"
                
                for line in lines:
                    if capture_mode == "TABLE":
                        if "|" in line:
                            table_lines.append(line)
                        else:
                            if not line.strip(): 
                                continue
                            capture_mode = "TEXT"
                            text_lines.append(line)
                    else:
                        text_lines.append(line)
                
                # 1. Render Table
                if table_lines:
                    rows = parse_markdown_table(table_lines)
                    if rows:
                        tbl = make_pdf_table(rows, body_style, available_width)
                        if tbl:
                            story.append(tbl)
                        story.append(Spacer(1, 12))
                
                # 2. Render Leftover Text (The "Analysis" part)
                for line in text_lines:
                    if line.strip().startswith('---BULLET---'):
                        bullet_text = line.replace('---BULLET---', '&bull; ')
                        story.append(Paragraph(bullet_text, bullet_style))
                    else:
                        story.append(Paragraph(line, style))

            else:
                # Normal Text Block
                for line in lines:
                    if not line.strip():
                        continue
                    if line.strip().startswith('---BULLET---'):
                        bullet_text = line.replace('---BULLET---', '&bull; ')
                        story.append(Paragraph(bullet_text, bullet_style))
                    elif line.strip():
                        story.append(Paragraph(line, style))

    # --- 0. Title Page ---
    if workflow_mode and workflow_mode != "Full Workflow (PDF Report)":
        title_text = f"{workflow_mode} Report: {company_name or ticker}"
    else:
        title_text = f"Investment Analysis Report: {company_name or ticker}"

    story.append(Paragraph(title_text, title_style))
    story.append(Paragraph(f"Generated on: {datetime.datetime.now().strftime('%d-%B-%Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.navy))
    story.append(Spacer(1, 24))

    # --- SPLIT LOGIC: SEPARATE THESIS FROM SUMMARY ---
    thesis_content = ""
    summary_content = final_report if final_report else ""

    if final_report:
        match = re.search(r'(?im)^#+\s*\d*\.?\s*Executive Summary', final_report)
        if match:
            split_index = match.start()
            thesis_content = final_report[:split_index].strip()
            summary_content = final_report[match.end():].strip()
        elif "Investment Thesis" in final_report and "Executive Summary" in final_report:
            parts = final_report.split("Executive Summary", 1)
            if len(parts) == 2:
                thesis_content = parts[0].replace("#", "").strip()
                summary_content = parts[1].strip()

    # --- 1. Dynamic Table of Contents (Clickable) ---
    active_toc_items = []
    item_num = 1
    if thesis_content:
        active_toc_items.append(("thesis", f"{item_num}. Investment Thesis"))
        item_num += 1
    if summary_content:
        exec_label = "Executive Summary & Synthesis" if workflow_mode in (None, "Full Workflow (PDF Report)") else "Executive Synthesis"
        active_toc_items.append(("exec_summary", f"{item_num}. {exec_label}"))
        item_num += 1
    if valuation_results:
        active_toc_items.append(("valuation", f"{item_num}. Valuation & Governance Analysis"))
        item_num += 1
    if strategy_results:
        active_toc_items.append(("strategy", f"{item_num}. Strategic Outlook & Alpha Analysis"))
        item_num += 1
    if quant_results:
        active_toc_items.append(("quant", f"{item_num}. Quantitative Financial Analysis"))
        item_num += 1
    if qual_results and isinstance(qual_results, dict) and any(qual_results.values()):
        label = "Qualitative & Management Analysis"
        if workflow_mode == "QoQ Concall Analysis":
            label = "QoQ Concall Analysis & Transcripts"
        elif workflow_mode == "Latest Concall Analysis":
            label = "Latest Concall Insights"
        elif workflow_mode == "SEBI Violations Check (MVP)":
            label = "SEBI Regulatory Status"
        elif workflow_mode == "Scuttlebutt Research":
            label = "Scuttlebutt Intel & Investigation"
        active_toc_items.append(("qual", f"{item_num}. {label}"))
        item_num += 1
    if risk_results:
        active_toc_items.append(("risk", f"{item_num}. Risk & Credit Profile"))
        item_num += 1

    toc_dict = dict(active_toc_items)

    if active_toc_items:
        story.append(Paragraph("<b>Table of Contents</b>", heading_style))
        story.append(Spacer(1, 12))

        for anchor, title in active_toc_items:
            link_text = f'<a href="#{anchor}" color="blue">{title}</a>'
            story.append(Paragraph(link_text, toc_link_style))
        
        # Only pagebreak if we have 3 or more sections or in Full mode
        if len(active_toc_items) >= 3 or workflow_mode in (None, "Full Workflow (PDF Report)"):
            story.append(PageBreak())
        else:
            story.append(Spacer(1, 16))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            story.append(Spacer(1, 16))

    # --- Section: INVESTMENT THESIS ---
    if thesis_content and "thesis" in toc_dict:
        header_text = f'<a name="thesis"/>{toc_dict["thesis"]}'
        story.append(Paragraph(header_text, heading_style))
        add_content(thesis_content, body_style)
        story.append(HRFlowable(width="100%", thickness=1, color=colors.navy))
        story.append(Spacer(1, 12))

    # --- Section: EXECUTIVE SUMMARY (Synthesis) ---
    if summary_content and "exec_summary" in toc_dict:
        header_text = f'<a name="exec_summary"/>{toc_dict["exec_summary"]}'
        story.append(Paragraph(header_text, heading_style))
        add_content(summary_content, body_style)
        story.append(HRFlowable(width="100%", thickness=1, color=colors.navy))
        story.append(Spacer(1, 12))

    # --- Section: VALUATION ANALYSIS ---
    if valuation_results and "valuation" in toc_dict:
        header_text = f'<a name="valuation"/>{toc_dict["valuation"]}'
        story.append(Paragraph(header_text, heading_style))
        
        val_text = ""
        peer_tbl = None
        if isinstance(valuation_results, dict):
            val_text = valuation_results.get('content', '')
            peer_tbl = valuation_results.get('peer_comparison_table')
        else:
            val_text = str(valuation_results)
            
        add_content(val_text, body_style)
        
        if peer_tbl is not None:
            try:
                if isinstance(peer_tbl, pd.DataFrame) and not peer_tbl.empty:
                    p_rows = [list(peer_tbl.columns)] + peer_tbl.astype(str).values.tolist()
                    tbl = make_pdf_table(p_rows, body_style, available_width)
                    if tbl:
                        story.append(Spacer(1, 6))
                        story.append(Paragraph("<b>Peer Comparison Matrix:</b>", sub_heading_style))
                        story.append(tbl)
            except Exception:
                pass
        story.append(Spacer(1, 12))

    # --- Section: STRATEGY ANALYSIS ---
    if strategy_results and "strategy" in toc_dict:
        header_text = f'<a name="strategy"/>{toc_dict["strategy"]}'
        story.append(Paragraph(header_text, heading_style))
        add_content(strategy_results, body_style)
        story.append(Spacer(1, 12))

    # --- Section: QUANTITATIVE ANALYSIS ---
    if quant_results and "quant" in toc_dict:
        header_text = f'<a name="quant"/>{toc_dict["quant"]}'
        story.append(Paragraph(header_text, heading_style))
        if isinstance(quant_results, list):
            for item in quant_results:
                item_type = item.get("type")
                content = item.get("content")

                if item_type == "text" and content:
                    add_content(content, body_style)
                    story.append(Spacer(1, 6))
                elif item_type == "table" and content is not None:
                    try:
                        if isinstance(content, pd.DataFrame) and not content.empty:
                            t_rows = [list(content.columns)] + content.astype(str).values.tolist()
                            tbl = make_pdf_table(t_rows, body_style, available_width)
                            if tbl:
                                story.append(tbl)
                                story.append(Spacer(1, 6))
                    except Exception:
                        pass
                elif item_type == "chart" and content:
                    try:
                        if isinstance(content, io.BytesIO):
                            content.seek(0) 
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

    # --- Section: QUALITATIVE ANALYSIS ---
    if qual_results and isinstance(qual_results, dict) and "qual" in toc_dict:
        header_text = f'<a name="qual"/>{toc_dict["qual"]}'
        story.append(Paragraph(header_text, heading_style))
        
        for key, value in qual_results.items():
            if not value:
                continue

            section_title = key.replace('_', ' ').title()
            story.append(Paragraph(section_title, sub_heading_style))

            if key == "qoq_comparison":
                try:
                    match = re.search(r'\[.*\]', str(value), re.DOTALL)
                    if match:
                        cleaned_value = match.group(0)
                        parsed_data = json.loads(cleaned_value)
                        if isinstance(parsed_data, list) and len(parsed_data) > 0:
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

    # --- Section: RISK ANALYSIS ---
    if risk_results and "risk" in toc_dict:
        header_text = f'<a name="risk"/>{toc_dict["risk"]}'
        story.append(Paragraph(header_text, heading_style))
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