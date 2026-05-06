"""
Bulk Rationale Step 6: Generate PDF

Creates a professional PDF report from stocks_with_charts.csv with premium blue theme
(Same design as Manual Rationale)
"""

import os
import re
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
from backend.utils.reportlab_html import extract_html_content, create_html_flowables


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
        cursor.execute("""
            SELECT c.channel_name, c.channel_logo_path, j.title, j.date, j.youtube_url, c.platform
            FROM jobs j
            LEFT JOIN channels c ON j.channel_id = c.id
            WHERE j.id = %s
        """, (job_id,))
        job_row = cursor.fetchone()
        if not job_row:
            raise ValueError(f"Job {job_id} not found")
        
        channel_name, channel_logo_path_raw, title, input_date, youtube_url, platform = job_row
        
        channel_logo_path = None
        if channel_logo_path_raw:
            if os.path.isabs(channel_logo_path_raw):
                channel_logo_path = channel_logo_path_raw
            else:
                possible_paths = [
                    f"/home/runner/workspace/backend/channel_logos/{channel_logo_path_raw}",
                    f"backend/channel_logos/{channel_logo_path_raw}",
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
            registration_details = "SEBI Regd No - INH000016126  |  AMFI Regd No - ARN-301724  |  APMI Regd No - APRN00865\nBSE Regd No - 6152  |  CIN No.- U67190WB2020PTC237908"
            disclaimer_text = None
            disclosure_text = None
            company_data = None
        
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
            'youtube_url': youtube_url or "",
            'platform': platform or "Youtube",
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


def run(job_folder, template_config=None):
    """
    Generate professional PDF report from stocks_with_charts.csv
    
    Args:
        job_folder: Path to job directory
        template_config: Optional PDF template configuration (unused, kept for compatibility)
    
    Returns:
        dict: {
            'success': bool,
            'output_file': str,
            'error': str or None
        }
    """
    print("\n" + "=" * 60)
    print("BULK RATIONALE STEP 6: GENERATE PDF")
    print("=" * 60 + "\n")
    
    try:
        job_id = os.path.basename(job_folder)
        
        stocks_csv = os.path.join(job_folder, "analysis/stocks_with_charts.csv")
        
        if not os.path.exists(stocks_csv):
            return {
                'success': False,
                'error': f'Input file not found: {stocks_csv}'
            }
        
        print(f"📊 Loading stocks from {stocks_csv}...")
        df = pd.read_csv(stocks_csv, encoding="utf-8-sig")
        print(f"✅ Loaded {len(df)} stocks")
        
        print("🔑 Fetching PDF configuration from database...")
        config = fetch_pdf_config(job_id)
        print(f"✅ Platform: {config['channel_name']}")
        print(f"✅ Report: {config['title']}")
        
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
        
        BLUE = colors.HexColor("#1a5490")
        PAGE_W, PAGE_H = A4
        M_L, M_R, M_T, M_B = 44, 44, 96, 52
        
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
        indented_body = PS("indented_body", fontSize=10.8, leading=15.6, spaceAfter=10,
                          alignment=TA_JUSTIFY, leftIndent=10, rightIndent=10)
        
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
        
        ROUND_LOGO = None
        if config['channel_logo_path'] and os.path.exists(config['channel_logo_path']):
            try:
                logo_path = make_round_logo(config['channel_logo_path'])
                if logo_path and os.path.exists(logo_path):
                    ROUND_LOGO = logo_path
            except Exception as e:
                print(f"⚠️ Could not create round logo: {e}")
        
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
        
        def draw_letterhead(c: pdfcanvas.Canvas):
            header_h = 72
            c.setFillColor(BLUE)
            c.rect(0, PAGE_H - header_h, PAGE_W, header_h, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont(BASE_BLD, 13.5)
            c.drawString(40, PAGE_H - 30, config['company_name'])
            c.setFont(BASE_REG, 7.5)
            
            reg_text = config['registration_details']
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
            
            left_x = M_L
            baseline_y = 34
            
            logo_sz = 24
            cur_x = left_x
            if ROUND_LOGO and os.path.exists(ROUND_LOGO):
                try:
                    c.drawImage(ROUND_LOGO, cur_x, baseline_y - logo_sz/2 - 2, logo_sz, logo_sz,
                               preserveAspectRatio=True, mask='auto')
                    cur_x += logo_sz + 8
                except Exception as e:
                    print(f"⚠️ Could not draw logo in footer: {e}")
                    c.setStrokeColor(BLUE)
                    c.circle(cur_x + logo_sz/2, baseline_y, logo_sz/2, stroke=1, fill=0)
                    cur_x += logo_sz + 8
            else:
                c.setStrokeColor(BLUE)
                c.circle(cur_x + logo_sz/2, baseline_y, logo_sz/2, stroke=1, fill=0)
                cur_x += logo_sz + 8
            
            c.setFillColor(BLUE)
            c.setFont(BASE_BLD, 9)
            c.drawString(cur_x, baseline_y + 5, config['channel_name'])
            
            platform = config.get('platform', 'Youtube')
            c.setFont(BASE_REG, 8)
            c.setFillColor(colors.HexColor("#666666"))
            c.drawString(cur_x, baseline_y - 7, platform)
            
            youtube_url = config.get('youtube_url', '')
            if youtube_url:
                c.setFont(BASE_REG, 7)
                c.setFillColor(colors.HexColor("#444444"))
                max_url_width = PAGE_W - M_L - M_R - 150
                display_url = youtube_url
                if c.stringWidth(display_url, BASE_REG, 7) > max_url_width:
                    display_url = display_url[:55] + "..."
                url_width = c.stringWidth(display_url, BASE_REG, 7)
                c.drawString(PAGE_W - M_R - url_width, baseline_y - 1, display_url)
        
        def on_first_page(c: pdfcanvas.Canvas, d: SimpleDocTemplate):
            draw_letterhead(c)
            draw_footer(c)
        
        def on_later_pages(c: pdfcanvas.Canvas, d: SimpleDocTemplate):
            draw_blue_stripe_header(c)
            draw_footer(c)
        
        doc = SimpleDocTemplate(
            output_pdf, pagesize=A4,
            leftMargin=M_L, rightMargin=M_R, topMargin=M_T, bottomMargin=M_B,
            title=config['title']
        )
        
        story = []
        
        def positional_date_header(date_text: str):
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
        
        print(f"📝 Generating {len(df)} stock pages...")
        for idx, row in df.iterrows():
            date_val = str(row.get("DATE", "") or "").strip()
            
            story.append(positional_date_header(date_val))
            story.append(Spacer(1, 10))
            
            listed = str(row.get("LISTED NAME", row.get("INPUT STOCK", row.get("STOCK NAME", ""))) or "").strip()
            symbol = str(row.get("STOCK SYMBOL", "") or "").strip()
            title_line = f"{listed} ({symbol})" if symbol else listed
            story.append(Paragraph(title_line, subheading_style))
            story.append(Spacer(1, 8))
            
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
            
            story.append(heading("Rationale"))
            story.append(Spacer(1, 10))
            
            analysis_text = str(row.get("ANALYSIS", "") or "—").strip()
            story.append(Paragraph("<b>OUR GENERAL VIEW</b>", label_style))
            story.append(Spacer(1, 4))
            story.append(Paragraph(analysis_text, body_style))
            
            story.append(PageBreak())
            
            if (idx + 1) % 10 == 0:
                print(f"  ✅ Generated {idx + 1}/{len(df)} pages")
        
        if config.get('disclaimer_text'):
            print("📋 Adding Disclaimer section...")
            story.append(heading("Disclaimer"))
            story.append(Spacer(1, 10))
            
            list_style = PS("list_style", fontSize=10.8, leading=15.6, spaceAfter=4,
                           alignment=TA_LEFT, leftIndent=25, bulletIndent=15)
            disclaimer_flowables = create_html_flowables(
                config['disclaimer_text'], 
                indented_body,
                list_style=list_style
            )
            for flowable in disclaimer_flowables:
                story.append(flowable)
            story.append(Spacer(1, 35))
        
        if config.get('disclosure_text'):
            print("📋 Adding Disclosure section...")
            story.append(heading("Disclosure"))
            story.append(Spacer(1, 10))
            
            list_style = PS("list_style2", fontSize=10.8, leading=15.6, spaceAfter=4,
                           alignment=TA_LEFT, leftIndent=25, bulletIndent=15)
            disclosure_flowables = create_html_flowables(
                config['disclosure_text'], 
                indented_body,
                list_style=list_style
            )
            for flowable in disclosure_flowables:
                story.append(flowable)
            story.append(Spacer(1, 35))
        
        contact_card_heading = PS("contact_card_heading", fontSize=10, leading=13, 
                                  textColor=BLUE, fontName=BASE_BLD, spaceAfter=4)
        contact_card_body = PS("contact_card_body", fontSize=9.5, leading=13, 
                               textColor=colors.black, fontName=BASE_REG)
        
        def make_contact_card(title, name, email, phone):
            """Create a styled contact card"""
            card_content = [
                Paragraph(f"<b>{title}</b>", contact_card_heading),
                Paragraph(f"<b>Name:</b> {name}", contact_card_body),
                Paragraph(f"<b>Email:</b> {email}", contact_card_body),
                Paragraph(f"<b>Contact:</b> {phone}", contact_card_body),
            ]
            card_table = Table([[c] for c in card_content], colWidths=[(PAGE_W - M_L - M_R - 20) / 2])
            card_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (0, 0), 8),
                ("BOTTOMPADDING", (-1, -1), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8f9fa")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
            ]))
            return card_table
        
        story.append(PageBreak())
        
        print("📋 Adding Contact Details section...")
        story.append(heading("Contact Details"))
        story.append(Spacer(1, 14))
        
        compliance_card = make_contact_card(
            "Compliance Officer Details",
            "Pradip Halder",
            "compliance@phdcapital.in",
            "+91 3216 297 100"
        )
        principal_card = make_contact_card(
            "Principal Officer Details",
            "Pritam Sardar",
            "pritam@phdcapital.in",
            "+91 3216 297 101"
        )
        grievance_card = make_contact_card(
            "Grievance Officer Details",
            "Pradip Halder",
            "compliance@phdcapital.in",
            "+91 3216 297 100"
        )
        general_card = make_contact_card(
            "General Contact Details",
            "PHD Capital",
            "support@phdcapital.in",
            "+91 3216 297 100"
        )
        
        col_width = (PAGE_W - M_L - M_R - 10) / 2
        contact_grid = Table([
            [compliance_card, principal_card],
            [grievance_card, general_card]
        ], colWidths=[col_width, col_width], rowHeights=[None, None])
        
        contact_grid.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        
        story.append(contact_grid)
        story.append(Spacer(1, 35))
        
        print("🔨 Building PDF...")
        doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
        
        print(f"✅ PDF generated successfully!")
        print(f"📄 Output: {output_pdf}")
        print(f"📊 Total pages: {len(df)} stocks + disclaimers\n")
        
        return {
            'success': True,
            'output_file': output_pdf
        }
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
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
        test_folder = "backend/job_files/test_bulk_job"
    
    result = run(test_folder)
    print(f"\n{'='*60}")
    print(f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
