"""
DIAGNOSTIC v2: Deep comparison of captures vs templates.

Shows:
  1. All 4 templates (what we're trying to match against)
  2. All 5 captured ROIs (what we're trying to match)
  3. Side-by-side comparison + histograms
  4. Raw metrics: white pixel count, correlation with each template

Run this ONCE while the game shows a known sequence (e.g. D-A-W-S-A).
"""

import cv2
import numpy as np
import mss
import os
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger()

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR    = os.path.join(BASE_DIR, 'debug')
ROI_FILE     = os.path.join(BASE_DIR, 'rois.json')
TEMPLATE_DIR = BASE_DIR
FIXED_SIZE   = (64, 80)

os.makedirs(DEBUG_DIR, exist_ok=True)

# Load ROIs
if os.path.exists(ROI_FILE):
    with open(ROI_FILE) as f:
        ROIS = [tuple(r) for r in json.load(f)]
    log.info(f"Loaded {len(ROIS)} ROIs from {ROI_FILE}")
else:
    log.error(f"{ROI_FILE} not found. Run --calibrate first.")
    sys.exit(1)

# Load templates
TEMPLATE_FILES = {'w': 'slot1_w.png', 'a': 'slot1_a.png',
                  's': 'slot1_s.png', 'd': 'slot1_d.png'}
templates_raw = {}
templates_proc = {}

log.info("\n" + "="*70)
log.info("TEMPLATES (as stored on disk)")
log.info("="*70)
for key, fname in TEMPLATE_FILES.items():
    path = os.path.join(TEMPLATE_DIR, fname)
    raw = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if raw is None:
        log.error(f"Template not found: {path}")
        sys.exit(1)
    templates_raw[key] = raw
    
    # Threshold like main.py does
    _, t = cv2.threshold(raw, 127, 255, cv2.THRESH_BINARY)
    # Resize to FIXED_SIZE
    t = cv2.resize(t, FIXED_SIZE, interpolation=cv2.INTER_NEAREST)
    templates_proc[key] = t
    
    white_px = np.count_nonzero(t)
    log.info(f"  '{key}':  raw shape={raw.shape}  "
             f"after threshold+resize: shape={t.shape}  white_px={white_px}")

