#!/usr/bin/env python3
"""
Cashflow Advisor Skill Demo Video
Generative ASCII video showing the cash flow report building up terminal-style.
"""

import os
import sys
import math
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import subprocess

# ─── CONFIG ──────────────────────────────────────────────────────────
VW, VH = 1280, 720          # 720p landscape
FPS = 24
DURATION = 30.0             # seconds
N_FRAMES = int(DURATION * FPS)
WORKDIR = r"C:\Users\MSI\AppData\Local\hermes\skills\cashflow-advisor"
OUTPUT_MP4 = os.path.join(WORKDIR, "cashflow_demo.mp4")
FONT_SIZE = 14

# Palette — financial terminal aesthetic
BG_DARK = (8, 12, 16)
FG_GREEN = (0, 255, 100)
FG_AMBER = (255, 180, 0)
FG_RED = (255, 60, 60)
FG_CYAN = (0, 220, 255)
FG_WHITE = (220, 230, 240)
FG_DIM = (80, 90, 100)
FG_BLUE = (80, 160, 255)
FG_ORANGE = (255, 140, 0)
FG_PURPLE = (180, 100, 255)

# Characters for different elements
CHAR_BLOCK_FULL = '█'
CHAR_BLOCK_3 = '▓'
CHAR_BLOCK_2 = '▒'
CHAR_BLOCK_1 = '░'
CHAR_VLINE = '│'
CHAR_HLINE = '─'
CHAR_TL = '┌'
CHAR_TR = '┐'
CHAR_BL = '└'
CHAR_BR = '┘'
CHAR_TL_CROSS = '├'
CHAR_TR_CROSS = '┤'
CHAR_BL_CROSS = '┴'
CHAR_BR_CROSS = '┬'
CHAR_CROSS = '┼'
CHAR_ARROW_UP = '▲'
CHAR_ARROW_DOWN = '▼'
CHAR_ARROW_RIGHT = '▶'
CHAR_DOLLAR = '$'
CHAR_PERCENT = '%'
CHAR_BULLET = '●'
CHAR_CIRCLE = '○'
CHAR_SQUARE = '■'
CHAR_DIAMOND = '◆'
CHAR_STAR = '★'
CHAR_SPARK = '✦'

