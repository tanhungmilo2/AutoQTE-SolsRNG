"""
SHOW ROIS – Display what the DEFAULT ROIs are capturing (no mouse needed).

Shows the raw BGR pixels from each slot.
Edit DEFAULT_ROIS below if needed.
Press any key to exit.
"""

import cv2
import numpy as np
import mss
import json
import os

FIXED_W, FIXED_H = 64, 80
DISPLAY_SCALE = 4

# Defaults (same as in main.py)
DEFAULT_ROIS = [
    (183, 390, FIXED_W, FIXED_H),
    (353, 390, FIXED_W, FIXED_H),
    (528, 390, FIXED_W, FIXED_H),
    (698, 390, FIXED_W, FIXED_H),
    (868, 390, FIXED_W, FIXED_H),
]

# Try to load from rois.json
if os.path.exists('rois.json'):
    try:
        with open('rois.json') as f:
            rois_data = json.load(f)
            ROIS = [tuple(r) for r in rois_data]
            print("Loaded ROIS from rois.json")
    except:
        ROIS = DEFAULT_ROIS
        print("Error reading rois.json, using defaults")
else:
    ROIS = DEFAULT_ROIS
    print("No rois.json, using DEFAULT_ROIS")

print("\nROI coordinates:")
for i, (x, y, w, h) in enumerate(ROIS):
    print(f"  Slot {i+1}: ({x}, {y}, {w}, {h})")

print("\nCapturing... (wait 2 seconds)")
import time
time.sleep(2)

# Capture all 5 slots
with mss.mss() as sct:
    captures = []
    for x, y, w, h in ROIS:
        bgra = np.array(sct.grab({"left": x, "top": y, "width": w, "height": h}))
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        captures.append(bgr)
        # Also analyze red channel
        r = bgra[:, :, 2]
        print(f"  Red channel: min={r.min()}  max={r.max()}  mean={r.mean():.1f}")

# Create grid
W, H = FIXED_W * DISPLAY_SCALE, FIXED_H * DISPLAY_SCALE
grid = np.zeros((H * 2, W * 3, 3), dtype=np.uint8) + 64

positions = [(0,0), (1,0), (2,0), (0,1), (1,1)]
for i, (row, col) in enumerate(positions):
    img = cv2.resize(captures[i], (W, H), interpolation=cv2.INTER_NEAREST)
    y1, y2 = row * H, (row + 1) * H
    x1, x2 = col * W, (col + 1) * W
    grid[y1:y2, x1:x2] = img
    cv2.putText(grid, f"Slot {i+1}", (x1 + 4, y1 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

cv2.imwrite('_current_rois_preview.png', grid)
print("\nSaved: _current_rois_preview.png")
print("\nVisual inspection:")
print("  ✓ Good: ROIs show clear letter (red/orange) on darker background")
print("  ✗ Bad: All black → ROI too low/right (missing letters)")
print("  ✗ Bad: All red/uniform → ROI capturing frame/glow, not letter")

cv2.imshow('Current ROI Capture', grid)
print("\nPress any key to close window...")
cv2.waitKey(0)
cv2.destroyAllWindows()