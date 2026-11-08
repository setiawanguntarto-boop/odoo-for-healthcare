# -*- coding: utf-8 -*-
"""Generate ultra-clean, minimalist flat-design app icons for Klinik ADERA ERP (Odoo 19 CE)
Specifications matching official Odoo 19 flat aesthetic (like Invoicing, Discuss, Point of Sale):
- Style: Solid vibrant squircle (rounded-square) background, pure white bold geometric glyphs.
- Resolution: Supersampled at 1024x1024 and downsampled with Lanczos to 256x256 RGBA.
- Visual Simplicity: Highly abstract, bold, thick shapes with instant legibility at 72x72 / 48x48.

Icons Generated:
1. EHR Bridge:
   - Background: Solid rich teal (#00897B)
   - Glyph: Bold medical cross in center, flanked by clean synchronized data curved arrows + subtle bridge base.
2. Akuntansi & Keuangan:
   - Background: Solid emerald green (#2E7D32)
   - Glyph: Minimalist geometric balance scale merging with a rising growth bar chart.
3. Remunerasi Dokter:
   - Background: Solid royal indigo blue (#1A237E)
   - Glyph: Bold stylized stethoscope looped around an abstract merit / payout split symbol.
"""

from PIL import Image, ImageDraw


def create_canvas(s=1024):
    return Image.new("RGBA", (s, s), (0, 0, 0, 0))


def draw_squircle(draw, s, fill_color, margin=64, radius=210):
    """Draws a smooth squircle container."""
    draw.rounded_rectangle(
        (margin, margin, s - margin, s - margin),
        radius=radius,
        fill=fill_color
    )


