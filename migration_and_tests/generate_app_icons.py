# -*- coding: utf-8 -*-
"""Generate high-resolution, pixel-perfect flat-design app icons for Klinik ADERA ERP
Following standard Odoo 19 minimalism:
- Canvas: 256x256 RGBA (supersampled at 1024x1024 for pristine antialiasing)
- Bounding Box: 8% margin rounded-square container (radius ~22%)
- Vector Glyphs: Crisp, minimalist white high-contrast icons
"""
import math
from PIL import Image, ImageDraw, ImagePath


def create_base_canvas(size_hi):
    return Image.new("RGBA", (size_hi, size_hi), (0, 0, 0, 0))


def draw_rounded_rect(draw, bbox, radius, fill_color):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill_color)


def generate_ehr_bridge_icon():
    """1. EHR Bridge Icon:
       Background: Vibrant Teal / Cyan (#0D9488 to #0891B2)
       Glyph: EHR Clinical Document with Medical Cross + Dual Sync Data Transfer Bridge Arrows
    """
    S = 1024
    im = create_base_canvas(S)
    draw = ImageDraw.Draw(im)

    # 1. Background Rounded Square (8% margin -> 82px to 942px, radius 210px)
    pad = 82
    radius = 210
    # Gradient or solid teal-cyan
    teal_bg = (13, 148, 136, 255)  # #0D9488 Vibrant Teal
    draw_rounded_rect(draw, (pad, pad, S - pad, S - pad), radius, teal_bg)

    # Subtle modern top-light highlight
    for i in range(12):
        alpha = int(25 * (1 - i / 12))
        highlight_color = (255, 255, 255, alpha)
        draw.rounded_rectangle(
            (pad + i * 2, pad + i * 2, S - pad - i * 2, pad + 380 - i * 15),
            radius=max(radius - i * 2, 10),
            fill=highlight_color
        )

    # Re-fill main shape slightly to blend
    # 2. White Minimalist Vector Glyph:
    # A central EHR medical tablet/card with a prominent cross + bidirectional data transfer bridge arrows
    cx, cy = S // 2, S // 2
    white = (255, 255, 255, 255)

    # Central EHR Card / Document
    cw, ch = 340, 440
    card_bbox = (cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2)
    draw.rounded_rectangle(card_bbox, radius=52, fill=white)

    # Cutout Teal Medical Cross inside EHR Document
    cross_w = 72
    cross_len = 200
    # Vertical cross bar
    draw.rounded_rectangle(
        (cx - cross_w // 2, cy - cross_len // 2 - 20, cx + cross_w // 2, cy + cross_len // 2 - 20),
        radius=20, fill=teal_bg
    )
    # Horizontal cross bar
    draw.rounded_rectangle(
        (cx - cross_len // 2, cy - cross_w // 2 - 20, cx + cross_len // 2, cy + cross_w // 2 - 20),
        radius=20, fill=teal_bg
    )
    # Bottom pulse line / data lines on the card
    draw.rounded_rectangle((cx - 100, cy + 120, cx + 100, cy + 144), radius=12, fill=teal_bg)
    draw.rounded_rectangle((cx - 60, cy + 160, cx + 60, cy + 180), radius=10, fill=teal_bg)

    # Data Bridge Curved Transfer Arrows (Left to Right / Interoperability Stream)
    # Top right flowing arrow
    arrow_color = (255, 255, 255, 255)
    thick = 36

    # Left looping data pulse bridge
    # Draw Left Arrow Arc
    arc_box_left = (cx - 360, cy - 240, cx - 120, cy + 240)
    draw.arc(arc_box_left, start=120, end=260, fill=arrow_color, width=thick)
    # Left arrow head pointing up-right
    ax1, ay1 = cx - 180, cy - 190
    draw.polygon([(ax1, ay1 - 36), (ax1 + 50, ay1), (ax1 - 10, ay1 + 40)], fill=arrow_color)

    # Right looping data pulse bridge
    arc_box_right = (cx + 120, cy - 240, cx + 360, cy + 240)
    draw.arc(arc_box_right, start=300, end=80, fill=arrow_color, width=thick)
    # Right arrow head pointing down-left
    ax2, ay2 = cx + 180, cy + 190
    draw.polygon([(ax2, ay2 + 36), (ax2 - 50, ay2), (ax2 + 10, ay2 - 40)], fill=arrow_color)

    # 4 Data Transfer Nodes (Glowing Dots)
    nodes = [
        (cx - 330, cy - 30),
        (cx - 320, cy + 80),
        (cx + 330, cy + 30),
        (cx + 320, cy - 80),
    ]
    for nx, ny in nodes:
        draw.ellipse((nx - 22, ny - 22, nx + 22, ny + 22), fill=arrow_color)

    # Downsample to 256x256 with Lanczos
    return im.resize((256, 256), Image.Resampling.LANCZOS)


def generate_psak_accounting_icon():
    """2. Akuntansi & Keuangan PSAK Icon:
       Background: Rich Emerald Green (#107C41 / #059669)
       Glyph: Classic Balance Scale + Upward Financial Growth Line
    """
    S = 1024
    im = create_base_canvas(S)
    draw = ImageDraw.Draw(im)

    pad = 82
    radius = 210
    green_bg = (16, 124, 65, 255)  # #107C41 Rich Emerald Green
    draw_rounded_rect(draw, (pad, pad, S - pad, S - pad), radius, green_bg)

    # Subtle modern top highlight
    for i in range(12):
        alpha = int(25 * (1 - i / 12))
        draw.rounded_rectangle(
            (pad + i * 2, pad + i * 2, S - pad - i * 2, pad + 380 - i * 15),
            radius=max(radius - i * 2, 10),
            fill=(255, 255, 255, alpha)
        )

    cx, cy = S // 2, S // 2 + 10
    white = (255, 255, 255, 255)

    # Financial Growth Chart / Trend Bars in the Background
    bar_w = 48
    bars = [
        (cx - 260, cy + 160, cx - 260 + bar_w, cy + 240),
        (cx - 180, cy + 100, cx - 180 + bar_w, cy + 240),
        (cx + 132, cy + 20, cx + 132 + bar_w, cy + 240),
        (cx + 212, cy - 60, cx + 212 + bar_w, cy + 240),
    ]
    for b in bars:
        draw.rounded_rectangle(b, radius=16, fill=(255, 255, 255, 140))

    # Upward Growth Arrow Trendline behind the scale
    trend_pts = [
        (cx - 280, cy + 130),
        (cx - 160, cy + 70),
        (cx - 30, cy + 20),
        (cx + 110, cy - 50),
        (cx + 250, cy - 140),
    ]
    draw.line(trend_pts, fill=(255, 255, 255, 200), width=28)
    # Arrow head
    draw.polygon([(cx + 275, cy - 190), (cx + 290, cy - 110), (cx + 215, cy - 125)], fill=(255, 255, 255, 230))

    # Classic Balance Scale (Neraca Keuangan Double-Entry PSAK)
    # Center Pillar
    draw.rounded_rectangle((cx - 24, cy - 200, cx + 24, cy + 240), radius=14, fill=white)
    # Pillar Base
    draw.rounded_rectangle((cx - 140, cy + 230, cx + 140, cy + 276), radius=20, fill=white)
    # Pillar Top Finial
    draw.ellipse((cx - 42, cy - 240, cx + 42, cy - 156), fill=white)

    # Horizontal Balance Beam
    beam_w = 520
    beam_h = 32
    beam_y = cy - 120
    draw.rounded_rectangle((cx - beam_w // 2, beam_y, cx + beam_w // 2, beam_y + beam_h), radius=16, fill=white)

    # Scale Strings & Pans (Left & Right)
    left_x = cx - 200
    right_x = cx + 200
    pan_y = cy + 40
    pan_radius = 120

    # Left strings
    draw.line([(left_x, beam_y + beam_h), (left_x - 80, pan_y)], fill=white, width=16)
    draw.line([(left_x, beam_y + beam_h), (left_x + 80, pan_y)], fill=white, width=16)
    # Left Pan
    draw.chord((left_x - pan_radius, pan_y - 20, left_x + pan_radius, pan_y + 80), start=0, end=180, fill=white)

    # Right strings
    draw.line([(right_x, beam_y + beam_h), (right_x - 80, pan_y)], fill=white, width=16)
    draw.line([(right_x, beam_y + beam_h), (right_x + 80, pan_y)], fill=white, width=16)
    # Right Pan
    draw.chord((right_x - pan_radius, pan_y - 20, right_x + pan_radius, pan_y + 80), start=0, end=180, fill=white)

    return im.resize((256, 256), Image.Resampling.LANCZOS)


def generate_doctor_remuneration_icon():
    """3. Remunerasi Dokter Icon:
       Background: Deep Royal Blue / Indigo (#3949AB / #1E40AF)
       Glyph: Stethoscope Intertwined with Fee Split / Currency % Shield
    """
    S = 1024
    im = create_base_canvas(S)
    draw = ImageDraw.Draw(im)

    pad = 82
    radius = 210
    indigo_bg = (57, 73, 171, 255)  # #3949AB Royal Indigo
    draw_rounded_rect(draw, (pad, pad, S - pad, S - pad), radius, indigo_bg)

    # Top highlight
    for i in range(12):
        alpha = int(25 * (1 - i / 12))
        draw.rounded_rectangle(
            (pad + i * 2, pad + i * 2, S - pad - i * 2, pad + 380 - i * 15),
            radius=max(radius - i * 2, 10),
            fill=(255, 255, 255, alpha)
        )

    cx, cy = S // 2, S // 2 - 10
    white = (255, 255, 255, 255)

    # 1. Stethoscope Earpieces (Top Arcs)
    tube_thick = 34

    # Left earpiece
    draw.rounded_rectangle((cx - 240, cy - 240, cx - 210, cy - 140), radius=14, fill=white)
    # Left ear tip
    draw.ellipse((cx - 250, cy - 265, cx - 200, cy - 215), fill=white)

    # Right earpiece
    draw.rounded_rectangle((cx + 210, cy - 240, cx + 240, cy - 140), radius=14, fill=white)
    # Right ear tip
    draw.ellipse((cx + 200, cy - 265, cx + 250, cy - 215), fill=white)

    # Binaural U-tube curves
    draw.arc((cx - 230, cy - 200, cx, cy - 20), start=90, end=180, fill=white, width=tube_thick)
    draw.arc((cx, cy - 200, cx + 230, cy - 20), start=0, end=90, fill=white, width=tube_thick)

    # Y-connector stem
    draw.rounded_rectangle((cx - tube_thick // 2, cy - 40, cx + tube_thick // 2, cy + 60), radius=16, fill=white)

    # Main flexible tube looping in a circle around the central badge
    loop_box = (cx - 270, cy - 20, cx + 270, cy + 320)
    draw.arc(loop_box, start=30, end=330, fill=white, width=tube_thick)

    # Chestpiece / Diaphragm (Bottom right)
    chest_x, chest_y = cx + 200, cy + 220
    draw.ellipse((chest_x - 55, chest_y - 55, chest_x + 55, chest_y + 55), fill=white)
    draw.ellipse((chest_x - 35, chest_y - 35, chest_x + 35, chest_y + 35), fill=indigo_bg)
    draw.ellipse((chest_x - 18, chest_y - 18, chest_x + 18, chest_y + 18), fill=white)

    # 2. Central Fee Split & Merit Badge (Percentage / Currency Split inside)
    # Stylized Fee Split Percentage Symbol in the Center
    # Top-left circle of %
    dot_r = 38
    draw.ellipse((cx - 100 - dot_r, cy + 40 - dot_r, cx - 100 + dot_r, cy + 40 + dot_r), fill=white)
    draw.ellipse((cx - 100 - 18, cy + 40 - 18, cx - 100 + 18, cy + 40 + 18), fill=indigo_bg)

    # Bottom-right circle of %
    draw.ellipse((cx + 40 - dot_r, cy + 180 - dot_r, cx + 40 + dot_r, cy + 180 + dot_r), fill=white)
    draw.ellipse((cx + 40 - 18, cy + 180 - 18, cx + 40 + 18, cy + 180 + 18), fill=indigo_bg)

    # Diagonal Split Slash Bar
    draw.line([(cx + 80, cy + 30), (cx - 140, cy + 190)], fill=white, width=38)

    # Small Medical Cross inside top circle
    cross_sz = 14
    draw.line([(cx - 100 - cross_sz, cy + 40), (cx - 100 + cross_sz, cy + 40)], fill=white, width=8)
    draw.line([(cx - 100, cy + 40 - cross_sz), (cx - 100, cy + 40 + cross_sz)], fill=white, width=8)

    return im.resize((256, 256), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    im_ehr = generate_ehr_bridge_icon()
    im_ehr.save("c:/odoo/my_custom_addons/adera_clinic_bridge/static/description/icon.png")
    print("Saved EHR Bridge icon")

    im_acc = generate_psak_accounting_icon()
    im_acc.save("c:/odoo/my_custom_addons/adera_accounting/static/description/icon.png")
    print("Saved PSAK Accounting icon")

    im_doc = generate_doctor_remuneration_icon()
    im_doc.save("c:/odoo/my_custom_addons/adera_doctor_remuneration/static/description/icon.png")
    print("Saved Doctor Remuneration icon")

