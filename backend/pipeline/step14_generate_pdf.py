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
            SELECT c.channel_name, c.channel_logo_path, j.youtube_url, j.title
            FROM jobs j
            LEFT JOIN channels c ON j.channel_id = c.id
            WHERE j.id = %s
        """, (job_id,))
        job_row = cursor.fetchone()
        if not job_row:
            raise ValueError(f"Job {job_id} not found")
        
        channel_name, channel_logo_path_raw, youtube_url, title = job_row
        
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
        
        return {
            'channel_name': channel_name or "YouTube Channel",
            'channel_logo_path': channel_logo_path,
            'video_url': youtube_url or "",
            'title': title or "Rationale Report",
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


def generate_pdf_report(job_id: str):
    """
    Step 14: Generate PDF
    Creates a professional PDF report from stocks_with_chart.csv
    """
    print("=" * 60)
    print("STEP 14: Generate PDF")
    print("=" * 60)
    
    # Paths
    job_folder = f"backend/job_files/{job_id}"
    stocks_csv = os.path.join(job_folder, "analysis/stocks_with_chart.csv")
    
    if not os.path.exists(stocks_csv):
        raise FileNotFoundError(f"Input file not found: {stocks_csv}")
    
    print(f"📊 Loading stocks from {stocks_csv}...")
    df = pd.read_csv(stocks_csv, encoding="utf-8-sig")
    print(f"✅ Loaded {len(df)} stocks")
    
    # Fetch configuration from database
    print("🔑 Fetching PDF configuration from database...")
    config = fetch_pdf_config(job_id)
    print(f"✅ Channel: {config['channel_name']}")
    print(f"✅ Video: {config['title']}")
    
    # Output PDF path - format: channel-name-date-time.pdf
    from datetime import datetime
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")  # YYYYMMDD
    time_str = now.strftime("%H%M%S")  # HHMMSS
    pdf_filename = f"{sanitize_filename(config['channel_name'])}-{date_str}-{time_str}.pdf"
    pdf_title = f"{sanitize_filename(config['channel_name'])}-{date_str}-{time_str}"
    output_pdf = os.path.join(job_folder, pdf_filename)
    print(f"📄 Output: {output_pdf}")
    
    # ========= FONTS =========
    BASE_REG = "NotoSans"
    BASE_BLD = "NotoSans-Bold"
    
    # Try custom fonts from database first, fallback to system fonts
    if config['font_regular_path'] and os.path.exists(config['font_regular_path']):
        pdfmetrics.registerFont(TTFont(BASE_REG, config['font_regular_path']))
        print(f"✅ Loaded custom font (regular): {config['font_regular_path']}")
    else:
        # Fallback to Helvetica
        BASE_REG = "Helvetica"
        print(f"⚠️ Using fallback font: {BASE_REG}")
    
    if config['font_bold_path'] and os.path.exists(config['font_bold_path']):
        pdfmetrics.registerFont(TTFont(BASE_BLD, config['font_bold_path']))
        print(f"✅ Loaded custom font (bold): {config['font_bold_path']}")
    else:
        # Fallback to Helvetica-Bold
        BASE_BLD = "Helvetica-Bold"
        print(f"⚠️ Using fallback font: {BASE_BLD}")
    
    # ========= STYLES =========
    styles = getSampleStyleSheet()
    BLUE = colors.HexColor("#003366")
    PAGE_W, PAGE_H = A4
    M_L, M_R, M_T, M_B = 44, 44, 96, 52
    
    # Helper to create ParagraphStyles
    def PS(name, **kw):
        if "fontName" not in kw:
            kw["fontName"] = BASE_REG
        return ParagraphStyle(name, parent=styles["Normal"], **kw)
    
    # Text styles
    subheading_style = PS(
        "subheading_style",
        fontSize=16, leading=20, textColor=colors.black,
        spaceAfter=10, spaceBefore=6, alignment=TA_LEFT,
        fontName=BASE_BLD
    )
    small_grey   = PS("small_grey",  fontSize=9.2, leading=12, textColor=colors.HexColor("#666666"))
    body_style   = PS("body_style",  fontSize=10.8, leading=15.6, spaceAfter=10, alignment=TA_JUSTIFY)
    label_style  = PS("label_style", fontSize=11,   leading=14.5, spaceAfter=4, alignment=TA_LEFT,
                      textColor=BLUE, fontName=BASE_BLD)
    date_bold    = PS("date_bold",   fontSize=11,   leading=13.5, alignment=TA_RIGHT,
                      textColor=colors.black, fontName=BASE_BLD)
    time_small   = PS("time_small",  fontSize=9.6,  leading=11.5, alignment=TA_RIGHT,
                      textColor=colors.HexColor("#666666"))
    center_small = PS("center_small",fontSize=11,   leading=14, alignment=TA_CENTER,
                      textColor=BLUE, fontName=BASE_BLD)
    indented_body = PS("indented_body", fontSize=10.8, leading=15.6, spaceAfter=10, 
                       alignment=TA_JUSTIFY, leftIndent=10, rightIndent=10)
    
    # ========= Premium Heading Flowable =========
    class RoundedHeading(Flowable):
        """Premium heading with crisp edges, perfect alignment, no rounded corners."""
        def __init__(self, text, fontName=BASE_BLD, fontSize=14.5, pad_x=14, pad_y=11,
                     radius=0, bg=BLUE, fg=colors.white, width=None, align="left"):
            Flowable.__init__(self)
            self.text = text
            self.fontName = fontName
            self.fontSize = fontSize
            self.pad_x = pad_x
            self.pad_y = pad_y
            self.radius = radius  # Set to 0 for crisp, professional edges
            self.bg = bg
            self.fg = fg
            self.width = width
            self.align = align
        
        def wrap(self, availWidth, availHeight):
            self.eff_width = self.width or availWidth
            # Equal padding top and bottom for perfect vertical centering
            self.eff_height = self.fontSize + 2*self.pad_y
            return self.eff_width, self.eff_height
        
        def draw(self):
            c = self.canv
            w, h = self.eff_width, self.eff_height
            r = self.radius
            
            c.saveState()
            c.setFillColor(self.bg)
            c.setStrokeColor(self.bg)
            # Use rect for sharp corners (professional look)
            if r == 0:
                c.rect(0, 0, w, h, fill=1, stroke=0)
            else:
                c.roundRect(0, 0, w, h, r, fill=1, stroke=0)
            
            c.setFillColor(self.fg)
            c.setFont(self.fontName, self.fontSize)
            tx = self.pad_x
            # Perfect vertical centering: exactly halfway
            ty = (h - self.fontSize) / 2.0
            c.drawString(tx, ty, self.text)
            c.restoreState()
    
    # Heading factory (full-width)
    def heading(text):
        return RoundedHeading(text, width=(PAGE_W - M_L - M_R), align="left")
    
    # ========= Utilities =========
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
            tmp_path = os.path.join(job_folder, "_round_channel_logo.png")
            out.save(tmp_path, "PNG")
            return tmp_path
        except Exception as e:
            print(f"⚠️ Could not create round logo: {e}")
            return src_path
    
    # Create round channel logo
    ROUND_CHANNEL_LOGO = None
    if config['channel_logo_path'] and os.path.exists(config['channel_logo_path']):
        # Use local channel logo from database
        try:
            logo_path = make_round_logo(config['channel_logo_path'])
            if logo_path and os.path.exists(logo_path):
                ROUND_CHANNEL_LOGO = logo_path
                print(f"✅ Created round channel logo from {config['channel_logo_path']} → {ROUND_CHANNEL_LOGO}")
            else:
                print(f"⚠️ Round logo created but file not found: {logo_path}")
        except Exception as e:
            print(f"⚠️ Could not create round channel logo: {e}")
    else:
        if config['channel_logo_path']:
            print(f"⚠️ Channel logo path not found: {config['channel_logo_path']}")
        else:
            print("ℹ️ No channel logo configured")
    
    # Padded block helper
    PADDING_UNDER_HEADING_LR = 10
    
    def padded_block(flowables, left=PADDING_UNDER_HEADING_LR, right=PADDING_UNDER_HEADING_LR):
        """A splittable padded container"""
        total_w = PAGE_W - M_L - M_R
        rows = [[f] for f in flowables]
        tbl = Table(rows, colWidths=[total_w])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING",  (0,0), (-1,-1), left),
            ("RIGHTPADDING", (0,0), (-1,-1), right),
            ("TOPPADDING",   (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",(0,0), (-1,-1), 2),
        ]))
        return tbl
    
    # ========= Page Decorations =========
    def draw_letterhead(c: pdfcanvas.Canvas):
        """Draw header on first page with company details"""
        header_h = 72
        c.setFillColor(BLUE)
        c.rect(0, PAGE_H - header_h, PAGE_W, header_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(BASE_BLD, 13.5)
        c.drawString(40, PAGE_H - 30, config['company_name'])
        c.setFont(BASE_REG, 7.5)
        
        # Parse registration_details for HTML content
        import re
        from html.parser import HTMLParser
        
        class HTMLTextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text_parts = []
            
            def handle_data(self, data):
                self.text_parts.append(data.strip())
        
        reg_text = config['registration_details']
        # Check if contains HTML tags
        if '<' in reg_text and '>' in reg_text:
            # Strip HTML tags and get plain text
            extractor = HTMLTextExtractor()
            try:
                extractor.feed(reg_text)
                reg_text = ' | '.join([t for t in extractor.text_parts if t])
            except:
                # If parsing fails, use regex to strip tags
                reg_text = re.sub(r'<[^>]+>', ' ', reg_text)
                reg_text = ' '.join(reg_text.split())
        
        # Split registration details into multiple lines to avoid overlap with logo
        # Maximum width: leave space for logo (90px from right edge)
        max_width = PAGE_W - 140
        
        # If text contains newlines, respect them
        if '\n' in reg_text:
            reg_lines = reg_text.split('\n')
        else:
            # Otherwise, split by pipe separator for cleaner layout
            if '|' in reg_text:
                parts = [p.strip() for p in reg_text.split('|')]
                # Group into lines that fit within max_width
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
        
        # Draw lines with proper spacing
        y_pos = PAGE_H - 45
        line_height = 10
        for line in reg_lines:
            c.drawString(40, y_pos, line)
            y_pos -= line_height
        
        # Company logo (try full path)
        if config['company_logo_path']:
            logo_path = config['company_logo_path']
            if os.path.exists(logo_path):
                try:
                    c.drawImage(logo_path, PAGE_W - 90, PAGE_H - 55, 48, 24, 
                               preserveAspectRatio=True, mask='auto')
                    print(f"✅ Company logo drawn from: {logo_path}")
                except Exception as e:
                    print(f"⚠️ Could not draw company logo from {logo_path}: {e}")
            else:
                print(f"⚠️ Company logo file not found: {logo_path}")
    
    def draw_blue_stripe_header(c: pdfcanvas.Canvas):
        """Draw simple blue stripe on subsequent pages"""
        stripe_h = 20
        c.setFillColor(BLUE)
        c.rect(0, PAGE_H - stripe_h, PAGE_W, stripe_h, fill=1, stroke=0)
    
    def draw_footer(c: pdfcanvas.Canvas):
        """Draw footer with channel info and page number"""
        # Page number centered
        c.setFont(BASE_REG, 8.5)
        c.setFillColor(colors.black)
        c.drawCentredString(PAGE_W/2.0, 16, f"Page {c.getPageNumber()}")
        
        total_w = PAGE_W - M_L - M_R
        col_w = total_w / 2.0
        left_x = M_L
        right_x = M_L + col_w
        baseline_y = 30
        
        # Left block: logo + channel name
        logo_sz = 18
        cur_x = left_x
        if ROUND_CHANNEL_LOGO and os.path.exists(ROUND_CHANNEL_LOGO):
            try:
                c.drawImage(ROUND_CHANNEL_LOGO, cur_x, baseline_y - logo_sz/2, logo_sz, logo_sz,
                           preserveAspectRatio=True, mask='auto')
                cur_x += logo_sz + 6
            except Exception as e:
                print(f"⚠️ Could not draw channel logo in footer: {e}")
                # Draw placeholder circle
                c.setStrokeColor(BLUE)
                c.circle(cur_x + logo_sz/2, baseline_y, logo_sz/2, stroke=1, fill=0)
                cur_x += logo_sz + 6
        else:
            # Draw placeholder circle if no logo
            c.setStrokeColor(BLUE)
            c.circle(cur_x + logo_sz/2, baseline_y, logo_sz/2, stroke=1, fill=0)
            cur_x += logo_sz + 6
        
        c.setFillColor(BLUE)
        c.setFont(BASE_BLD, 9)
        c.drawString(cur_x, baseline_y + 4, config['channel_name'])
        c.setFont(BASE_REG, 8)
        c.drawString(cur_x, baseline_y - 7, "YouTube Channel")
        
        # Right block: YouTube URL
        url_text = config['video_url']
        c.setFont(BASE_REG, 9)
        c.setFillColor(BLUE)
        url_w = c.stringWidth(url_text, BASE_REG, 9)
        url_x = right_x + col_w - url_w
        c.drawString(url_x, baseline_y - 2, url_text)
    
    def on_first_page(c: pdfcanvas.Canvas, d: SimpleDocTemplate):
        draw_letterhead(c)
        draw_footer(c)
    
    def on_later_pages(c: pdfcanvas.Canvas, d: SimpleDocTemplate):
        draw_blue_stripe_header(c)
        draw_footer(c)
    
    # ========= Doc Setup =========
    doc = SimpleDocTemplate(
        output_pdf, pagesize=A4,
        leftMargin=M_L, rightMargin=M_R, topMargin=M_T, bottomMargin=M_B,
        title=pdf_title
    )
    
    story = []
    
    # ========= Helper Functions =========
    def positional_date_time(date_text: str, time_text: str):
        """Two-column row: Positional chip + date/time"""
        total_w = PAGE_W - M_L - M_R
        left_w  = total_w * 0.40
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
        """Full-width chart image"""
        max_w = PAGE_W - M_L - M_R
        h = max(3.2*inch, min(max_w * 9/16, 4.8*inch))
        return Image(path, width=max_w, height=h)
    
    # ========= Stock Pages =========
    print(f"📝 Generating {len(df)} stock pages...")
    for idx, row in df.iterrows():
        date_val = str(row.get("DATE", "") or "").strip()
        time_val = str(row.get("START TIME", "") or "").strip()
        
        story.append(positional_date_time(date_val, time_val))
        story.append(Spacer(1, 10))
        
        # Stock title: LISTED NAME (SYMBOL)
        listed = str(row.get("LISTED NAME", "") or "").strip()
        symbol = str(row.get("STOCK SYMBOL", "") or "").strip()
        title_line = f"{listed} ({symbol})" if symbol else listed
        story.append(Paragraph(title_line, subheading_style))
        story.append(Spacer(1, 8))
        
        # Chart
        chart_path = str(row.get("CHART PATH", "") or "").strip()
        if chart_path:
            # Make path absolute if relative
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
        
        # Rationale heading
        story.append(heading("Rationale"))
        story.append(Spacer(1, 10))
        
        # Analysis content
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
    
    # ========= NO DEFAULTS - ALL DATA MUST COME FROM DATABASE =========
    
    # Disclaimer (ONLY from database - NO DEFAULTS)
    if config.get('disclaimer_text'):
        print("📋 Adding Disclaimer section FROM DATABASE...")
        print(f"   📝 Disclaimer length: {len(config['disclaimer_text'])} chars")
        story.append(heading("Disclaimer"))
        story.append(Spacer(1, 10))
        disclaimer_content = extract_html_content(config['disclaimer_text'])
        story.append(Paragraph(disclaimer_content, indented_body))
        story.append(Spacer(1, 35))  # Increased spacing for premium look
    else:
        print("⚠️ WARNING: No disclaimer_text in database! Skipping Disclaimer section.")
    
    # Disclosure (ONLY from database - NO DEFAULTS) - NO PAGE BREAK
    if config.get('disclosure_text'):
        print("📋 Adding Disclosure section FROM DATABASE...")
        print(f"   📝 Disclosure length: {len(config['disclosure_text'])} chars")
        story.append(heading("Disclosure"))
        story.append(Spacer(1, 10))
        disclosure_content = extract_html_content(config['disclosure_text'])
        story.append(Paragraph(disclosure_content, indented_body))
        story.append(Spacer(1, 35))  # Increased spacing for premium look
    else:
        print("⚠️ WARNING: No disclosure_text in database! Skipping Disclosure section.")
    
    # ========= Company Data (ONLY from Database - NO DEFAULTS) =========
    company_data_dict = {}
    if config.get('company_data'):
        print("📋 Adding Company Data section FROM DATABASE...")
        if isinstance(config['company_data'], str):
            try:
                import json
                company_data_dict = json.loads(config['company_data'])
                print(f"   📝 Parsed company_data JSON with {len(company_data_dict)} keys")
            except Exception as e:
                print(f"⚠️ WARNING: Could not parse company_data JSON: {e}")
                company_data_dict = {}
        elif isinstance(config['company_data'], dict):
            company_data_dict = config['company_data']
            print(f"   📝 Using company_data dict with {len(company_data_dict)} keys")
    else:
        print("⚠️ WARNING: No company_data in database! Skipping Company Data section.")
    
    # Only add Company Data section if we have data from database
    if company_data_dict:
        story.append(heading("Company Data"))
        story.append(Spacer(1, 12))
        
        # Helper to create detail block (uniform styling - no custom colors)
        detail_style = PS("detail_style", fontSize=10, leading=13, spaceAfter=3, alignment=TA_LEFT)
        detail_label = PS("detail_label", fontSize=10, leading=13, spaceAfter=3, alignment=TA_LEFT,
                         fontName=BASE_BLD)
        
        def make_detail_block(title, data):
            """Create a detail block for one officer"""
            items = [Paragraph(f"<b>{title}</b>", detail_label)]
            if 'name' in data:
                items.append(Paragraph(f"Name: {data['name']}", detail_style))
            if 'email' in data:
                items.append(Paragraph(f"Email: {data['email']}", detail_style))
            if 'contact' in data:
                items.append(Paragraph(f"Contact: {data['contact']}", detail_style))
            return items
        
        # Create 2x2 grid: [Compliance, Principal] [Grievance, Contact]
        total_w = PAGE_W - M_L - M_R
        col_w = (total_w - 20) / 2.0
        
        # Row 1: Compliance (left) + Principal (right)
        compliance_block = make_detail_block("Compliance Office Details:", 
                                             company_data_dict.get('compliance', {}))
        principal_block = make_detail_block("Principal Officer Details:", 
                                            company_data_dict.get('principal', {}))
        
        row1_data = [[compliance_block, principal_block]]
        row1_table = Table(row1_data, colWidths=[col_w, col_w])
        row1_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("TOPPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ]))
        story.append(row1_table)
        story.append(Spacer(1, 16))
        
        # Row 2: Grievance (left) + Contact (right)
        grievance_block = make_detail_block("Grievance Office Details:", 
                                            company_data_dict.get('grievance', {}))
        contact_block = make_detail_block("Contact Details:", 
                                         company_data_dict.get('contact', {}))
        
        row2_data = [[grievance_block, contact_block]]
        row2_table = Table(row2_data, colWidths=[col_w, col_w])
        row2_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("TOPPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ]))
        story.append(row2_table)
        story.append(Spacer(1, 20))
    
    # ========= Officers' Details (Fixed HTML) - NO PAGE BREAK =========
    print("📋 Adding Officers' Details section...")
    story.append(heading("Officers' Details"))
    story.append(Spacer(1, 12))
    
    # Officers' Details with BOLD titles for premium look
    officers_html = """<b><font size="11">Compliance Office Details</font></b><br/>
