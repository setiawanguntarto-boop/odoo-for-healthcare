# -*- coding: utf-8 -*-
"""
Generate standardized enterprise squircle icons for Klinik ADERA ERP (Odoo 19 CE)
Using PIL/Pillow with RGBA anti-aliased rendering, 135-degree duotone gradients,
continuous squircle paths, subtle bottom elevation shadows, and sharp crisp white glyphs.
"""

import math
from PIL import Image, ImageDraw, ImageFilter

CANVAS_SIZE = 512
PADDING = 32
CORNER_RADIUS = 112  # Squircle ~22% curvature on 512px canvas
SHADOW_OFFSET = 12
SHADOW_BLUR = 24


def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))


def interpolate_color(c1, c2, factor):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * factor) for i in range(3))


def create_base_squircle(start_hex, end_hex):
    # Oversampled canvas for super-sampling anti-aliasing (2x)
    scale = 2
    size = CANVAS_SIZE * scale
    pad = PADDING * scale
    radius = CORNER_RADIUS * scale
    
    # 1. Base gradient image
    c_start = hex_to_rgb(start_hex)
    c_end = hex_to_rgb(end_hex)
    
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    
    # Linear gradient at 135 degrees (from top-left to bottom-right)
    for y in range(size):
        for x in range(size):
            # Normalized diagonal projection: 0.0 at (0,0) to 1.0 at (size, size)
            t = (x + y) / (2.0 * size)
            color = interpolate_color(c_start, c_end, t)
            grad_draw.point((x, y), fill=(*color, 255))
            
    # 2. Mask for rounded squircle
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    x0, y0 = pad, pad
    x1, y1 = size - pad, size - pad
    mask_draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=255)
    
    # Apply mask
    squircle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    squircle.paste(grad, (0, 0), mask=mask)
    
    # Downsample to target CANVAS_SIZE with high quality Lanczos filter
    final_squircle = squircle.resize((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.LANCZOS)
    
    # 3. Create Elevation Drop Shadow
    shadow_mask = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), 0)
    s_draw = ImageDraw.Draw(shadow_mask)
    s_pad = PADDING
    s_radius = CORNER_RADIUS
    s_draw.rounded_rectangle(
        [s_pad, s_pad + SHADOW_OFFSET, CANVAS_SIZE - s_pad, CANVAS_SIZE - s_pad + SHADOW_OFFSET],
        radius=s_radius,
        fill=140  # Shadow intensity
    )
    shadow_blur = shadow_mask.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    # Paste shadow with black color and blurred alpha
    black_shadow = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    black_shadow.paste((0, 0, 0, 60), (0, 0), mask=shadow_blur)
    canvas.alpha_composite(black_shadow)
    canvas.alpha_composite(final_squircle)
    
    return canvas


def draw_glyph_shadow(draw, fn, *args, **kwargs):
    """Draw subtle 2px downward drop-shadow for glyph."""
    kwargs_shadow = kwargs.copy()
    if 'fill' in kwargs_shadow:
        kwargs_shadow['fill'] = (0, 0, 0, 45)
    if 'outline' in kwargs_shadow:
        kwargs_shadow['outline'] = (0, 0, 0, 45)
    # Apply +2y offset
    fn(draw, offset_y=3, *args, **kwargs_shadow)
    fn(draw, offset_y=0, *args, **kwargs)


def generate_accounting_icon(output_path):
    """1. Akuntansi & Keuangan: Balance Scale & Minimalist Ledger Book (#10B981 -> #047857)"""
    img = create_base_squircle("#10B981", "#047857")
    draw = ImageDraw.Draw(img)
    cx, cy = 256, 256
    
    # Draw Balance Scale & Financial Columns
    white = (255, 255, 255, 255)
    shadow = (0, 0, 0, 40)
    
    for dy, col in [(3, shadow), (0, white)]:
        # Central pillar
        draw.rounded_rectangle([cx - 8, cy - 80 + dy, cx + 8, cy + 90 + dy], radius=4, fill=col)
        # Base platform
        draw.rounded_rectangle([cx - 80, cy + 85 + dy, cx + 80, cy + 105 + dy], radius=6, fill=col)
        # Top beam
        draw.rounded_rectangle([cx - 100, cy - 70 + dy, cx + 100, cy - 58 + dy], radius=5, fill=col)
        # Center dome/pivot
        draw.ellipse([cx - 16, cy - 90 + dy, cx + 16, cy - 62 + dy], fill=col)
        
        # Left Scale strings & Pan
        draw.line([cx - 90, cy - 58 + dy, cx - 120, cy - 10 + dy], fill=col, width=4)
        draw.line([cx - 90, cy - 58 + dy, cx - 60, cy - 10 + dy], fill=col, width=4)
        draw.arc([cx - 130, cy - 35 + dy, cx - 50, cy + 15 + dy], start=0, end=180, fill=col, width=6)
        draw.line([cx - 130, cy - 10 + dy, cx - 50, cy - 10 + dy], fill=col, width=6)
        
        # Right Scale strings & Pan
        draw.line([cx + 90, cy - 58 + dy, cx + 60, cy - 10 + dy], fill=col, width=4)
        draw.line([cx + 90, cy - 58 + dy, cx + 120, cy - 10 + dy], fill=col, width=4)
        draw.arc([cx + 50, cy - 35 + dy, cx + 130, cy + 15 + dy], start=0, end=180, fill=col, width=6)
        draw.line([cx + 50, cy - 10 + dy, cx + 130, cy - 10 + dy], fill=col, width=6)

    img.save(output_path, "PNG")
    print(f"[OK] Generated Accounting Icon: {output_path}")