# ─── FONT SETUP ──────────────────────────────────────────────────────
def get_font(size=FONT_SIZE):
    """Find a monospace font on Windows."""
    font_paths = [
        r"C:\Windows\Fonts\consola.ttf",      # Consolas
        r"C:\Windows\Fonts\cour.ttf",          # Courier New
        r"C:\Windows\Fonts\lucon.ttf",         # Lucida Console
        r"C:\Windows\Fonts\CascadiaCode.ttf",  # Cascadia Code
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

FONT = get_font(FONT_SIZE)
BOLD_FONT = get_font(FONT_SIZE)  # Will use same, bold via draw

# Character cell dimensions
bbox = FONT.getbbox('M')
CW = bbox[2] - bbox[0]
CH = FONT.getmetrics()[0] + FONT.getmetrics()[1]
COLS = VW // CW
ROWS = VH // CH
OX = (VW - COLS * CW) // 2
OY = (VH - ROWS * CH) // 2

print(f"Grid: {COLS}x{ROWS}, Cell: {CW}x{CH}, Offset: ({OX}, {OY})")

# ─── DATA FROM CASH FLOW REPORT ──────────────────────────────────────
REPORT_DATA = {
    "date": "2026-06-29",
    "available": 12500,
    "pending": 22000,
    "expenses": [
        ("AWS / Infrastructure", 3200, 2, True),
        ("Payroll — Bi-weekly", 28000, 3, True),
        ("SaaS Tools", 850, 5, True),
        ("Office Rent", 4500, 7, True),
        ("Annual Cyber Insurance", 7000, 12, False),
        ("Payroll — Bi-weekly", 28000, 17, True),
    ],
    "inflows": [
        ("2026-07-01", 3500, "Professional Services — June"),
        ("2026-07-03", 22000, "Stripe payout"),
        ("2026-07-07", 15000, "Q2 Enterprise License — Nakatomi Corp"),
        ("2026-07-13", 1499, "Delayed collection (est. 50%)"),
        ("2026-07-17", 2999, "Subscription renewal"),
        ("2026-07-20", 2999, "Subscription renewal"),
        ("2026-07-21", 1499, "Subscription renewal"),
        ("2026-07-23", 1499, "Subscription renewal"),
        ("2026-07-26", 4999, "Subscription renewal"),
    ],
    "gaps": [
        ("2026-07-02", -15200, "Payroll — Bi-weekly"),
        ("2026-07-16", -17050, "Payroll — Bi-weekly"),
    ],
    "options": [
        ("INSTANT_PAYOUT", "Stripe instant payout", 330, "COVERS GAP", "stripe.Payout.create(method='instant')"),
        ("STRIPE_CAPITAL", "Stripe Capital cash advance", 2500, "COVERS GAP", "Accept at dashboard.stripe.com/capital"),
        ("INVOICE_ACCEL", "Early-payment discount to customers", 130, "PARTIAL", "Offer 2% early-pay discount to 2 customers"),
    ],
}

# ─── RENDER HELPERS ──────────────────────────────────────────────────
def new_canvas():
    return Image.new('RGB', (VW, VH), BG_DARK)

def draw_char(canvas, ch, row, col, color=FG_WHITE, bold=False):
    if ch == ' ':
        return
    if 0 <= row < ROWS and 0 <= col < COLS:
        draw = ImageDraw.Draw(canvas)
        x = OX + col * CW
        y = OY + row * CH
        draw.text((x, y), ch, font=FONT, fill=color)

def draw_text(canvas, text, row, col, color=FG_WHITE, bold=False):
    for i, ch in enumerate(text):
        draw_char(canvas, ch, row, col + i, color, bold)

def draw_box(canvas, r1, c1, r2, c2, color=FG_DIM, title=None):
    # Corners
    draw_char(canvas, CHAR_TL, r1, c1, color)
    draw_char(canvas, CHAR_TR, r1, c2, color)
    draw_char(canvas, CHAR_BL, r2, c1, color)
    draw_char(canvas, CHAR_BR, r2, c2, color)
    # Edges
    for c in range(c1 + 1, c2):
        draw_char(canvas, CHAR_HLINE, r1, c, color)
        draw_char(canvas, CHAR_HLINE, r2, c, color)
    for r in range(r1 + 1, r2):
        draw_char(canvas, CHAR_VLINE, r, c1, color)
        draw_char(canvas, CHAR_VLINE, r, c2, color)
    if title:
        draw_text(canvas, f" {title} ", r1, c1 + 2, FG_CYAN)

def draw_bar(canvas, row, col, width, value, max_val, color=FG_GREEN, label=""):
    filled = int(width * value / max_val) if max_val > 0 else 0
    if label:
        draw_text(canvas, label, row, col, FG_DIM)
        col += len(label) + 1
    for i in range(width):
        ch = CHAR_BLOCK_FULL if i < filled else CHAR_BLOCK_1
        draw_char(canvas, ch, row, col + i, color if i < filled else FG_DIM)

def fmt_money(v):
    if v >= 0:
        return f"${v:,.0f}"
    return f"-${abs(v):,.0f}"

# ─── SCENE FUNCTIONS ─────────────────────────────────────────────────
class SceneState:
    def __init__(self):
        self.t = 0
        self.frame = 0
        self.typewriter_pos = {}
        self.reveal_progress = {}
        self.particles = []
        self.scanline_offset = 0
        self.glitch_lines = []

S = SceneState()

def lerp(a, b, t):
    return a + (b - a) * t

def ease_out_cubic(t):
    return 1 - (1 - t) ** 3

def ease_in_out_cubic(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2

def scene_boot(canvas, t):
    """Opening terminal boot sequence."""
    S.scanline_offset = int(t * 30) % ROWS
    
    # Scanline effect
    for r in range(ROWS):
        intensity = max(0, 1 - abs(r - S.scanline_offset) / 3)
        if intensity > 0.3:
            for c in range(COLS):
                if random.random() < 0.02:
                    draw_char(canvas, random.choice('01'), r, c, 
                            (int(FG_GREEN[0]*intensity), int(FG_GREEN[1]*intensity), int(FG_GREEN[2]*intensity)))
    
    # Boot messages
    messages = [
        ("INITIALIZING CASH FLOW ADVISOR v0.4...", 2),
        ("[OK] Stripe MCP connection established", 4),
        ("[OK] Loading fixed expenses from config.yaml", 5),
        ("[OK] Fetching pending payouts ($22,000)", 6),
        ("[OK] Retrieving Capital financing offers", 7),
        ("[OK] Building 30-day projection model", 8),
        ("", 10),
        (">> READY. Generating report...", 12),
    ]
    
    for msg, row in messages:
        if t > row * 0.15:
            progress = min(1, (t - row * 0.15) * 8)
            visible = msg[:int(len(msg) * progress)]
            draw_text(canvas, visible, row, 2, FG_GREEN)

def scene_header(canvas, t):
    """Report header with animated border."""
    progress = min(1, t * 2)
    
    # Top border drawing
    width = 70
    start_c = (COLS - width) // 2
    for c in range(int(width * progress)):
        draw_char(canvas, CHAR_HLINE, 1, start_c + c, FG_CYAN)
        draw_char(canvas, CHAR_HLINE, 4, start_c + c, FG_CYAN)
    if progress > 0.5:
        for r in range(2, 4):
            draw_char(canvas, CHAR_VLINE, r, start_c, FG_CYAN)
            draw_char(canvas, CHAR_VLINE, r, start_c + width - 1, FG_CYAN)
    if progress > 0.8:
        draw_char(canvas, CHAR_TL, 1, start_c, FG_CYAN)
        draw_char(canvas, CHAR_TR, 1, start_c + width - 1, FG_CYAN)
        draw_char(canvas, CHAR_BL, 4, start_c, FG_CYAN)
        draw_char(canvas, CHAR_BR, 4, start_c + width - 1, FG_CYAN)
    
    # Title
    if progress > 0.6:
        title = "💰 CASH FLOW & EXPENSE REPORT — 2026-06-29"
        draw_text(canvas, title, 2, start_c + (width - len(title)) // 2, FG_WHITE)
        subtitle = "Hermes Agent · Stripe Capital Integration · MCP Mode"
        draw_text(canvas, subtitle, 3, start_c + (width - len(subtitle)) // 2, FG_DIM)

def scene_balances(canvas, t):
    """Current balances section."""
    start_row = 6
    progress = min(1, (t - 3) * 1.5)
    
    draw_text(canvas, "── CURRENT BALANCES ────────────────────────────────────────", start_row, 2, FG_CYAN)
    
    if progress > 0.2:
        avail = int(lerp(0, REPORT_DATA["available"], ease_out_cubic(min(1, (progress - 0.2) * 2))))
        draw_text(canvas, f"  Available now:    {fmt_money(avail)}", start_row + 1, 4, FG_GREEN)
    
    if progress > 0.5:
        pend = int(lerp(0, REPORT_DATA["pending"], ease_out_cubic(min(1, (progress - 0.5) * 2))))
        draw_text(canvas, f"  Pending payout:   {fmt_money(pend)} (in Stripe pipeline)", start_row + 2, 4, FG_BLUE)
    
    if progress > 0.8:
        total = REPORT_DATA["available"] + REPORT_DATA["pending"]
        draw_text(canvas, f"  ─────────────────────────────────", start_row + 3, 4, FG_DIM)
        draw_text(canvas, f"  Total accessible: {fmt_money(total)}", start_row + 4, 4, FG_WHITE, bold=True)

def scene_expenses(canvas, t):
    """Upcoming fixed expenses - building row by row."""
    start_row = 12
    progress = min(1, (t - 5) * 1.2)
    
    draw_text(canvas, "── UPCOMING FIXED EXPENSES ─────────────────────────────────", start_row, 2, FG_CYAN)
    
    for i, (name, amt, days, recurring) in enumerate(REPORT_DATA["expenses"]):
        row = start_row + 1 + i
        item_progress = min(1, max(0, (progress - i * 0.1) * 3))
        
        if item_progress > 0:
            # Animate the amount counting up
            display_amt = int(amt * ease_out_cubic(item_progress))
            recur_tag = "recurring" if recurring else "one-off"
            color = FG_RED if amt > 10000 else (FG_AMBER if amt > 5000 else FG_WHITE)
            tag_color = FG_GREEN if recurring else FG_ORANGE
            
            line = f"  • {name:<30} {fmt_money(display_amt):>12}   (due in {days} days, {recur_tag})"
            draw_text(canvas, line, row, 4, color)
            
            # Animated bar for large expenses
            if amt > 10000 and item_progress > 0.5:
                bar_width = 30
                bar_filled = int(bar_width * item_progress)
                bar_str = CHAR_BLOCK_FULL * bar_filled + CHAR_BLOCK_1 * (bar_width - bar_filled)
                draw_text(canvas, f"    [{bar_str}]", row + 0.5, 4, color)

def scene_projection(canvas, t):
    """30-day cash flow projection table - builds row by row."""
    start_row = 20
    progress = min(1, (t - 8) * 0.8)
    
    draw_text(canvas, "── 30-DAY CASH FLOW PROJECTION ─────────────────────────────", start_row, 2, FG_CYAN)
    
    # Table header
    if progress > 0.1:
        header = "  Date         | Net In       | Outflow      | Projected Balance"
        draw_text(canvas, header, start_row + 1, 2, FG_WHITE)
        draw_text(canvas, "  " + "─" * 68, start_row + 2, 2, FG_DIM)
    
    # Projection rows - simplified key dates
    proj_rows = [
        ("2026-06-29", 0, 0, 12500, None, FG_WHITE),
        ("2026-07-01", 3500, 3200, 12800, "INVOICE: Professional Services", FG_GREEN),
        ("2026-07-02", 0, 28000, -15200, "🔴 CRITICAL GAP: Payroll", FG_RED),
        ("2026-07-03", 22000, 0, 6800, "PAYOUT: Stripe $22,000", FG_BLUE),
        ("2026-07-04", 0, 850, 5950, None, FG_WHITE),
        ("2026-07-06", 0, 4500, 1450, "🟡 BELOW BUFFER", FG_AMBER),
        ("2026-07-07", 15000, 0, 16450, "INVOICE: Q2 Enterprise License", FG_GREEN),
        ("2026-07-11", 0, 7000, 9450, None, FG_WHITE),
        ("2026-07-16", 0, 28000, -17050, "🔴 CRITICAL GAP: Payroll", FG_RED),
    ]
    
    for i, (date, net_in, out, bal, note, color) in enumerate(proj_rows):
        row = start_row + 3 + i
        item_progress = min(1, max(0, (progress - 0.1 - i * 0.08) * 5))
        
        if item_progress > 0:
            # Animate numbers counting up
            ni = int(net_in * ease_out_cubic(item_progress))
            out_amt = int(out * ease_out_cubic(item_progress))
            bal_amt = 12500  # starting balance
            # Compute actual running balance
            for j in range(i + 1):
                bal_amt += proj_rows[j][1] - proj_rows[j][2]
            bal_disp = int(bal_amt * ease_out_cubic(item_progress)) if item_progress > 0.3 else 12500
            
            bal_str = fmt_money(bal_disp)
            bal_color = FG_RED if bal_amt < 0 else (FG_AMBER if bal_amt < 5000 else FG_GREEN)
            
            line = f"  {date}   | {fmt_money(ni):>12} | {fmt_money(out_amt):>12} | {bal_str:>18}"
            draw_text(canvas, line, row, 2, color if color != FG_WHITE else FG_WHITE)
            
            if note and item_progress > 0.7:
                draw_text(canvas, f"    └─ [{note}]", row + 0.3, 2, FG_DIM)

def scene_gaps(canvas, t):
    """Critical gaps detected - pulsing red alerts."""
    start_row = 32
    progress = min(1, (t - 15) * 1.5)
    
    if progress > 0:
        draw_text(canvas, "── CRITICAL GAPS DETECTED ──────────────────────────────────", start_row, 2, FG_RED)
    
    for i, (date, gap, reason) in enumerate(REPORT_DATA["gaps"]):
        row = start_row + 1 + i
        item_progress = min(1, max(0, (progress - i * 0.2) * 3))
        
        if item_progress > 0:
            # Pulsing effect
            pulse = 0.7 + 0.3 * math.sin(t * 6 + i)
            r = int(FG_RED[0] * pulse)
            g = int(FG_RED[1] * pulse)
            b = int(FG_RED[2] * pulse)
            alert_color = (r, g, b)
            
            gap_amt = int(abs(gap) * ease_out_cubic(item_progress))
            line = f"  ✗ {date} (Day {3 + i*14}): shortage of -${gap_amt:,.0f} (Due to: {reason})"
            draw_text(canvas, line, row, 4, alert_color)
            
            # Animated warning triangles
            if item_progress > 0.5:
                for j in range(3):
                    draw_char(canvas, CHAR_ARROW_DOWN, row, 2 + j * 2, alert_color)

def scene_options(canvas, t):
    """Funding options - sliding in from right."""
    start_row = 36
    progress = min(1, (t - 18) * 1.0)
    
    if progress > 0:
        draw_text(canvas, "── FUNDING & LOAN SUGGESTIONS ──────────────────────────────", start_row, 2, FG_CYAN)
        draw_text(canvas, "  Ranked by cost (lowest first):", start_row + 1, 4, FG_DIM)
    
    for i, (key, desc, cost, coverage, action) in enumerate(REPORT_DATA["options"]):
        row = start_row + 2 + i * 3
        item_progress = min(1, max(0, (progress - i * 0.15) * 4))
        
        if item_progress > 0:
            # Slide in from right
            slide = int((1 - ease_out_cubic(item_progress)) * 20)
            col = 4 + slide
            
            # Option number and type
            type_color = FG_GREEN if "COVERS" in coverage else FG_AMBER
            draw_text(canvas, f"  {i+1}. [{key}] {desc}", row, col, FG_WHITE)
            draw_text(canvas, f"     Cost: {fmt_money(cost)} | {coverage}", row + 0.5, col, type_color)
            draw_text(canvas, f"     Action: {action}", row + 1, col, FG_DIM)
            
            # Cost bar
            if item_progress > 0.6:
                max_cost = max(o[2] for o in REPORT_DATA["options"])
                bar_w = 25
                draw_bar(canvas, row + 0.5, col + 30, bar_w, cost, max_cost, type_color)

def scene_recommendation(canvas, t):
    """CFO recommendation section."""
    start_row = 48
    progress = min(1, (t - 22) * 1.2)
    
    if progress > 0:
        draw_text(canvas, "── AI CFO BRIEFING ────────────────────────────────────────", start_row, 2, FG_PURPLE)
    
    recs = [
        ("IMMEDIATE", "Trigger $22K instant payout ($330 fee) → clears Jul 2 payroll gap in hours"),
        ("WITHIN 24H", "Evaluate Stripe Capital $25K advance ($2.5K fee) → covers mid-month gap"),
        ("OPTIONAL", "Offer 2% early-pay discount on $18.5K invoices ($130 cost, partial coverage)"),
    ]
    
    for i, (priority, text) in enumerate(recs):
        row = start_row + 1 + i * 2
        item_progress = min(1, max(0, (progress - i * 0.2) * 3))
        
        if item_progress > 0:
            pri_color = FG_RED if priority == "IMMEDIATE" else (FG_AMBER if priority == "WITHIN 24H" else FG_GREEN)
            draw_text(canvas, f"  [{priority}]", row, 4, pri_color)
            # Typewriter effect
            visible = text[:int(len(text) * ease_out_cubic(item_progress))]
            draw_text(canvas, f"  {visible}", row + 0.5, 4, FG_WHITE)

def scene_integrations(canvas, t):
    """Integrations checklist."""
    start_row = 55
    progress = min(1, (t - 25) * 2)
    
    if progress > 0:
        draw_text(canvas, "── INTEGRATIONS DIAGNOSTIC ─────────────────────────────────", start_row, 2, FG_CYAN)
    
    items = [
        ("✅", "Stripe", "MCP MODE (pre-fetched via Hermes Stripe MCP)", FG_GREEN),
        ("✗", "QuickBooks", "DISABLED (Stub)", FG_DIM),
        ("✗", "Xero", "DISABLED (Stub)", FG_DIM),
        ("✗", "Plaid", "DISABLED (Stub)", FG_DIM),
    ]
    
    for i, (icon, name, status, color) in enumerate(items):
        row = start_row + 1 + i
        item_progress = min(1, max(0, (progress - i * 0.15) * 4))
        
        if item_progress > 0:
            draw_text(canvas, f"  {icon} {name:<12} {status}", row, 4, color)

def scene_footer(canvas, t):
    """Footer with saved file paths."""
    start_row = 61
    progress = min(1, (t - 27) * 3)
    
    if progress > 0:
        draw_text(canvas, "────────────────────────────────────────────────────────────", start_row, 2, FG_DIM)
        draw_text(canvas, f"  📁 Report saved: C:\\Users\\MSI\\.hermes\\cashflow\\reports\\2026-06-29.md", start_row + 1, 4, FG_BLUE)
        draw_text(canvas, f"  📊 Chart saved:  C:\\Users\\MSI\\.hermes\\cashflow\\charts\\2026-06-29.png", start_row + 2, 4, FG_BLUE)
        draw_text(canvas, "", start_row + 3, 2, FG_WHITE)
        draw_text(canvas, "  > Cash flow advisory complete. Next run: daily 08:00 or weekly Mon 08:00", start_row + 4, 4, FG_DIM)
        draw_text(canvas, "  > Type '--add-expense \"Description, Amount, DayOfMonth\"' to register new expenses", start_row + 5, 4, FG_DIM)

# ─── MAIN RENDER LOOP ────────────────────────────────────────────────
def render_frame(frame_idx):
    t = frame_idx / FPS
    S.t = t
    S.frame = frame_idx
    
    canvas = new_canvas()
    
    # Background grid lines (very subtle)
    for r in range(0, ROWS, 4):
        for c in range(0, COLS, 8):
            draw_char(canvas, '·', r, c, (16, 20, 28))
    
    # Scene sequencing
    if t < 3.5:
        scene_boot(canvas, t)
    elif t < 6:
        scene_header(canvas, t - 3.5)
        scene_balances(canvas, t - 3.5)
    elif t < 10:
        scene_header(canvas, 2.5)
        scene_balances(canvas, 2.5)
        scene_expenses(canvas, t - 6)
    elif t < 16:
        scene_header(canvas, 2.5)
        scene_balances(canvas, 2.5)
        scene_expenses(canvas, 4)
        scene_projection(canvas, t - 10)
    elif t < 20:
        scene_header(canvas, 2.5)
        scene_balances(canvas, 2.5)
        scene_expenses(canvas, 4)
        scene_projection(canvas, 6)
        scene_gaps(canvas, t - 16)
    elif t < 24:
        scene_header(canvas, 2.5)
        scene_balances(canvas, 2.5)
        scene_expenses(canvas, 4)
        scene_projection(canvas, 6)
        scene_gaps(canvas, 4)
        scene_options(canvas, t - 20)
    elif t < 28:
        scene_header(canvas, 2.5)
        scene_balances(canvas, 2.5)
        scene_expenses(canvas, 4)
        scene_projection(canvas, 6)
        scene_gaps(canvas, 4)
        scene_options(canvas, 4)
        scene_recommendation(canvas, t - 24)
    else:
        scene_header(canvas, 2.5)
        scene_balances(canvas, 2.5)
        scene_expenses(canvas, 4)
        scene_projection(canvas, 6)
        scene_gaps(canvas, 4)
        scene_options(canvas, 4)
        scene_recommendation(canvas, 4)
        scene_integrations(canvas, t - 28)
        scene_footer(canvas, t - 28)
    
    # Subtle CRT scanline overlay
    for r in range(0, ROWS, 3):
        if (r + int(t * 10)) % 6 == 0:
            for c in range(COLS):
                # Darken every 3rd row slightly
                pass  # Skip for performance, could add post-process
    
    return canvas

def main():
    print(f"Rendering {N_FRAMES} frames at {FPS}fps ({DURATION}s)...")
    print(f"Resolution: {VW}x{VH}, Grid: {COLS}x{ROWS}")
    print(f"Output: {OUTPUT_MP4}")
    
    # Render frames to temporary directory
    frame_dir = os.path.join(WORKDIR, "frames")
    os.makedirs(frame_dir, exist_ok=True)
    
    frame_paths = []
    
    for i in range(N_FRAMES):
        if i % 24 == 0:
            print(f"  Frame {i}/{N_FRAMES} ({i/FPS:.1f}s)")
        
        canvas = render_frame(i)
        frame_path = os.path.join(frame_dir, f"frame_{i:04d}.png")
        canvas.save(frame_path)
        frame_paths.append(frame_path)
    
    print("Encoding video with ffmpeg...")
    
    # Encode with ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", os.path.join(frame_dir, "frame_%04d.png"),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",  # Ensure even dimensions
        OUTPUT_MP4
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"\n✅ Video saved to: {OUTPUT_MP4}")
        
        # Clean up frames
        import shutil
        shutil.rmtree(frame_dir)
        print("Frames cleaned up.")
    else:
        print(f"\n❌ ffmpeg error:")
        print(result.stderr)
        print(f"\nFrames left in: {frame_dir}")

if __name__ == "__main__":
    main()