Name: Pradip Halder<br/>
Email: compliance@phdcapital.in<br/>
Contact: +91 3216 297 100"""
    
    officers_html2 = """<b><font size="11">Principal Officer Details</font></b><br/>
Name: Pritam Sardar<br/>
Email: pritam@phdcapital.in<br/>
Contact: +91 8371 887 303"""
    
    officers_html3 = """<b><font size="11">Grievance Office Details</font></b><br/>
Name: Pradip Halder<br/>
Email: compliance@phdcapital.in<br/>
Contact: +91 3216 297 100"""
    
    officers_html4 = """<b><font size="11">General Contact Details</font></b><br/>
Contact: +91 3216 297 100<br/>
Email: support@phdcapital.in"""
    
    # Create 2x2 layout for officers details
    officer_style = PS("officer_style", fontSize=10, leading=14, spaceAfter=6, alignment=TA_LEFT)
    total_w = PAGE_W - M_L - M_R
    col_w = (total_w - 20) / 2.0
    
    # Row 1: Compliance + Principal
    officer_row1 = [[
        [Paragraph(officers_html, officer_style)],
        [Paragraph(officers_html2, officer_style)]
    ]]
    officer_table1 = Table(officer_row1, colWidths=[col_w, col_w])
    officer_table1.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(officer_table1)
    story.append(Spacer(1, 16))
    
    # Row 2: Grievance + Contact
    officer_row2 = [[
        [Paragraph(officers_html3, officer_style)],
        [Paragraph(officers_html4, officer_style)]
    ]]
    officer_table2 = Table(officer_row2, colWidths=[col_w, col_w])
    officer_table2.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(officer_table2)
    story.append(Spacer(1, 20))
    
    # ========= Build PDF =========
    print("🔨 Building PDF...")
    doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
    
    print(f"✅ PDF generated successfully!")
    print(f"📄 Output: {output_pdf}")
    print(f"📊 Total pages: {len(df)} stocks + 2 (disclaimer/disclosure)")
    
    return output_pdf


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python step14_generate_pdf.py <job_id>")
        sys.exit(1)
    
    job_id = sys.argv[1]
    generate_pdf_report(job_id)
