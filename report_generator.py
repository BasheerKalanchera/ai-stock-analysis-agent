import datetime
import re
import argparse
import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.colors import navy, black

def clean_and_format_text(text):
    """
    Converts Markdown-like text to valid ReportLab XML.
    """
    if not text:
        return ""
    
    # This check prevents the function from crashing if it unexpectedly receives non-string data.
    if not isinstance(text, str):
        text = str(text)

    text = re.sub(r'#+\s*(.*?)\n', r'<b>\1</b>\n', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    # Replaces markdown-style bullets with a temporary marker for processing.
    text = text.replace('* ', '---BULLET---')
    
    return text

def create_pdf_report(ticker, company_name, quant_results, qual_results, final_report, file_path):
    """
    Generates a professional-looking PDF report from the analysis results.
    """
    doc = SimpleDocTemplate(file_path, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # --- Custom Styles ---
    title_style = ParagraphStyle('Title', parent=styles['h1'], fontName='Helvetica-Bold', fontSize=20, alignment=TA_CENTER, textColor=navy)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['h2'], fontName='Helvetica', fontSize=12, alignment=TA_CENTER, textColor=black)
    heading_style = ParagraphStyle('Heading2', parent=styles['h2'], fontName='Helvetica-Bold', fontSize=14, spaceBefore=12, spaceAfter=6, textColor=navy)
    # New style for sub-sections within the qualitative analysis.
    sub_heading_style = ParagraphStyle('SubHeading', parent=styles['h3'], fontName='Helvetica-Bold', fontSize=12, spaceBefore=10, spaceAfter=4, textColor=black)
    body_style = ParagraphStyle('BodyText', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=TA_JUSTIFY, spaceAfter=6, leading=14)
    bullet_style = ParagraphStyle('Bullet', parent=body_style, firstLineIndent=0, leftIndent=20, spaceBefore=2)
    
    story = []

    # --- Helper function to add content to the story ---
    def add_content(text, style):
        cleaned_text = clean_and_format_text(text)
        lines = cleaned_text.split('\n')
        for line in lines:
            if line.strip().startswith('---BULLET---'):
                # Creates a bulleted list item.
                bullet_text = line.replace('---BULLET---', '&bull; ')
                story.append(Paragraph(bullet_text, bullet_style))
            elif line.strip():
                # Adds a regular paragraph, replacing newlines with HTML line breaks.
                story.append(Paragraph(line.replace('\n', '<br/>'), style))

    # --- Build the Story ---
    story.append(Paragraph(f"Investment Analysis Report: {company_name or ticker}", title_style))
    story.append(Paragraph(f"Generated on: {datetime.datetime.now().strftime('%d-%B-%Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 24))

    if final_report:
        story.append(Paragraph("Comprehensive Investment Summary", heading_style))
        add_content(final_report, body_style)
        story.append(HRFlowable(width="100%", thickness=1, color=navy))
        story.append(Spacer(1, 12))

    if quant_results:
        story.append(Paragraph("Quantitative Analysis", heading_style))
        add_content(quant_results, body_style)
        story.append(Spacer(1, 12))

    # --- CORRECTED QUALITATIVE ANALYSIS BLOCK ---
    # This block now correctly handles a dictionary.
    if qual_results and isinstance(qual_results, dict):
        story.append(Paragraph("Qualitative Analysis", heading_style))
        # Loop through each section in the qualitative results dictionary.
        for key, value in qual_results.items():
            if value: # Only add the section if it has content.
                # Format the title (e.g., 'positives_and_concerns' -> 'Positives And Concerns').
                section_title = key.replace('_', ' ').title()
                story.append(Paragraph(section_title, sub_heading_style))
                add_content(str(value), body_style) # Convert value to string to be safe.
        story.append(Spacer(1, 12))
        
    try:
        doc.build(story)
        print(f"Successfully created PDF report at: {file_path}")
        return True
    except Exception as e:
        print(f"Error creating PDF report: {e}")
        return False

def parse_md_report(md_content):
    """
    Parses the content of a markdown log file to extract each agent's analysis.
    """
    parsed_data = {'quant_results': None, 'qual_results': None, 'final_report': None, 'company_name': None}
    
    name_match = re.search(r"AGENT 1: DOWNLOAD SUMMARY for (.*?)\n", md_content)
    if name_match:
        parsed_data['company_name'] = name_match.group(1).strip()

    sections = re.split(r'## AGENT \d+:', md_content)
    
    for section in sections:
        if "QUANTITATIVE ANALYSIS" in section:
            content = section.replace("QUANTITATIVE ANALYSIS", "").strip()
            parsed_data['quant_results'] = content.strip()
        elif "QUALITATIVE ANALYSIS" in section:
            content = section.replace("QUALITATIVE ANALYSIS", "").strip()
            parsed_data['qual_results'] = content.strip()
        elif "FINAL SYNTHESIS REPORT" in section:
            content = section.replace("FINAL SYNTHESIS REPORT", "").strip()
            parsed_data['final_report'] = content.strip()

    return parsed_data

# This block allows the script to be run directly from the command line
# to generate a PDF from an existing markdown log file.
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate a PDF analysis report from a single Markdown log file.")
    parser.add_argument("md_file_path", type=str, help="The file path to the Markdown log file.")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.md_file_path):
        print(f"Error: The file '{args.md_file_path}' was not found.")
    else:
        with open(args.md_file_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
            
        analysis_data = parse_md_report(markdown_content)
        
        REPORTS_DIRECTORY = "reports"
        if not os.path.exists(REPORTS_DIRECTORY):
            os.makedirs(REPORTS_DIRECTORY)
            
        base_filename = os.path.basename(args.md_file_path)
        ticker = base_filename.split('_')[0]
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_filename = f"CLI_Report_{ticker}_{timestamp}.pdf"
        output_path = os.path.join(REPORTS_DIRECTORY, output_filename)
        
        create_pdf_report(
            ticker=ticker,
            company_name=analysis_data['company_name'],
            quant_results=analysis_data['quant_results'],
            qual_results=analysis_data['qual_results'],
            final_report=analysis_data['final_report'],
            file_path=output_path
        )