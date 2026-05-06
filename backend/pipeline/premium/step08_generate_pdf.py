"""
Premium Step 8: Generate Final PDF Report

Creates a professional PDF report from stocks_with_analysis.csv
Uses burgundy/maroon color scheme to differentiate from Media Rationale
"""

import os
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, BaseDocTemplate, Paragraph, Spacer, Image, PageBreak,
    Table, TableStyle, Flowable, PageTemplate, Frame, NextPageTemplate
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage, ImageDraw
import psycopg2
from backend.utils.reportlab_html import extract_html_content


def get_db_connection():
    """Get database connection"""
    import os
    return psycopg2.connect(os.environ["DATABASE_URL"])


def sanitize_filename(s: str) -> str:
    """Sanitize string for safe filesystem usage"""
    return str(s).strip().replace(" ", "_").replace(":", "-").replace("/", "-").replace("\\", "-")


def safe_str(value, default=""):
    """Safely convert value to string, handling None/NaN"""
    if pd.isna(value) or value is None or value == "":
        return default
    try:
        return str(value).strip()
    except:
        return default


def fetch_pdf_config(job_id: str):
    """Fetch PDF configuration from database tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Fetch job details with channel info
        cursor.execute("""
            SELECT c.channel_name, c.channel_logo_path, c.channel_url
            FROM jobs j
            LEFT JOIN channels c ON j.channel_id = c.id
            WHERE j.id = %s
        """, (job_id,))
        job_row = cursor.fetchone()
        if not job_row:
            raise ValueError(f"Job {job_id} not found")
        
        channel_name, channel_logo_path_raw, channel_url = job_row
        
        # Construct full path for channel logo if it exists
        channel_logo_path = None
        if channel_logo_path_raw:
            if os.path.isabs(channel_logo_path_raw):
                channel_logo_path = channel_logo_path_raw
            else:
                possible_paths = [
                    f"/home/runner/workspace/backend/uploaded_files/{channel_logo_path_raw}",
                    f"backend/uploaded_files/{channel_logo_path_raw}",
                    channel_logo_path_raw
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        channel_logo_path = path
                        break
        
        # Fetch PDF template
        cursor.execute("""
            SELECT company_name, registration_details, disclaimer_text, disclosure_text, company_data
            FROM pdf_template
            ORDER BY id DESC
            LIMIT 1
        """)
        template_row = cursor.fetchone()
        if template_row:
            company_name, registration_details, disclaimer_text, disclosure_text, company_data = template_row
        else:
            company_name = "PHD CAPITAL PVT LTD"
            registration_details = "SEBI Regd No - INH000016126 | AMFI Regd No - ARN-301724 | APMI Regd No - APRN00865\nBSE Regd No - 6152 | CIN No.- U67190WB2020PTC237908"
            disclaimer_text = None
            disclosure_text = None
            company_data = None
        
        # Fetch uploaded files
        cursor.execute("""
            SELECT file_type, file_path, file_name
            FROM uploaded_files
            WHERE file_type IN ('companyLogo', 'customFont')
            ORDER BY uploaded_at DESC
        """)
        uploaded_files = cursor.fetchall()
        
        company_logo_path = None
        font_regular_path = None
        font_bold_path = None
        
        for file_type, file_path, file_name in uploaded_files:
            if file_type == 'companyLogo' and not company_logo_path:
                company_logo_path = file_path
            elif file_type == 'customFont':
                if 'bold' in file_name.lower() and not font_bold_path:
                    font_bold_path = file_path
                elif not font_regular_path:
                    font_regular_path = file_path
        
        return {
            'channel_name': channel_name or "Investment Channel",
            'channel_logo_path': channel_logo_path,
            'channel_url': channel_url or "",
            'company_name': company_name,
            'registration_details': registration_details,
            'disclaimer_text': disclaimer_text,
            'disclosure_text': disclosure_text,
            'company_data': company_data,
            'company_logo_path': company_logo_path,
            'font_regular_path': font_regular_path,
            'font_bold_path': font_bold_path
        }
    
    finally:
        cursor.close()
        conn.close()


def run(job_folder, template_config=None):
    """
    Generate final PDF report from stocks_with_analysis.csv
    
    Args:
        job_folder: Path to job directory
        template_config: Optional PDF template configuration (unused, fetched from DB)
    
    Returns:
        dict: {
            'success': bool,
            'output_file': str,
            'error': str or None
        }
    """
    print("\n" + "=" * 60)
    print("PREMIUM STEP 8: GENERATE PDF REPORT")
    print(f"{'='*60}\n")
    
    try:
        # Extract job_id from folder path
        job_id = os.path.basename(job_folder)
        
        # Paths
        analysis_folder = os.path.join(job_folder, 'analysis')
        pdf_folder = os.path.join(job_folder, 'pdf')
        charts_folder = os.path.join(job_folder, 'charts')
        os.makedirs(pdf_folder, exist_ok=True)
        
        # Support both Premium (stocks_with_analysis.csv) and Manual (stocks_with_charts.csv) 
        stocks_csv = os.path.join(analysis_folder, 'stocks_with_analysis.csv')
        if not os.path.exists(stocks_csv):
            # Fallback to Manual Rationale CSV name
            stocks_csv = os.path.join(analysis_folder, 'stocks_with_charts.csv')
        
        if not os.path.exists(stocks_csv):
            return {
                'success': False,
                'error': f'Stock analysis CSV not found in {analysis_folder}'
            }
        
        print("📖 Loading stocks with analysis...")
        df = pd.read_csv(stocks_csv, encoding='utf-8')
        print(f"✅ Loaded {len(df)} stocks\n")
        
        # Fetch configuration from database
        print("🔑 Fetching PDF configuration from database...")
        config = fetch_pdf_config(job_id)
        print(f"✅ Channel: {config['channel_name']}")
        
        # Output PDF filename (consistent naming for easy access)
        pdf_filename = "premium_rationale.pdf"
        pdf_title = f"{config['channel_name']} Premium Analysis"
        output_pdf = os.path.join(pdf_folder, pdf_filename)
        print(f"📄 Output: {output_pdf}\n")
        
        # ========= FONTS =========
        BASE_REG = "NotoSans"
        BASE_BLD = "NotoSans-Bold"
        
        if config['font_regular_path'] and os.path.exists(config['font_regular_path']):
            pdfmetrics.registerFont(TTFont(BASE_REG, config['font_regular_path']))
            print(f"✅ Loaded custom font (regular)")
        else:
            BASE_REG = "Helvetica"
            print(f"⚠️  Using fallback font: {BASE_REG}")
        
        if config['font_bold_path'] and os.path.exists(config['font_bold_path']):
            pdfmetrics.registerFont(TTFont(BASE_BLD, config['font_bold_path']))
            print(f"✅ Loaded custom font (bold)")
        else:
            BASE_BLD = "Helvetica-Bold"
            print(f"⚠️  Using fallback font: {BASE_BLD}")
        
        print()
        
        # ========= PREMIUM COLOR SCHEME =========
        # Dark Lavender for Premium (vs Blue for Media)
        LAVENDER = colors.HexColor("#6B5B95")  # Dark lavender
        ACCENT_GOLD = colors.HexColor("#D4AF37")  # Gold accent
        
        PAGE_W, PAGE_H = A4
        M_L, M_R, M_T, M_B = 44, 44, 96, 52
        CONTENT_INSET = 0  # No additional inset - use margins only
        
        # ========= STYLES =========
        styles = getSampleStyleSheet()
        
        def PS(name, **kw):
            if "fontName" not in kw:
                kw["fontName"] = BASE_REG
            return ParagraphStyle(name, parent=styles["Normal"], **kw)
        
        subheading_style = PS(
            "subheading_style",
            fontSize=15.5, leading=19, textColor=colors.black,
            spaceAfter=10, spaceBefore=6, alignment=TA_LEFT,
            fontName=BASE_BLD
        )
        small_grey = PS("small_grey", fontSize=9, leading=11, textColor=colors.HexColor("#666666"))
        body_style = PS("body_style", fontSize=10.5, leading=15, spaceAfter=10, alignment=TA_JUSTIFY)
        label_style = PS("label_style", fontSize=10.5, leading=14, spaceAfter=4, alignment=TA_LEFT,
                        textColor=LAVENDER, fontName=BASE_BLD)
        date_bold = PS("date_bold", fontSize=10.5, leading=13, alignment=TA_RIGHT,
                      textColor=colors.black, fontName=BASE_BLD)
        time_small = PS("time_small", fontSize=9.5, leading=11, alignment=TA_RIGHT,
                       textColor=colors.HexColor("#666666"))
        officer_label = PS("officer_label", fontSize=9.5, leading=12, textColor=LAVENDER, fontName=BASE_BLD)
        officer_value = PS("officer_value", fontSize=9, leading=11.5, textColor=colors.black)
        
        # ========= Premium Heading Flowable =========
        class PremiumHeading(Flowable):
            """Premium heading with lavender background - uses available width"""
            def __init__(self, text, fontName=BASE_BLD, fontSize=14, pad_x=14, pad_y=10,
                        bg=LAVENDER, fg=colors.white):
                Flowable.__init__(self)
                self.text = text
                self.fontName = fontName
                self.fontSize = fontSize
                self.pad_x = pad_x
                self.pad_y = pad_y
                self.bg = bg
                self.fg = fg
            
            def wrap(self, availWidth, availHeight):
                # Use the actual available width from the frame
                self.eff_width = availWidth
                self.eff_height = self.fontSize + 2*self.pad_y
                return self.eff_width, self.eff_height
            
            def draw(self):
                c = self.canv
                w, h = self.eff_width, self.eff_height
                
                c.saveState()
                c.setFillColor(self.bg)
                c.setStrokeColor(self.bg)
                c.rect(0, 0, w, h, fill=1, stroke=0)
                
                c.setFillColor(self.fg)
                c.setFont(self.fontName, self.fontSize)
                tx = self.pad_x
                ty = (h - self.fontSize) / 2.0
                c.drawString(tx, ty, self.text)
                c.restoreState()
        
        def heading(text):
            return PremiumHeading(text)
        
        # ========= Utilities =========
        def make_round_logo(src_path, diameter_px=360):
            """Create circular logo"""
            try:
                im = PILImage.open(src_path).convert("RGBA")
                side = min(im.size)
                x0 = (im.width - side) // 2
                y0 = (im.height - side) // 2
                im = im.crop((x0, y0, x0 + side, y0 + side)).resize((diameter_px, diameter_px), PILImage.LANCZOS)
                mask = PILImage.new("L", (diameter_px, diameter_px), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, diameter_px, diameter_px), fill=255)
                out = PILImage.new("RGBA", (diameter_px, diameter_px), (255, 255, 255, 0))
                out.paste(im, (0, 0), mask=mask)
                tmp_path = os.path.join(job_folder, "_round_channel_logo.png")
                out.save(tmp_path, "PNG")
                return tmp_path
            except Exception as e:
                print(f"⚠️  Could not create round logo: {e}")
                return src_path
        
        # Create round channel logo
        ROUND_CHANNEL_LOGO = None
        if config['channel_logo_path'] and os.path.exists(config['channel_logo_path']):
            try:
                logo_path = make_round_logo(config['channel_logo_path'])
                if logo_path and os.path.exists(logo_path):
                    ROUND_CHANNEL_LOGO = logo_path
                    print(f"✅ Created round channel logo")
            except Exception as e:
                print(f"⚠️  Could not create round channel logo: {e}")
        
        # ========= Page Decorations =========
        def draw_letterhead(c: pdfcanvas.Canvas):
            """Draw header on first page"""
            header_h = 72
            c.setFillColor(LAVENDER)
            c.rect(0, PAGE_H - header_h, PAGE_W, header_h, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont(BASE_BLD, 13.5)
            c.drawString(40, PAGE_H - 30, config['company_name'])
            c.setFont(BASE_REG, 7.5)
            
            # Parse registration_details
            import re
            from html.parser import HTMLParser
            
            class HTMLTextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text_parts = []
                
                def handle_data(self, data):
                    self.text_parts.append(data.strip())
            
            reg_text = config['registration_details']
            if '<' in reg_text and '>' in reg_text:
                extractor = HTMLTextExtractor()
                try:
                    extractor.feed(reg_text)
                    reg_text = ' | '.join([t for t in extractor.text_parts if t])
                except:
                    reg_text = re.sub(r'<[^>]+>', ' ', reg_text)
                    reg_text = ' '.join(reg_text.split())
            
            max_width = PAGE_W - 140
            
            if '\n' in reg_text:
                reg_lines = reg_text.split('\n')
            else:
                if '|' in reg_text:
                    parts = [p.strip() for p in reg_text.split('|')]
                    reg_lines = []
                    current_line = ""
                    for part in parts:
                        test_line = current_line + (" | " if current_line else "") + part
                        if c.stringWidth(test_line, BASE_REG, 7.5) <= max_width:
                            current_line = test_line
                        else:
                            if current_line:
                                reg_lines.append(current_line)
                            current_line = part
                    if current_line:
                        reg_lines.append(current_line)
                else:
                    reg_lines = [reg_text]
            
            y_pos = PAGE_H - 45
            line_height = 10
            for line in reg_lines:
                c.drawString(40, y_pos, line)
                y_pos -= line_height
            
            # Company logo
            if config['company_logo_path'] and os.path.exists(config['company_logo_path']):
                try:
                    c.drawImage(config['company_logo_path'], PAGE_W - 90, PAGE_H - 55, 48, 24, 
                               preserveAspectRatio=True, mask='auto')
                except:
                    pass
        
        def draw_lavender_stripe_header(c: pdfcanvas.Canvas):
            """Draw lavender stripe on subsequent pages"""
            stripe_h = 20
            c.setFillColor(LAVENDER)
            c.rect(0, PAGE_H - stripe_h, PAGE_W, stripe_h, fill=1, stroke=0)
        
        def draw_footer(c: pdfcanvas.Canvas):
            """Draw footer with channel info and page number"""
            c.setFont(BASE_REG, 8.5)
            c.setFillColor(colors.black)
            c.drawCentredString(PAGE_W/2.0, 16, f"Page {c.getPageNumber()}")
            
            total_w = PAGE_W - M_L - M_R
            col_w = total_w / 2.0
            left_x = M_L
            right_x = M_L + col_w
            baseline_y = 30
            
            # Left: logo + channel name
            logo_sz = 18
            cur_x = left_x
            if ROUND_CHANNEL_LOGO and os.path.exists(ROUND_CHANNEL_LOGO):
                try:
                    c.drawImage(ROUND_CHANNEL_LOGO, cur_x, baseline_y - logo_sz/2, logo_sz, logo_sz,
                               preserveAspectRatio=True, mask='auto')
                    cur_x += logo_sz + 6
                except:
                    c.setStrokeColor(LAVENDER)
                    c.circle(cur_x + logo_sz/2, baseline_y, logo_sz/2, stroke=1, fill=0)
                    cur_x += logo_sz + 6
            else:
                c.setStrokeColor(LAVENDER)
                c.circle(cur_x + logo_sz/2, baseline_y, logo_sz/2, stroke=1, fill=0)
                cur_x += logo_sz + 6
            
            c.setFillColor(LAVENDER)
            c.setFont(BASE_BLD, 9)
            c.drawString(cur_x, baseline_y + 4, config['channel_name'])
            c.setFont(BASE_REG, 8)
            c.drawString(cur_x, baseline_y - 7, "Premium Analysis")
            
            # Right: Channel URL
            link_text = config['channel_url']
            if link_text:
                c.setFont(BASE_REG, 9)
                c.setFillColor(LAVENDER)
                url_w = c.stringWidth(link_text, BASE_REG, 9)
                url_x = right_x + col_w - url_w
                c.drawString(url_x, baseline_y - 2, link_text)
        
        def on_first_page(c: pdfcanvas.Canvas, d: SimpleDocTemplate):
            draw_letterhead(c)
            draw_footer(c)
        
        def on_later_pages(c: pdfcanvas.Canvas, d: SimpleDocTemplate):
            # Small lavender stripe header for all non-first pages
            draw_lavender_stripe_header(c)
            draw_footer(c)
        
        # ========= Doc Setup with Different Margins =========
        # First page: large top margin for letterhead
        first_frame = Frame(M_L, M_B, PAGE_W - M_L - M_R, PAGE_H - M_T - M_B, id='first')
        first_template = PageTemplate(id='First', frames=[first_frame], onPage=on_first_page)
        
        # Later pages: small top margin (no header needed)
        later_top_margin = 44  # Same as left/right margins
        later_frame = Frame(M_L, M_B, PAGE_W - M_L - M_R, PAGE_H - later_top_margin - M_B, id='later')
        later_template = PageTemplate(id='Later', frames=[later_frame], onPage=on_later_pages)
        
        doc = BaseDocTemplate(
            output_pdf, pagesize=A4,
            leftMargin=M_L, rightMargin=M_R, topMargin=M_T, bottomMargin=M_B,
            title=pdf_title
        )
        doc.addPageTemplates([first_template, later_template])
        
        story = []
        
        # ========= Helper Functions =========
        def positional_date_time(date_text: str, time_text: str):
            """Two-column row: Positional chip + date/time"""
            # Positional chip (will auto-size in table)
            left_chip = PremiumHeading(
                "Positional", fontSize=13, pad_x=12, pad_y=9,
                bg=LAVENDER, fg=colors.white
            )
            
            # Create right side content
            right_content = []
            if date_text:
                right_content.append(f"<b>Date:</b> {date_text}")
            if time_text:
                right_content.append(f"<font size=9 color='#666666'>Time: {time_text}</font>")
            
            right_text = "<br/>".join(right_content) if right_content else ""
            right_para = Paragraph(right_text, date_bold) if right_text else Spacer(1, 0)
            
            # Two-column table with 40/60 split
            tbl = Table([[left_chip, right_para]], colWidths=[None, None])
            tbl.setStyle(TableStyle([
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("ALIGN", (0,0), (0,0), "LEFT"),   # Left cell: left align
                ("ALIGN", (1,0), (1,0), "RIGHT"),  # Right cell: right align
                ("LEFTPADDING", (0,0), (-1,-1), CONTENT_INSET),
                ("RIGHTPADDING", (0,0), (-1,-1), CONTENT_INSET),
                ("TOPPADDING", (0,0), (-1,-1), 0),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ]))
            return tbl
        
        def full_width_chart(path):
            """Full-width chart image"""
            max_w = PAGE_W - M_L - M_R
            h = max(3.2*inch, min(max_w * 9/16, 4.5*inch))
            return Image(path, width=max_w, height=h)
        
        # ========= Stock Pages =========
        print(f"📝 Generating PDF pages for {len(df)} stocks...\n")
        
        for idx, row in df.iterrows():
            date_val = safe_str(row.get("DATE"))
            time_val = safe_str(row.get("TIME"))
            
            story.append(positional_date_time(date_val, time_val))
            story.append(Spacer(1, 10))
            
            # Stock title: LISTED NAME (SYMBOL)
            listed_name = safe_str(row.get("LISTED NAME"))
            stock_symbol = safe_str(row.get("STOCK SYMBOL"))
            if listed_name and stock_symbol:
                title_line = f"{listed_name} ({stock_symbol})"
            elif listed_name:
                title_line = listed_name
            elif stock_symbol:
                title_line = stock_symbol
            else:
                title_line = safe_str(row.get("STOCK NAME"), "Unknown Stock")
            
            story.append(Paragraph(title_line, subheading_style))
            story.append(Spacer(1, 8))
            
            # Chart
            chart_filename = safe_str(row.get("CHART PATH"))
            if chart_filename:
                chart_path = os.path.join(charts_folder, os.path.basename(chart_filename))
                if os.path.exists(chart_path):
                    try:
                        story.append(full_width_chart(chart_path))
                        story.append(Spacer(1, 12))
                    except Exception as e:
                        print(f"  ⚠️  Could not add chart for {stock_symbol}: {e}")
                        story.append(Paragraph("<i>Chart unavailable</i>", small_grey))
                        story.append(Spacer(1, 8))
                else:
                    story.append(Paragraph("<i>Chart unavailable</i>", small_grey))
                    story.append(Spacer(1, 8))
            else:
                story.append(Paragraph("<i>Chart unavailable</i>", small_grey))
                story.append(Spacer(1, 8))
            
            # Stock Details Table
            story.append(heading("Stock Details"))
            story.append(Spacer(1, 8))
            
            table_data = [
                ["Script", "Sector", "Targets", "Stop Loss", "Holding", "Call", "CMP"],
                [
                    safe_str(row.get("STOCK SYMBOL"), "-"),
                    safe_str(row.get("SECTOR"), "-"),
                    safe_str(row.get("TARGETS"), "-"),
                    safe_str(row.get("STOP LOSS"), "-"),
                    safe_str(row.get("HOLDING PERIOD"), "-"),
                    safe_str(row.get("CALL"), "-"),
                    safe_str(row.get("CMP"), "-")
                ]
            ]
            
            # Calculate column widths to match full available width minus margins
            TABLE_MARGIN = 7  # 7px margin on both sides
            total_w = PAGE_W - M_L - M_R - (2 * TABLE_MARGIN)
            col_widths = [
                total_w * 0.14,  # Script
                total_w * 0.16,  # Sector
                total_w * 0.18,  # Targets
                total_w * 0.14,  # Stop Loss
                total_w * 0.14,  # Holding
                total_w * 0.12,  # Call
                total_w * 0.12   # CMP
            ]
            
            details_table = Table(table_data, colWidths=col_widths)
            details_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), LAVENDER),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), BASE_BLD),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 1), (-1, -1), BASE_REG),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EDE7F6")]),  # Light lavender tint
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            
            # Wrap table with 7px left/right margins
            table_wrapper = Table([[details_table]], colWidths=[PAGE_W - M_L - M_R])
            table_wrapper.setStyle(TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), TABLE_MARGIN),
                ("RIGHTPADDING", (0, 0), (-1, -1), TABLE_MARGIN),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            
            story.append(table_wrapper)
            story.append(Spacer(1, 14))
            
            # Rationale Section
            story.append(heading("Rationale - Our General View"))
            story.append(Spacer(1, 10))
            
            analysis_text = safe_str(row.get("ANALYSIS"), "Analysis not available")
            story.append(Paragraph(analysis_text, body_style))
            story.append(Spacer(1, 10))
            
            # Page break after each stock (except last)
            if idx < len(df) - 1:
                # Switch to Later template after first stock page
                if idx == 0:
                    story.append(NextPageTemplate('Later'))
                story.append(PageBreak())
        
        # ========= Disclaimer Page =========
        if config['disclaimer_text'] or config['disclosure_text'] or config['company_data']:
            story.append(PageBreak())
            story.append(Spacer(1, 20))
            
            if config['disclaimer_text']:
                story.append(heading("Disclaimer"))
                story.append(Spacer(1, 10))
                # Convert HTML to ReportLab-compatible format
                disclaimer_content = extract_html_content(config['disclaimer_text'])
                if disclaimer_content:
                    story.append(Paragraph(disclaimer_content, body_style))
                    story.append(Spacer(1, 14))
            
            if config['disclosure_text']:
                story.append(heading("Disclosure"))
                story.append(Spacer(1, 10))
                # Convert HTML to ReportLab-compatible format
                disclosure_content = extract_html_content(config['disclosure_text'])
                if disclosure_content:
                    story.append(Paragraph(disclosure_content, body_style))
                    story.append(Spacer(1, 14))
            
            if config['company_data']:
                story.append(heading("Additional Information"))
                story.append(Spacer(1, 10))
                # Convert HTML to ReportLab-compatible format
                company_data_content = extract_html_content(config['company_data'])
                if company_data_content:
                    story.append(Paragraph(company_data_content, body_style))
                    story.append(Spacer(1, 14))
        
        # ========= Officer Details Page =========
        story.append(PageBreak())
        story.append(Spacer(1, 20))
        story.append(heading("Contact Information"))
        story.append(Spacer(1, 14))
        
        # Officer details in 2-column layout
        officer_data = [
            # Row 1
            [
                Paragraph("<b>Compliance Officer Details</b><br/><br/>Name: Pradip Halder<br/>Email: compliance@phdcapital.in<br/>Contact: +91 3216 297 100", body_style),
                Paragraph("<b>Principal Officer Details</b><br/><br/>Name: Pritam Sardar<br/>Email: pritam@phdcapital.in<br/>Contact: +91 8371 887 303", body_style)
            ],
            # Spacer row
            [Spacer(1, 10), Spacer(1, 10)],
            # Row 2
            [
                Paragraph("<b>Grievance Officer Details</b><br/><br/>Name: Pradip Halder<br/>Email: compliance@phdcapital.in<br/>Contact: +91 3216 297 100", body_style),
                Paragraph("<b>General Contact Details</b><br/><br/>Contact: +91 3216 297 100<br/>Email: support@phdcapital.in", body_style)
            ]
        ]
        
        total_w = PAGE_W - M_L - M_R
        col_w = total_w / 2.0 - 10
        
        officer_table = Table(officer_data, colWidths=[col_w, col_w], spaceBefore=0, spaceAfter=0)
        officer_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("TOPPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F9F9F9")),
            ("BOX", (0,0), (-1,-1), 0.5, colors.grey),
            ("INNERGRID", (0,0), (-1,-1), 0.5, colors.HexColor("#E0E0E0")),
        ]))
        
        story.append(officer_table)
        
        # ========= Build PDF =========
        print("🔨 Building PDF document...")
        doc.build(story)
        
        print(f"\n✅ PDF generated successfully!")
        print(f"   Output: {pdf_filename}")
        print(f"   Location: {output_pdf}\n")
        
        return {
            'success': True,
            'output_file': output_pdf,
            'error': None
        }
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e)
        }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_folder = sys.argv[1]
    else:
        test_folder = "backend/job_files/test_premium_job"
    
    result = run(test_folder)
    print(f"\n{'='*60}")
    print(f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
