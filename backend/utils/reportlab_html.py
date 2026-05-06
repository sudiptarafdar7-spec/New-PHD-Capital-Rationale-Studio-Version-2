"""
ReportLab HTML Conversion Utilities
Converts rich HTML content from database to ReportLab-compatible format
"""

import re
from reportlab.platypus import Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.lib import colors


def extract_html_content(html_text):
    """Convert HTML to ReportLab-compatible format, preserving formatting
    
    This function transforms rich HTML content (like disclaimers/disclosures)
    into a subset of HTML tags that ReportLab's Paragraph can safely render.
    
    Supported conversions:
    - Headings (h1-h6) → font sizes + bold
    - Strong/em → b/i
    - Paragraphs/divs → line breaks
    - Lists (ul/ol/li) → bullet points with indentation
    - Removes unsupported tags (table, iframe, script, style, para, etc.)
    
    Args:
        html_text: Raw HTML string from database
        
    Returns:
        ReportLab-compatible HTML string
    """
    if not html_text:
        return ""
    
    # If it's already plain text, return as-is
    if '<' not in html_text:
        return html_text.strip()
    
    text = html_text
    
    # Remove document structure tags
    text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head>.*?</head>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'</?body[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<style>.*?</style>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<script>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Convert HTML5/semantic tags to ReportLab-compatible format
    # Convert headings to bold + larger font + line breaks
    text = re.sub(r'<h1[^>]*>(.*?)</h1>', r'<br/><font size="14"><b>\1</b></font><br/><br/>', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<h2[^>]*>(.*?)</h2>', r'<br/><font size="13"><b>\1</b></font><br/><br/>', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<h3[^>]*>(.*?)</h3>', r'<br/><font size="12"><b>\1</b></font><br/>', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<h4[^>]*>(.*?)</h4>', r'<br/><font size="11"><b>\1</b></font><br/>', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<h5[^>]*>(.*?)</h5>', r'<br/><b>\1</b><br/>', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<h6[^>]*>(.*?)</h6>', r'<br/><b>\1</b><br/>', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Convert <strong> and <b> to bold
    text = re.sub(r'<strong[^>]*>', '<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'</strong>', '</b>', text, flags=re.IGNORECASE)
    
    # Convert <em> to italic
    text = re.sub(r'<em[^>]*>', '<i>', text, flags=re.IGNORECASE)
    text = re.sub(r'</em>', '</i>', text, flags=re.IGNORECASE)
    
    # Convert <u> underline (already supported)
    text = re.sub(r'<u[^>]*>', '<u>', text, flags=re.IGNORECASE)
    
    # Convert <p> to line breaks with spacing
    text = re.sub(r'<p[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '<br/><br/>', text, flags=re.IGNORECASE)
    
    # Convert <div> to line breaks
    text = re.sub(r'<div[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '<br/>', text, flags=re.IGNORECASE)
    
    # Convert lists to properly indented bullet points
    # Handle nested lists by adding more indentation
    text = re.sub(r'<ul[^>]*>', '<br/>', text, flags=re.IGNORECASE)
    text = re.sub(r'</ul>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<ol[^>]*>', '<br/>', text, flags=re.IGNORECASE)
    text = re.sub(r'</ol>', '', text, flags=re.IGNORECASE)
    
    # Convert list items with proper indentation (using spaces for left padding)
    text = re.sub(r'<li[^>]*>(.*?)</li>', r'      \u2022  \1<br/>', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove unsupported container tags but keep content
    text = re.sub(r'<(section|article|main|header|footer|nav|aside|container|card|para|span)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</(section|article|main|header|footer|nav|aside|container|card|para|span)>', '', text, flags=re.IGNORECASE)
    
    # Remove tables and their content (not supported)
    text = re.sub(r'<table[^>]*>.*?</table>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<iframe[^>]*>.*?</iframe>', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove any remaining HTML tags that aren't supported
    # Keep only: b, i, u, font, br, super, sub
    def clean_unsupported_tags(match):
        tag = match.group(1).lower()
        if tag in ['b', 'i', 'u', 'font', 'br', 'super', 'sub', '/b', '/i', '/u', '/font', '/super', '/sub']:
            return match.group(0)
        return ''
    
    text = re.sub(r'<(/?\w+)[^>]*/?>', clean_unsupported_tags, text)
    
    # Fix br tags - ensure they're self-closing with no space before slash
    text = re.sub(r'<br\s*/?>', '<br/>', text, flags=re.IGNORECASE)
    
    # Clean up multiple consecutive line breaks (max 2)
    text = re.sub(r'(<br/>){3,}', '<br/><br/>', text, flags=re.IGNORECASE)
    
    # Remove leading/trailing breaks
    text = re.sub(r'^(<br/>)+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(<br/>)+$', '', text, flags=re.IGNORECASE)
    
    # Clean up extra whitespace but preserve intentional indentation
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'> +<', '><', text)
    
    # Ensure proper spacing after bullet points
    text = text.replace('\u2022  ', '\u2022 ')
    
    return text.strip()


def create_html_flowables(html_text, base_style, heading_style=None, list_style=None):
    """
    Convert HTML to a list of ReportLab flowables for better formatting control.
    
    This provides more control over rendering than extract_html_content by creating
    separate Paragraph objects for different elements.
    
    Args:
        html_text: Raw HTML string
        base_style: ParagraphStyle for regular text
        heading_style: Optional ParagraphStyle for headings (defaults to bold version of base)
        list_style: Optional ParagraphStyle for list items (defaults to indented version of base)
    
    Returns:
        List of Flowable objects (Paragraphs, Spacers)
    """
    if not html_text:
        return []
    
    # If it's plain text, return single paragraph
    if '<' not in html_text:
        return [Paragraph(html_text.strip(), base_style)]
    
    flowables = []
    
    # Create default styles if not provided
    if heading_style is None:
        heading_style = ParagraphStyle(
            'heading_style',
            parent=base_style,
            fontName=base_style.fontName.replace('-', '-Bold') if '-' in base_style.fontName else 'Helvetica-Bold',
            fontSize=base_style.fontSize + 2,
            spaceAfter=8,
            spaceBefore=12
        )
    
    if list_style is None:
        list_style = ParagraphStyle(
            'list_style',
            parent=base_style,
            leftIndent=20,
            bulletIndent=10,
            spaceAfter=4
        )
    
    # Process HTML and split into blocks
    text = html_text
    
    # Remove document structure
    text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head>.*?</head>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'</?body[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<style>.*?</style>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<script>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Split by major block elements
    blocks = re.split(r'(<h[1-6][^>]*>.*?</h[1-6]>|<p[^>]*>.*?</p>|<ul[^>]*>.*?</ul>|<ol[^>]*>.*?</ol>|<div[^>]*>.*?</div>)', 
                     text, flags=re.IGNORECASE | re.DOTALL)
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        
        # Check if it's a heading
        heading_match = re.match(r'<h([1-6])[^>]*>(.*?)</h\1>', block, re.IGNORECASE | re.DOTALL)
        if heading_match:
            level = int(heading_match.group(1))
            content = heading_match.group(2)
            # Clean inner HTML
            content = re.sub(r'<[^>]+>', '', content)
            
            h_style = ParagraphStyle(
                f'h{level}_style',
                parent=base_style,
                fontName='Helvetica-Bold',
                fontSize=base_style.fontSize + (6 - level),
                spaceAfter=6,
                spaceBefore=10
            )
            flowables.append(Paragraph(f"<b>{content}</b>", h_style))
            continue
        
        # Check if it's a list
        list_match = re.match(r'<(ul|ol)[^>]*>(.*?)</\1>', block, re.IGNORECASE | re.DOTALL)
        if list_match:
            list_content = list_match.group(2)
            items = re.findall(r'<li[^>]*>(.*?)</li>', list_content, re.IGNORECASE | re.DOTALL)
            for item in items:
                # Clean inner HTML but preserve b/i
                item = re.sub(r'<strong[^>]*>', '<b>', item, flags=re.IGNORECASE)
                item = re.sub(r'</strong>', '</b>', item, flags=re.IGNORECASE)
                item = re.sub(r'<em[^>]*>', '<i>', item, flags=re.IGNORECASE)
                item = re.sub(r'</em>', '</i>', item, flags=re.IGNORECASE)
                item = re.sub(r'<(?!/?[bi]>)[^>]+>', '', item)
                
                flowables.append(Paragraph(f"\u2022  {item.strip()}", list_style))
            flowables.append(Spacer(1, 4))
            continue
        
        # Check if it's a paragraph
        p_match = re.match(r'<p[^>]*>(.*?)</p>', block, re.IGNORECASE | re.DOTALL)
        if p_match:
            content = p_match.group(1)
        else:
            content = block
        
        # Clean and add as regular paragraph
        content = re.sub(r'<strong[^>]*>', '<b>', content, flags=re.IGNORECASE)
        content = re.sub(r'</strong>', '</b>', content, flags=re.IGNORECASE)
        content = re.sub(r'<em[^>]*>', '<i>', content, flags=re.IGNORECASE)
        content = re.sub(r'</em>', '</i>', content, flags=re.IGNORECASE)
        content = re.sub(r'<br\s*/?>', '<br/>', content, flags=re.IGNORECASE)
        content = re.sub(r'<(?!/?[biu]>|br/>)[^>]+>', '', content)
        content = content.strip()
        
        if content:
            flowables.append(Paragraph(content, base_style))
            flowables.append(Spacer(1, 6))
    
    return flowables