def generate_ehr_bridge_icon():
    """Icon 1: EHR Bridge
    Vibrant Teal squircle (#00897B), pure white bold medical cross + dual sync bridge glyph.
    """
    S = 1024
    im = create_canvas(S)
    draw = ImageDraw.Draw(im)

    # 1. Background Squircle
    teal = (0, 137, 123, 255)  # #00897B Teal
    draw_squircle(draw, S, teal)

    white = (255, 255, 255, 255)
    cx, cy = S // 2, S // 2

    # 2. Bold Central Medical Cross
    # Thicker, bolder proportions
    cw = 110  # bar width
    cl = 340  # bar length
    # Vertical bar
    draw.rounded_rectangle((cx - cw // 2, cy - cl // 2 - 20, cx + cw // 2, cy + cl // 2 - 20), radius=28, fill=white)
    # Horizontal bar
    draw.rounded_rectangle((cx - cl // 2, cy - cw // 2 - 20, cx + cl // 2, cy + cw // 2 - 20), radius=28, fill=white)

    # 3. Flanking Synchronization Flow Arcs (Thick, Clean, Bold)
    arc_thick = 48

    # Left Sync Curve (flanking left, curved upward)
    left_arc_bbox = (cx - 360, cy - 240, cx - 120, cy + 200)
    draw.arc(left_arc_bbox, start=110, end=250, fill=white, width=arc_thick)
    # Top-pointing bold arrowhead on left
    ax1, ay1 = cx - 220, cy - 190
    draw.polygon([(ax1, ay1 - 44), (ax1 + 54, ay1 + 10), (ax1 - 20, ay1 + 36)], fill=white)

    # Right Sync Curve (flanking right, curved downward)
    right_arc_bbox = (cx + 120, cy - 200, cx + 360, cy + 240)
    draw.arc(right_arc_bbox, start=290, end=70, fill=white, width=arc_thick)
    # Bottom-pointing bold arrowhead on right
    ax2, ay2 = cx + 220, cy + 190
    draw.polygon([(ax2, ay2 + 44), (ax2 - 54, ay2 - 10), (ax2 + 20, ay2 - 36)], fill=white)

    # 4. Subtle Solid Data Bridge Bar at the bottom
    bridge_w = 460
    bridge_h = 44
    bridge_y = cy + 250
    draw.rounded_rectangle(
        (cx - bridge_w // 2, bridge_y, cx + bridge_w // 2, bridge_y + bridge_h),
        radius=22,
        fill=white
    )

    return im.resize((256, 256), Image.Resampling.LANCZOS)


def generate_akuntansi_icon():
    """Icon 2: Akuntansi & Keuangan
    Vibrant Emerald Green (#2E7D32), minimalist bold balance scale + rising growth bar chart.
    """
    S = 1024
    im = create_canvas(S)
    draw = ImageDraw.Draw(im)

    # 1. Background Squircle
    green = (46, 125, 50, 255)  # #2E7D32 Forest / Emerald Green
    draw_squircle(draw, S, green)

    white = (255, 255, 255, 255)
    cx, cy = S // 2, S // 2

    # 2. Central Fulcrum Pillar & Base
    # Sturdy solid geometric pillar
    pillar_w = 64
    draw.rounded_rectangle((cx - pillar_w // 2, cy - 170, cx + pillar_w // 2, cy + 240), radius=20, fill=white)
    # Bottom Base
    base_w = 460
    base_h = 50
    draw.rounded_rectangle((cx - base_w // 2, cy + 220, cx + base_w // 2, cy + 220 + base_h), radius=22, fill=white)

    # Fulcrum Top Pivot
    draw.ellipse((cx - 56, cy - 210, cx + 56, cy - 98), fill=white)

    # 3. Horizontal Balance Beam (Slightly tilted upward on right to show positive growth)
    beam_w = 560
    beam_h = 48
    draw.rounded_rectangle((cx - beam_w // 2, cy - 140, cx + beam_w // 2, cy - 140 + beam_h), radius=20, fill=white)

    # 4. Left Scale: Solid Traditional Pan
    left_x = cx - 210
    pan_y = cy + 30
    # Left vertical ropes
    draw.line([(left_x, cy - 110), (left_x - 70, pan_y)], fill=white, width=24)
    draw.line([(left_x, cy - 110), (left_x + 70, pan_y)], fill=white, width=24)
    # Left Bowl / Pan
    draw.chord((left_x - 100, pan_y - 20, left_x + 100, pan_y + 80), start=0, end=180, fill=white)

    # 5. Right Scale: Merged with Rising Growth Bar Chart (3 ascending bars)
    right_x = cx + 210
    # Base platform for bars
    bar_base_y = cy + 80
    draw.rounded_rectangle((right_x - 90, bar_base_y, right_x + 90, bar_base_y + 24), radius=12, fill=white)

    # Rope connecting to right platform
    draw.line([(right_x, cy - 110), (right_x, bar_base_y)], fill=white, width=24)

    # 3 Bold Ascending Bars (representing financial growth & PSAK)
    bar_w = 38
    # Bar 1 (Short)
    draw.rounded_rectangle((right_x - 70, bar_base_y - 80, right_x - 70 + bar_w, bar_base_y), radius=12, fill=white)
    # Bar 2 (Medium)
    draw.rounded_rectangle((right_x - 19, bar_base_y - 140, right_x - 19 + bar_w, bar_base_y), radius=12, fill=white)
    # Bar 3 (Tall + Growth Arrow)
    draw.rounded_rectangle((right_x + 32, bar_base_y - 200, right_x + 32 + bar_w, bar_base_y), radius=12, fill=white)

    # Growth Arrow Head pointing up-right above Bar 3
    ax, ay = right_x + 51, bar_base_y - 225
    draw.polygon([(ax, ay - 38), (ax + 38, ay + 6), (ax - 38, ay + 6)], fill=white)

    return im.resize((256, 256), Image.Resampling.LANCZOS)


def generate_remunerasi_icon():
    """Icon 3: Remunerasi Dokter
    Deep Indigo/Royal Blue (#1A237E), bold flat stethoscope looped around abstract fee-split/payout badge.
    """
    S = 1024
    im = create_canvas(S)
    draw = ImageDraw.Draw(im)

    # 1. Background Squircle
    deep_blue = (26, 35, 126, 255)  # #1A237E Royal Indigo
    draw_squircle(draw, S, deep_blue)

    white = (255, 255, 255, 255)
    cx, cy = S // 2, S // 2

    # 2. Bold Stethoscope Top Binaural U-Tube
    thick = 48

    # Left earpiece & tip
    draw.rounded_rectangle((cx - 240, cy - 250, cx - 200, cy - 140), radius=20, fill=white)
    draw.ellipse((cx - 255, cy - 280, cx - 185, cy - 220), fill=white)

    # Right earpiece & tip
    draw.rounded_rectangle((cx + 200, cy - 250, cx + 240, cy - 140), radius=20, fill=white)
    draw.ellipse((cx + 185, cy - 280, cx + 255, cy - 220), fill=white)

    # Binaural U-curves meeting at center Y-stem
    draw.arc((cx - 220, cy - 210, cx, cy - 10), start=90, end=180, fill=white, width=thick)
    draw.arc((cx, cy - 210, cx + 220, cy - 10), start=0, end=90, fill=white, width=thick)

    # Y-connector stem
    draw.rounded_rectangle((cx - thick // 2, cy - 30, cx + thick // 2, cy + 60), radius=20, fill=white)

    # 3. Flexible Tube Looping Around the Payout Badge
    loop_box = (cx - 260, cy - 20, cx + 260, cy + 340)
    draw.arc(loop_box, start=30, end=330, fill=white, width=thick)

    # Chestpiece / Diaphragm (Bottom right)
    chest_x, chest_y = cx + 195, cy + 245
    draw.ellipse((chest_x - 65, chest_y - 65, chest_x + 65, chest_y + 65), fill=white)
    draw.ellipse((chest_x - 40, chest_y - 40, chest_x + 40, chest_y + 40), fill=deep_blue)
    draw.ellipse((chest_x - 20, chest_y - 20, chest_x + 20, chest_y + 20), fill=white)

    # 4. Centerpiece: Bold Minimalist Payout / Fee-Split (%) Symbol
    # Stylized thick percentage with solid geometric clarity
    # Diagonal division slash
    draw.line([(cx + 80, cy + 40), (cx - 110, cy + 210)], fill=white, width=50)

    # Top-left circle (Doctor Potion)
    dot_r = 44
    draw.ellipse((cx - 85 - dot_r, cy + 50 - dot_r, cx - 85 + dot_r, cy + 50 + dot_r), fill=white)
    draw.ellipse((cx - 85 - 20, cy + 50 - 20, cx - 85 + 20, cy + 50 + 20), fill=deep_blue)

    # Bottom-right circle (Clinic Potion)
    draw.ellipse((cx + 55 - dot_r, cy + 200 - dot_r, cx + 55 + dot_r, cy + 200 + dot_r), fill=white)
    draw.ellipse((cx + 55 - 20, cy + 200 - 20, cx + 55 + 20, cy + 200 + 20), fill=deep_blue)

    return im.resize((256, 256), Image.Resampling.LANCZOS)


def generate_showcase_canvas():
    """Generates the unified side-by-side showcase row on #F5F1FB background
    matching Odoo Discuss / Dashboards / Invoicing layout.
    """
    W = 1200
    H = 460
    showcase = Image.new("RGBA", (W, H), (245, 241, 251, 255))  # #F5F1FB lavender tint
    draw = ImageDraw.Draw(showcase)

    # Icon centers
    xs = [240, 600, 960]
    y_icon = 180

    im_ehr = generate_ehr_bridge_icon()
    im_acc = generate_akuntansi_icon()
    im_doc = generate_remunerasi_icon()

    icons = [
        (im_ehr, "EHR Bridge", xs[0]),
        (im_acc, "Akuntansi & Keu...", xs[1]),
        (im_doc, "Remunerasi Dokter", xs[2]),
    ]

    for im, label, cx in icons:
        # 1. Soft Drop Shadow behind icon
        shadow = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle((10, 10, 246, 246), radius=55, fill=(40, 20, 80, 45))
        # Paste shadow offset
        showcase.paste(shadow, (cx - 128, y_icon - 128 + 14), shadow)

        # 2. Paste Icon
        showcase.paste(im, (cx - 128, y_icon - 128), im)

        # 3. Label below
        # Simple aesthetic text placeholder or clean lines
        text_bbox = draw.textbbox((0, 0), label)
        tw = text_bbox[2] - text_bbox[0]
        th = text_bbox[3] - text_bbox[1]
        draw.text((cx - tw // 2, y_icon + 145), label, fill=(45, 40, 60, 255))

    return showcase


if __name__ == "__main__":
    import os

    # Dynamically find addons base directory
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    ehr_path = os.path.join(base_dir, "adera_clinic_bridge", "static", "description", "icon.png")
    acc_path = os.path.join(base_dir, "adera_accounting", "static", "description", "icon.png")
    doc_path = os.path.join(base_dir, "adera_doctor_remuneration", "static", "description", "icon.png")

    generate_ehr_bridge_icon().save(ehr_path)
    print(f"Saved: {ehr_path}")

    generate_akuntansi_icon().save(acc_path)
    print(f"Saved: {acc_path}")

    generate_remunerasi_icon().save(doc_path)
    print(f"Saved: {doc_path}")

    # Generate the showcase banner
    artifact_dir = "C:/Users/ASUS/.gemini/antigravity/brain/94d7ff11-1e58-4b18-bd19-a6a19c07fa00"
    if os.path.exists(artifact_dir):
        showcase_path = os.path.join(artifact_dir, "adera_app_icons_showcase.png")
        generate_showcase_canvas().save(showcase_path)
        print(f"Saved showcase: {showcase_path}")
