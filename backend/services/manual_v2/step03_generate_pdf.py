"""
Manual Rationale Step 3: Generate PDF

Creates a professional PDF report from stocks_with_charts.csv with premium blue theme
"""

import os
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak,
    Table, TableStyle, Flowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage, ImageDraw
from datetime import datetime
import psycopg2
from backend.utils.reportlab_html import extract_html_content


def get_db_connection():
    """Get database connection"""
    import os
    return psycopg2.connect(os.environ["DATABASE_URL"])


def sanitize_filename(s: str) -> str:
    """Sanitize string for safe filesystem usage"""
    return str(s).strip().replace(" ", "_").replace(":", "-").replace("/", "-").replace("\\", "-")


def fetch_pdf_config(job_id: str):
    """Fetch PDF configuration from database tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Fetch job details with channel info (JOIN with channels table)
        cursor.execute("""
            SELECT c.channel_name, c.channel_logo_path, j.title, j.date
            FROM jobs j
            LEFT JOIN channels c ON j.channel_id = c.id
            WHERE j.id = %s
        """, (job_id,))
        job_row = cursor.fetchone()
        if not job_row:
            raise ValueError(f"Job {job_id} not found")
        
        channel_name, channel_logo_path_raw, title, input_date = job_row
        
        # Construct full path for channel logo if it exists
        channel_logo_path = None
        if channel_logo_path_raw:
            # Try to build full path
            if os.path.isabs(channel_logo_path_raw):
                channel_logo_path = channel_logo_path_raw
            else:
                # Try different path combinations
                possible_paths = [
                    f"/home/runner/workspace/backend/uploaded_files/{channel_logo_path_raw}",
                    f"backend/uploaded_files/{channel_logo_path_raw}",
                    channel_logo_path_raw
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        channel_logo_path = path
                        print(f"✅ Found channel logo at: {path}")
                        break
                
                if not channel_logo_path:
                    print(f"⚠️ Channel logo file not found: {channel_logo_path_raw}")
                    print(f"   Tried paths: {possible_paths}")
        
        # Fetch PDF template (company details, disclaimer, disclosure)
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
            # Default values if no template exists
            company_name = "PHD CAPITAL PVT LTD"
            registration_details = "SEBI Regd No - INH000016126  |  AMFI Regd No - ARN-301724  |  APMI Regd No - APRN00865\nBSE Regd No - 6152  |  CIN No.- U67190WB2020PTC237908"
            disclaimer_text = None
            disclosure_text = None
            company_data = None
        
        # Fetch uploaded files (company logo and custom fonts)
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
                # Use the file_path as-is from database (already has full path)
                company_logo_path = file_path
            elif file_type == 'customFont':
                # Use the file_path as-is from database
                if 'bold' in file_name.lower() and not font_bold_path:
                    font_bold_path = file_path
                elif not font_regular_path:
                    font_regular_path = file_path
        
        # Format input_date as string if it's a date object
        input_date_str = None
        if input_date:
            if hasattr(input_date, 'strftime'):
                input_date_str = input_date.strftime('%Y-%m-%d')
            else:
                input_date_str = str(input_date)
        
        return {
            'channel_name': channel_name or "Platform",
            'channel_logo_path': channel_logo_path,
            'title': title or "Rationale Report",
            'input_date': input_date_str,
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


def make_round_logo(src_path, diameter_px=360):
    """Create circular logo from source image"""
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
        tmp_path = os.path.join(os.path.dirname(src_path), "_round_platform_logo.png")
        out.save(tmp_path, "PNG")
        return tmp_path
    except Exception as e:
        print(f"⚠️ Could not create round logo: {e}")
        return src_path




def generate_manual_pdf(job_id: str, job_folder: str, stocks_with_charts):
    """Generate professional PDF report from stocks_with_charts.csv"""
    
    print("\n" + "=" * 60)
    print("MANUAL RATIONALE STEP 3: GENERATE PDF")
    print("=" * 60 + "\n")
    
    # Paths
    stocks_csv = os.path.join(job_folder, "analysis/stocks_with_charts.csv")
    
    if not os.path.exists(stocks_csv):
        raise FileNotFoundError(f"Input file not found: {stocks_csv}")
    
    print(f"📊 Loading stocks from {stocks_csv}...")
    df = pd.read_csv(stocks_csv, encoding="utf-8-sig")
    print(f"✅ Loaded {len(df)} stocks")
    
    # Fetch configuration
    print("🔑 Fetching PDF configuration from database...")
    config = fetch_pdf_config(job_id)
    print(f"✅ Platform: {config['channel_name']}")
    print(f"✅ Report: {config['title']}")
    
    # Output PDF path - use input date from config, not current date
    input_date = config.get('input_date', '')
    if input_date:
        try:
            parsed_date = datetime.strptime(input_date, '%Y-%m-%d')
            date_str = parsed_date.strftime('%d-%m-%Y')
        except:
            date_str = datetime.now().strftime('%d-%m-%Y')
    else:
        date_str = datetime.now().strftime('%d-%m-%Y')
    
    pdf_filename = f"{sanitize_filename(config['channel_name'])}-{date_str}.pdf"
    output_pdf = os.path.join(job_folder, "pdf", pdf_filename)
    os.makedirs(os.path.dirname(output_pdf), exist_ok=True)
    
    print(f"📄 Output: {output_pdf}")
    
    # Fonts
    BASE_REG = "NotoSans"
    BASE_BLD = "NotoSans-Bold"
    
    if config['font_regular_path'] and os.path.exists(config['font_regular_path']):
        pdfmetrics.registerFont(TTFont(BASE_REG, config['font_regular_path']))
    else:
        BASE_REG = "Helvetica"
    
    if config['font_bold_path'] and os.path.exists(config['font_bold_path']):
        pdfmetrics.registerFont(TTFont(BASE_BLD, config['font_bold_path']))
    else:
        BASE_BLD = "Helvetica-Bold"
    
    # Colors & Dimensions
    BLUE = colors.HexColor("#1a5490")  # Premium darker blue
    PAGE_W, PAGE_H = A4
    M_L, M_R, M_T, M_B = 44, 44, 96, 52
    
    # Styles
    styles = getSampleStyleSheet()
    
    def PS(name, **kw):
        if "fontName" not in kw:
            kw["fontName"] = BASE_REG
        return ParagraphStyle(name, parent=styles["Normal"], **kw)
    
    subheading_style = PS("subheading", fontSize=16, leading=20, textColor=colors.black,
                         spaceAfter=10, spaceBefore=6, alignment=TA_LEFT, fontName=BASE_BLD)
    small_grey = PS("small_grey", fontSize=9.2, leading=12, textColor=colors.HexColor("#666666"))
    body_style = PS("body_style", fontSize=10.8, leading=15.6, spaceAfter=10, alignment=TA_JUSTIFY)
    label_style = PS("label_style", fontSize=11, leading=14.5, spaceAfter=4, alignment=TA_LEFT,
                    textColor=BLUE, fontName=BASE_BLD)
    date_bold = PS("date_bold", fontSize=11, leading=13.5, alignment=TA_RIGHT,
                  textColor=colors.black, fontName=BASE_BLD)
    time_small = PS("time_small", fontSize=9.6, leading=11.5, alignment=TA_RIGHT,
                   textColor=colors.HexColor("#666666"))
    indented_body = PS("indented_body", fontSize=10.8, leading=15.6, spaceAfter=10,
                      alignment=TA_JUSTIFY, leftIndent=10, rightIndent=10)
    
    # Premium Heading Flowable
    class RoundedHeading(Flowable):
        def __init__(self, text, fontName=BASE_BLD, fontSize=14.5, pad_x=14, pad_y=11,
                    radius=0, bg=BLUE, fg=colors.white, width=None, align="left"):
            Flowable.__init__(self)
            self.text = text
            self.fontName = fontName
            self.fontSize = fontSize
            self.pad_x = pad_x
            self.pad_y = pad_y
            self.radius = radius
            self.bg = bg
            self.fg = fg
            self.width = width
            self.align = align
        
        def wrap(self, availWidth, availHeight):
            self.eff_width = self.width or availWidth
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
        return RoundedHeading(text, width=(PAGE_W - M_L - M_R), align="left")
    
    # Create round logo
    ROUND_LOGO = None
    if config['channel_logo_path'] and os.path.exists(config['channel_logo_path']):
        try:
            logo_path = make_round_logo(config['channel_logo_path'])
            if logo_path and os.path.exists(logo_path):
                ROUND_LOGO = logo_path
        except Exception as e:
            print(f"⚠️ Could not create round logo: {e}")
    
    # Padded block helper
    def padded_block(flowables, left=10, right=10):
        total_w = PAGE_W - M_L - M_R
        rows = [[f] for f in flowables]
        tbl = Table(rows, colWidths=[total_w])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), left),
            ("RIGHTPADDING", (0,0), (-1,-1), right),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        return tbl
    
    # Page decorations
    def draw_letterhead(c: pdfcanvas.Canvas):
        header_h = 72
        c.setFillColor(BLUE)
        c.rect(0, PAGE_H - header_h, PAGE_W, header_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(BASE_BLD, 13.5)
        c.drawString(40, PAGE_H - 30, config['company_name'])
        c.setFont(BASE_REG, 7.5)
        
        reg_text = config['registration_details']
        import re
        if '<' in reg_text and '>' in reg_text:
            reg_text = re.sub(r'<[^>]+>', ' ', reg_text)
            reg_text = ' '.join(reg_text.split())
        
        max_width = PAGE_W - 140
        if '\n' in reg_text:
            reg_lines = reg_text.split('\n')
        elif '|' in reg_text:
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
        for line in reg_lines:
            c.drawString(40, y_pos, line)
            y_pos -= 10
        
        if config['company_logo_path'] and os.path.exists(config['company_logo_path']):
            try:
                c.drawImage(config['company_logo_path'], PAGE_W - 90, PAGE_H - 55, 48, 24,
                           preserveAspectRatio=True, mask='auto')
            except Exception as e:
                print(f"⚠️ Could not draw company logo: {e}")
    
    def draw_blue_stripe_header(c: pdfcanvas.Canvas):
        stripe_h = 20
        c.setFillColor(BLUE)
        c.rect(0, PAGE_H - stripe_h, PAGE_W, stripe_h, fill=1, stroke=0)
    
    def draw_footer(c: pdfcanvas.Canvas):
        c.setFont(BASE_REG, 8.5)
        c.setFillColor(colors.black)
        c.drawCentredString(PAGE_W/2.0, 16, f"Page {c.getPageNumber()}")
        
        total_w = PAGE_W - M_L - M_R
        col_w = total_w / 2.0
        left_x = M_L
        baseline_y = 30
        
        logo_sz = 18
        cur_x = left_x
        if ROUND_LOGO and os.path.exists(ROUND_LOGO):
            try:
                c.drawImage(ROUND_LOGO, cur_x, baseline_y - logo_sz/2, logo_sz, logo_sz,
                           preserveAspectRatio=True, mask='auto')
                cur_x += logo_sz + 6
            except Exception as e:
                print(f"⚠️ Could not draw logo in footer: {e}")
                c.setStrokeColor(BLUE)
                c.circle(cur_x + logo_sz/2, baseline_y, logo_sz/2, stroke=1, fill=0)
                cur_x += logo_sz + 6
        else:
            c.setStrokeColor(BLUE)
            c.circle(cur_x + logo_sz/2, baseline_y, logo_sz/2, stroke=1, fill=0)
            cur_x += logo_sz + 6
        
        c.setFillColor(BLUE)
        c.setFont(BASE_BLD, 9)
        c.drawString(cur_x, baseline_y + 4, config['channel_name'])
        c.setFont(BASE_REG, 8)
        c.drawString(cur_x, baseline_y - 7, "Trading Platform")
    
    def on_first_page(c: pdfcanvas.Canvas, d: SimpleDocTemplate):
        draw_letterhead(c)
        draw_footer(c)
    
    def on_later_pages(c: pdfcanvas.Canvas, d: SimpleDocTemplate):
        draw_blue_stripe_header(c)
        draw_footer(c)
    
    # Document setup
    doc = SimpleDocTemplate(
        output_pdf, pagesize=A4,
        leftMargin=M_L, rightMargin=M_R, topMargin=M_T, bottomMargin=M_B,
        title=config['title']
    )
    
    story = []
    
    # Helper functions
    def positional_date_time(date_text: str, time_text: str):
        total_w = PAGE_W - M_L - M_R
        left_w = total_w * 0.40
        right_w = total_w - left_w
        
        left_chip = RoundedHeading(
            "Positional", fontSize=13.5, pad_x=12, pad_y=10, radius=8,
            bg=BLUE, fg=colors.white, width=left_w, align="left"
        )
        
        right_bits = []
        if date_text:
            right_bits.append(Paragraph(f"<b>Date:</b> {date_text}", date_bold))
        if time_text:
            right_bits.append(Paragraph(f"Time: {time_text}", time_small))
        
        right_stack = Table([[b] for b in right_bits] or [[Spacer(1,0)]], colWidths=[right_w])
        right_stack.setStyle(TableStyle([
            ("ALIGN", (0,0), (-1,-1), "RIGHT"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
            ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ]))
        
        tbl = Table([[left_chip, right_stack]], colWidths=[left_w, right_w])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        return tbl
    
    def full_width_chart(path):
        max_w = PAGE_W - M_L - M_R
        h = max(3.2*inch, min(max_w * 9/16, 4.8*inch))
        return Image(path, width=max_w, height=h)
    
    # Stock pages
    print(f"📝 Generating {len(df)} stock pages...")
    for idx, row in df.iterrows():
        date_val = str(row.get("DATE", "") or "").strip()
        time_val = str(row.get("TIME", "") or "").strip()
        
        story.append(positional_date_time(date_val, time_val))
        story.append(Spacer(1, 10))
        
        listed = str(row.get("LISTED NAME", "") or "").strip()
        symbol = str(row.get("STOCK SYMBOL", "") or "").strip()
        title_line = f"{listed} ({symbol})" if symbol else listed
        story.append(Paragraph(title_line, subheading_style))
        story.append(Spacer(1, 8))
        
        # Chart
        chart_path = str(row.get("CHART PATH", "") or "").strip()
        if chart_path:
            if not os.path.isabs(chart_path):
                chart_path = os.path.join(job_folder, chart_path)
            
            if os.path.exists(chart_path):
                try:
                    story.append(full_width_chart(chart_path))
                    story.append(Spacer(1, 14))
                except Exception as e:
                    print(f"⚠️ Could not add chart {chart_path}: {e}")
                    story.append(Paragraph("<i>Chart unavailable</i>", small_grey))
                    story.append(Spacer(1, 10))
            else:
                story.append(Paragraph("<i>Chart unavailable</i>", small_grey))
                story.append(Spacer(1, 10))
        else:
            story.append(Paragraph("<i>Chart unavailable</i>", small_grey))
            story.append(Spacer(1, 10))
        
        # Rationale
        story.append(heading("Rationale"))
        story.append(Spacer(1, 10))
        
        analysis_text = str(row.get("ANALYSIS", "") or "—").strip()
        under_rationale = [
            Paragraph("<b>OUR GENERAL VIEW</b>", label_style),
            Spacer(1, 2),
            Paragraph(analysis_text, body_style),
        ]
        story.append(padded_block(under_rationale))
        
        story.append(PageBreak())
        
        if (idx + 1) % 10 == 0:
            print(f"  ✅ Generated {idx + 1}/{len(df)} pages")
    
    # Disclaimer
    if config.get('disclaimer_text'):
        print("📋 Adding Disclaimer section...")
        story.append(heading("Disclaimer"))
        story.append(Spacer(1, 10))
        disclaimer_content = extract_html_content(config['disclaimer_text'])
        story.append(Paragraph(disclaimer_content, indented_body))
        story.append(Spacer(1, 35))
    
    # Disclosure
    if config.get('disclosure_text'):
        print("📋 Adding Disclosure section...")
        story.append(heading("Disclosure"))
        story.append(Spacer(1, 10))
        disclosure_content = extract_html_content(config['disclosure_text'])
        story.append(Paragraph(disclosure_content, indented_body))
        story.append(Spacer(1, 35))
    
    # Build PDF
    print("🔨 Building PDF...")
    doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
    
    print(f"✅ PDF generated successfully!")
    print(f"📄 Output: {output_pdf}")
    print(f"📊 Total pages: {len(df)} stocks + disclaimers\n")
    
    return output_pdf