def generate_doctor_remuneration_icon(output_path):
    """2. Remunerasi Dokter & PPh 21: Medical Stethoscope & Star / Shield (#8B5CF6 -> #4338CA)"""
    img = create_base_squircle("#8B5CF6", "#4338CA")
    draw = ImageDraw.Draw(img)
    cx, cy = 256, 256
    
    white = (255, 255, 255, 255)
    shadow = (0, 0, 0, 40)
    
    for dy, col in [(3, shadow), (0, white)]:
        # Stethoscope U-tube
        draw.arc([cx - 90, cy - 110 + dy, cx + 90, cy + 10 + dy], start=0, end=180, fill=col, width=12)
        # Left ear piece
        draw.line([cx - 90, cy - 105 + dy, cx - 90, cy - 60 + dy], fill=col, width=12)
        draw.ellipse([cx - 100, cy - 115 + dy, cx - 80, cy - 95 + dy], fill=col)
        # Right ear piece
        draw.line([cx + 90, cy - 105 + dy, cx + 90, cy - 60 + dy], fill=col, width=12)
        draw.ellipse([cx + 80, cy - 115 + dy, cx + 100, cy - 95 + dy], fill=col)
        
        # Center connector tube down
        draw.line([cx, cy + 10 + dy, cx, cy + 60 + dy], fill=col, width=12)
        # Chestpiece / Bell
        draw.ellipse([cx - 36, cy + 50 + dy, cx + 36, cy + 110 + dy], outline=col, width=10)
        draw.ellipse([cx - 16, cy + 70 + dy, cx + 16, cy + 90 + dy], fill=col)
        
        # Star Badge in Upper Center
        # 5-point star
        points = []
        for i in range(10):
            r = 28 if i % 2 == 0 else 12
            angle = i * math.pi / 5 - math.pi / 2
            points.append((cx + r * math.cos(angle), cy - 40 + dy + r * math.sin(angle)))
        draw.polygon(points, fill=col)

    img.save(output_path, "PNG")
    print(f"[OK] Generated Doctor Remuneration Icon: {output_path}")


def generate_approvals_icon(output_path):
    """3. Pusat Otorisasi: Hexagonal Security Shield with Double Verified Checkmark (#F43F5E -> #E11D48)"""
    img = create_base_squircle("#F43F5E", "#E11D48")
    draw = ImageDraw.Draw(img)
    cx, cy = 256, 256
    
    white = (255, 255, 255, 255)
    shadow = (0, 0, 0, 40)
    
    for dy, col in [(3, shadow), (0, white)]:
        # Modern Security Shield
        shield = [
            (cx, cy - 105 + dy),
            (cx + 95, cy - 65 + dy),
            (cx + 95, cy + 20 + dy),
            (cx, cy + 110 + dy),
            (cx - 95, cy + 20 + dy),
            (cx - 95, cy - 65 + dy),
        ]
        draw.polygon(shield, outline=col, width=12)
        
        # Verified Checkmark inside Shield
        # Stem 1 (down-right)
        draw.line([cx - 45, cy + 5 + dy, cx - 12, cy + 38 + dy], fill=col, width=16)
        # Stem 2 (up-right)
        draw.line([cx - 15, cy + 38 + dy, cx + 50, cy - 35 + dy], fill=col, width=16)
        
        # Rounded caps on checkmark
        draw.ellipse([cx - 52, cy - 2 + dy, cx - 38, cy + 12 + dy], fill=col)
        draw.ellipse([cx + 43, cy - 42 + dy, cx + 57, cy - 28 + dy], fill=col)
        draw.ellipse([cx - 20, cy + 30 + dy, cx - 4, cy + 46 + dy], fill=col)

    img.save(output_path, "PNG")
    print(f"[OK] Generated Approvals Hub Icon: {output_path}")