# Save all templates side-by-side
template_strips = []
for key in ['w', 'a', 's', 'd']:
    img = templates_proc[key]
    img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cv2.putText(img_bgr, key.upper(), (2, FIXED_SIZE[1]-2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
    template_strips.append(img_bgr)

templates_side = np.hstack(template_strips)
cv2.imwrite(os.path.join(DEBUG_DIR, '_0_all_templates.png'), templates_side)
log.info(f"  → Saved: {DEBUG_DIR}/_0_all_templates.png")

# Capture all 5 slots
log.info("\n" + "="*70)
log.info("CAPTURING 5 SLOTS (in 2 seconds — switch to game now)")
log.info("="*70)
import time
time.sleep(2)

captures_raw = []
captures_proc = []
slot_names = ['DAWED', 'AWSDA', '?']  # common sequences — won't affect diagnostic

with mss.mss() as sct:
    for i, (x, y, w, h) in enumerate(ROIS):
        bgra = np.array(sct.grab({"left": x, "top": y, "width": w, "height": h}))
        
        # Save raw BGRA (for inspection of actual game pixels)
        raw_bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        cv2.imwrite(os.path.join(DEBUG_DIR, f"_1_slot{i+1}_raw_bgr.png"), raw_bgr)
        
        # Extract red channel (as main.py does)
        r = bgra[:, :, 2]
        cv2.imwrite(os.path.join(DEBUG_DIR, f"_2_slot{i+1}_red_channel.png"), r)
        
        # Otsu threshold
        _, t_otsu = cv2.threshold(r, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        cv2.imwrite(os.path.join(DEBUG_DIR, f"_3_slot{i+1}_otsu.png"), t_otsu)
        
        # Morph open
        MORPH_KERNEL = np.ones((2, 2), np.uint8)
        t_morph = cv2.morphologyEx(t_otsu, cv2.MORPH_OPEN, MORPH_KERNEL)
        cv2.imwrite(os.path.join(DEBUG_DIR, f"_4_slot{i+1}_morph_open.png"), t_morph)
        
        # Resize to FIXED_SIZE (as main.py does)
        t_final = cv2.resize(t_morph, FIXED_SIZE, interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(os.path.join(DEBUG_DIR, f"_5_slot{i+1}_final.png"), t_final)
        
        captures_raw.append(bgra)
        captures_proc.append(t_final)
        
        white_px = np.count_nonzero(t_final)
        log.info(f"  Slot {i+1}: shape={t_final.shape}  white_px={white_px}")

# Detailed analysis
log.info("\n" + "="*70)
log.info("MATCH SCORES (TM_CCOEFF_NORMED)")
log.info("="*70)

for i, roi_proc in enumerate(captures_proc):
    log.info(f"\nSlot {i+1}:")
    scores = {}
    for key, tmpl_proc in templates_proc.items():
        res = cv2.matchTemplate(roi_proc, tmpl_proc, cv2.TM_CCOEFF_NORMED)
        score = float(res[0, 0])
        scores[key] = score
    
    sorted_keys = sorted(scores, key=scores.get, reverse=True)
    for k in sorted_keys:
        marker = "↑ BEST" if k == sorted_keys[0] else ""
        log.info(f"    {k.upper()}: {scores[k]:+.4f}  {marker}")

# Side-by-side: captures vs templates
log.info("\n" + "="*70)
log.info("VISUAL COMPARISON: Captures vs Templates")
log.info("="*70)

for i, roi_proc in enumerate(captures_proc):
    roi_bgr = cv2.cvtColor(roi_proc, cv2.COLOR_GRAY2BGR)
    
    # Find best-matching template
    scores = {}
    for key, tmpl in templates_proc.items():
        res = cv2.matchTemplate(roi_proc, tmpl, cv2.TM_CCOEFF_NORMED)
        scores[key] = float(res[0, 0])
    best_key = max(scores, key=scores.get)
    best_score = scores[best_key]
    
    # Create comparison: [capture] [space] [template]
    space = np.ones((FIXED_SIZE[1], 8, 3), dtype=np.uint8) * 128
    tmpl_bgr = cv2.cvtColor(templates_proc[best_key], cv2.COLOR_GRAY2BGR)
    side = np.hstack([roi_bgr, space, tmpl_bgr])
    
    label = f"Slot{i+1} vs {best_key.upper()} (score={best_score:.3f})"
    cv2.putText(side, label, (2, FIXED_SIZE[1]-2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    
    cv2.imwrite(os.path.join(DEBUG_DIR, f"_6_slot{i+1}_vs_best.png"), side)
    log.info(f"  Slot {i+1}: {label}")

# Histogram analysis
log.info("\n" + "="*70)
log.info("HISTOGRAM ANALYSIS (red channel)")
log.info("="*70)

for i in range(5):
    r = captures_raw[i][:, :, 2]
    hist = cv2.calcHist([r], [0], None, [256], [0, 256])
    h_min, h_max = r.min(), r.max()
    h_mean, h_std = r.mean(), r.std()
    h_white = np.count_nonzero(r > 200)
    h_dark = np.count_nonzero(r < 50)
    log.info(f"  Slot {i+1}: min={h_min}  max={h_max}  "
             f"mean={h_mean:.1f}±{h_std:.1f}  white>200:{h_white}  dark<50:{h_dark}")

# Overall diagnosis
log.info("\n" + "="*70)
log.info("DIAGNOSIS")
log.info("="*70)

print("""
WHAT TO CHECK:
  1. _0_all_templates.png
     → Should show 4 clear white letters on black background
     → If templates are inverted (black on white), re-run generate_templates.py
  
  2. _5_slot*_final.png (your actual captures)
     → Compare against templates
     → Should look VISUALLY IDENTICAL to the matching template
     → If all white or all black → ROI is wrong, run --calibrate again
     → If letters are there but score is low → template/capture generation mismatch
  
  3. _6_slot*_vs_best.png
     → Left side: your capture
     → Right side: best-matching template
     → Visually they should look nearly identical
     → If they look different → check steps _1 through _5
  
  4. Red channel histograms above
     → If min/max are very close (e.g. 80-85) → no contrast, Otsu will fail
     → Should have clear separation (e.g. 30-200)
     → If background and letter are indistinguishable → ROI or game state is wrong

NEXT STEPS:
  • If templates look fine but captures don't match:
    → Run with --calibrate to recenter ROIs exactly on letter centers
    → Recheck that slot1_w.png etc exist and are in this directory
  
  • If templates look inverted/wrong:
    → Re-run generate_templates.py with fresh captures
  
  • If ROI capture looks fine but score is still low:
    → The preprocessing pipeline might diverge from generate_templates.py
    → Check: does generate_templates.py use raw red channel Otsu? Yes.
    → Does main.py? Yes. So they should match perfectly on the same input.
    → Issue might be: capture ROI size (64×80) vs actual game letter box
""")

log.info(f"\nAll diagnostics saved to: {DEBUG_DIR}")
log.info("Open the PNG files to visually inspect the pipeline.")