def generate_clinic_bridge_icon(output_path):
    """4. EHR Clinic Bridge: Hospital Cross with Real-Time Pulse / Waveform (#06B6D4 -> #0284C7)"""
    img = create_base_squircle("#06B6D4", "#0284C7")
    draw = ImageDraw.Draw(img)
    cx, cy = 256, 256
    
    white = (255, 255, 255, 255)
    shadow = (0, 0, 0, 40)
    
    for dy, col in [(3, shadow), (0, white)]:
        # Medical Cross Outline / Silhouette
        cross = [
            (cx - 30, cy - 95 + dy),
            (cx + 30, cy - 95 + dy),
            (cx + 30, cy - 35 + dy),
            (cx + 90, cy - 35 + dy),
            (cx + 90, cy + 35 + dy),
            (cx + 30, cy + 35 + dy),
            (cx + 30, cy + 95 + dy),
            (cx - 30, cy + 95 + dy),
            (cx - 30, cy + 35 + dy),
            (cx - 90, cy + 35 + dy),
            (cx - 90, cy - 35 + dy),
            (cx - 30, cy - 35 + dy),
        ]
        draw.polygon(cross, outline=col, width=10)
        
        # Real-time Webhook Pulse Waveform through center
        pulse = [
            (cx - 105, cy + dy),
            (cx - 45, cy + dy),
            (cx - 25, cy - 45 + dy),
            (cx + 5, cy + 50 + dy),
            (cx + 25, cy - 25 + dy),
            (cx + 45, cy + dy),
            (cx + 105, cy + dy),
        ]
        draw.line(pulse, fill=col, width=10, joint="curve")

    img.save(output_path, "PNG")
    print(f"[OK] Generated Clinic Bridge Icon: {output_path}")


def generate_clinic_core_icon(output_path):
    """5. Klinik Core System: Medical Clinic Building with Caduceus Emblem (#3B82F6 -> #1E3A8A)"""
    img = create_base_squircle("#3B82F6", "#1E3A8A")
    draw = ImageDraw.Draw(img)
    cx, cy = 256, 256
    
    white = (255, 255, 255, 255)
    shadow = (0, 0, 0, 40)
    
    for dy, col in [(3, shadow), (0, white)]:
        # Clinic Building Roof (Pediment/Triangle)
        roof = [
            (cx, cy - 100 + dy),
            (cx + 100, cy - 45 + dy),
            (cx - 100, cy - 45 + dy),
        ]
        draw.polygon(roof, fill=col)
        
        # Top entablature
        draw.rounded_rectangle([cx - 95, cy - 45 + dy, cx + 95, cy - 30 + dy], radius=3, fill=col)
        
        # 4 Pillars of Healthcare Governance
        pillar_xs = [cx - 80, cx - 30, cx + 20, cx + 70]
        for px in pillar_xs:
            draw.rounded_rectangle([px, cy - 25 + dy, px + 12, cy + 70 + dy], radius=3, fill=col)
            
        # Foundation steps
        draw.rounded_rectangle([cx - 105, cy + 70 + dy, cx + 105, cy + 85 + dy], radius=4, fill=col)
        draw.rounded_rectangle([cx - 115, cy + 85 + dy, cx + 115, cy + 100 + dy], radius=4, fill=col)
        
        # Center Caduceus / Medical Cross in Pediment
        draw.rectangle([cx - 4, cy - 80 + dy, cx + 4, cy - 60 + dy], fill=(*hex_to_rgb("#3B82F6"), 255))
        draw.rectangle([cx - 14, cy - 74 + dy, cx + 14, cy - 66 + dy], fill=(*hex_to_rgb("#3B82F6"), 255))

    img.save(output_path, "PNG")
    print(f"[OK] Generated Clinic Core Icon: {output_path}")


if __name__ == '__main__':
    generate_accounting_icon("/mnt/extra-addons/adera_accounting/static/description/icon.png")
    generate_doctor_remuneration_icon("/mnt/extra-addons/adera_doctor_remuneration/static/description/icon.png")
    generate_approvals_icon("/mnt/extra-addons/adera_approvals/static/description/icon.png")
    generate_clinic_bridge_icon("/mnt/extra-addons/adera_clinic_bridge/static/description/icon.png")
    generate_clinic_core_icon("/mnt/extra-addons/adera_core/static/description/icon.png")
    print("\nALL 5 ENTERPRISE SQUIRCLE ICONS CREATED SUCCESSFULLY!")

