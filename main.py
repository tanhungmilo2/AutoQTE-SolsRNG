"""
WASD Recognition Macro  ─  v3.1 (Sliding Window Upgrade)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE (per slot, ~3 ms total for 5 slots):
  capture BGRA (Padded) → red-channel Otsu → morph-open (kills glow)
  → TM_CCOEFF_NORMED with Sliding Window vs cached templates
  → Find best match location & crop to FIXED(64×80)
  → confidence gate → Hu-Moments fallback (on cropped) → key press
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import cv2
import numpy as np
import mss
import keyboard
import time
import os
import sys
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

# ══════════════════════════════════════════════════════════════════════
#  CONFIGURATION  ─  edit this section only
# ══════════════════════════════════════════════════════════════════════

# Kích thước cố định của template (Must match WIDTH/HEIGHT trong generate_templates.py)
FIXED_W: int = 64
FIXED_H: int = 80
FIXED_SIZE = (FIXED_W, FIXED_H)   # cv2 uses (width, height)

# Độ lệch pixel tối đa cho phép (Ví dụ: 15 pixel về mọi hướng)
PADDING: int = 15

# Minimum TM_CCOEFF_NORMED score to accept a recognition result.
CONFIDENCE_THRESHOLD: float = 0.35

# Minimum score margin between best and second-best to accept without fallback.
MARGIN_THRESHOLD: float = 0.08

# Morphological open kernel size. Kills isolated glow pixels.
MORPH_KERNEL: np.ndarray = np.ones((2, 2), np.uint8)

# Template files. Place next to this script (or set TEMPLATE_DIR below).
TEMPLATE_FILES: dict[str, str] = {
    'w': 'slot1_w.png',
    'a': 'slot1_a.png',
    's': 'slot1_s.png',
    'd': 'slot1_d.png',
}

# ── ROI Config ────────────────────────────────────────────────────────
ROI_FILE: str   = 'rois.json'          # saved by --calibrate
HOTKEY: str     = 'e'
KEYSTROKE_DELAY = 0.05                 # seconds between key presses

# Fallback ROIs (used when rois.json is absent)
DEFAULT_ROIS: list[tuple] = [
    (183, 390, FIXED_W, FIXED_H),      # Slot 1
    (353, 390, FIXED_W, FIXED_H),      # Slot 2
    (528, 390, FIXED_W, FIXED_H),      # Slot 3
    (698, 390, FIXED_W, FIXED_H),      # Slot 4
    (868, 390, FIXED_W, FIXED_H),      # Slot 5
]

# ══════════════════════════════════════════════════════════════════════
#  PATHS & LOGGING
# ══════════════════════════════════════════════════════════════════════

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR  = os.path.join(BASE_DIR, 'debug')
os.makedirs(DEBUG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('wasd')

# ══════════════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class SlotResult:
    key:        Optional[str]   # 'w'|'a'|'s'|'d' or None
    score:      float           # primary TM score
    margin:     float           # gap to second-best
    via:        str             # 'template' | 'hu_moments' | 'unknown'
    slot_idx:   int

    @property
    def accepted(self) -> bool:
        return self.key is not None

    def __str__(self) -> str:
        k = self.key.upper() if self.key else '?'
        return (f"Slot{self.slot_idx+1} {k}  "
                f"score={self.score:.3f}  margin={self.margin:.3f}  [{self.via}]")


@dataclass
class TemplateBank:
    """Holds pre-processed, fixed-size binary templates. Loaded once at startup."""
    data: dict[str, np.ndarray]       # key → (FIXED_H×FIXED_W uint8 binary)
    hu:   dict[str, np.ndarray]       # key → Hu moment vector (7,) for fallback
    keys: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, file_map: dict[str, str]) -> 'TemplateBank':
        data, hu = {}, {}
        for key, fname in file_map.items():
            path = os.path.join(BASE_DIR, fname)
            raw  = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if raw is None:
                raise FileNotFoundError(
                    f"Template '{key}' not found: {path}\n"
                    f"Run generate_templates.py first."
                )
            # Binarise
            _, t = cv2.threshold(raw, 127, 255, cv2.THRESH_BINARY)
            # Resize to fixed size
            t = cv2.resize(t, FIXED_SIZE, interpolation=cv2.INTER_NEAREST)
            data[key] = t
            hu[key]   = _compute_hu(t)
            log.info(f"  Template '{key}': shape={t.shape}  "
                     f"white_px={np.count_nonzero(t)}  "
                     f"hu[0]={hu[key][0]:.4f}")
        keys = list(data.keys())
        return cls(data=data, hu=hu, keys=keys)


# ══════════════════════════════════════════════════════════════════════
#  PREPROCESSING
# ══════════════════════════════════════════════════════════════════════

def preprocess(bgra: np.ndarray) -> np.ndarray:
    """BGRA  →  clean binary (giữ nguyên kích thước truyền vào để chạy trượt)"""
    r = bgra[:, :, 2]                                               
    _, t = cv2.threshold(r, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)       
    t = cv2.morphologyEx(t, cv2.MORPH_OPEN, MORPH_KERNEL)          
    return t 


# ══════════════════════════════════════════════════════════════════════
#  RECOGNITION — PRIMARY (Template Matching với Sliding Window)
# ══════════════════════════════════════════════════════════════════════

def recognize_primary(roi_bin_padded: np.ndarray,
                      bank: TemplateBank) -> tuple[Optional[str], float, float, np.ndarray]:
    """
    Sử dụng Sliding Window để quét tìm vị trí khớp nhất của template trong vùng ảnh rộng.
    Trả về (best_key_or_None, best_score, margin, roi_bin_cropped).
    """
    scores = {}
    locs = {}
    
    # Duyệt qua các nút W, A, S, D để tìm điểm cao nhất bằng cửa sổ trượt
    for key in bank.keys:
        res = cv2.matchTemplate(roi_bin_padded, bank.data[key], cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        scores[key] = float(max_val)
        locs[key] = max_loc

    sorted_ = sorted(scores.values(), reverse=True)
    best_k  = max(scores, key=scores.get)
    best_s  = sorted_[0]
    margin  = sorted_[0] - sorted_[1] if len(sorted_) > 1 else 1.0

    # Trích xuất đúng khung FIXED_SIZE (64x80) tại nơi khớp nhất để phục vụ debug và hu_moments
    max_x, max_y = locs[best_k]
    roi_bin_cropped = roi_bin_padded[max_y:max_y + FIXED_H, max_x:max_x + FIXED_W]

    if best_s >= CONFIDENCE_THRESHOLD and margin >= MARGIN_THRESHOLD:
        return best_k, best_s, margin, roi_bin_cropped
    return None, best_s, margin, roi_bin_cropped


# ══════════════════════════════════════════════════════════════════════
#  RECOGNITION — FALLBACK (Hu Moments)
# ══════════════════════════════════════════════════════════════════════

def _compute_hu(binary: np.ndarray) -> np.ndarray:
    """Compute log-scaled Hu moment vector for shape matching."""
    m   = cv2.moments(binary)
    hu  = cv2.HuMoments(m).flatten()
    with np.errstate(divide='ignore', invalid='ignore'):
        hu = -np.sign(hu) * np.log10(np.abs(hu) + 1e-10)
    return hu


def recognize_fallback(roi_bin: np.ndarray,
                        bank: TemplateBank) -> tuple[Optional[str], float]:
    roi_hu = _compute_hu(roi_bin)
    dists  = {k: float(np.sum(np.abs(roi_hu - bank.hu[k]))) for k in bank.keys}
    best_k = min(dists, key=dists.get)
    best_d = dists[best_k]

    HU_THRESHOLD = 3.0   
    if best_d < HU_THRESHOLD:
        return best_k, best_d
    return None, best_d


# ══════════════════════════════════════════════════════════════════════
#  FULL SLOT RECOGNITION
# ══════════════════════════════════════════════════════════════════════

def recognize_slot(roi_bin_padded: np.ndarray,
                   bank: TemplateBank,
                   slot_idx: int) -> tuple[SlotResult, np.ndarray]:
    """
    Nhận diện toàn diện cho một ô bằng thuật toán cửa sổ trượt.
    """
    # ── Thuật toán chính (Cửa sổ trượt) ──────────────────────────────
    key, score, margin, roi_bin_cropped = recognize_primary(roi_bin_padded, bank)
    if key is not None:
        return SlotResult(key=key, score=score, margin=margin,
                          via='template', slot_idx=slot_idx), roi_bin_cropped

    # ── Thuật toán phụ (Chạy trên ảnh đã được căn giữa tự động) ──────
    fb_key, fb_dist = recognize_fallback(roi_bin_cropped, bank)
    if fb_key is not None:
        fb_score = 1.0 / (1.0 + fb_dist)
        return SlotResult(key=fb_key, score=fb_score, margin=0.0,
                          via='hu_moments', slot_idx=slot_idx), roi_bin_cropped

    # ── Thất bại ──────────────────────────────────────────────────────
    return SlotResult(key=None, score=score, margin=margin,
                      via='unknown', slot_idx=slot_idx), roi_bin_cropped


# ══════════════════════════════════════════════════════════════════════
#  DEBUG OUTPUT
# ══════════════════════════════════════════════════════════════════════

def save_debug(bgra_padded: np.ndarray,
               roi_bin_cropped: np.ndarray,
               result: SlotResult,
               bank: TemplateBank,
               force: bool = False) -> None:
    tag = f"slot{result.slot_idx + 1}"

    # Lưu ảnh gốc kênh đỏ có kèm viền PADDING rộng rãi để dễ quan sát độ lệch
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{tag}_1_red_raw.png"),
                bgra_padded[:, :, 2])

    r = bgra_padded[:, :, 2]
    _, otsu_only = cv2.threshold(r, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{tag}_2_otsu.png"), otsu_only)

    # Ảnh sau khi quét cửa sổ trượt và tự động cắt chuẩn tâm chữ
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{tag}_3_final.png"), roi_bin_cropped)

    if result.key:
        cv2.imwrite(os.path.join(DEBUG_DIR, f"{tag}_4_tmpl_{result.key}.png"),
                    bank.data[result.key])

    # So sánh song song ảnh cắt tự động và template (Không lo lỗi lệch size nhờ sliding window)
    if result.key and roi_bin_cropped.shape == bank.data[result.key].shape:
        side = np.hstack([roi_bin_cropped, np.full((FIXED_H, 4), 128, dtype=np.uint8),
                          bank.data[result.key]])
        label = f"{result.key.upper()} {result.score:.3f} [{result.via}]"
        side_bgr = cv2.cvtColor(side, cv2.COLOR_GRAY2BGR)
        cv2.putText(side_bgr, label, (2, FIXED_H - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        cv2.imwrite(os.path.join(DEBUG_DIR, f"{tag}_5_compare.png"), side_bgr)


# ══════════════════════════════════════════════════════════════════════
#  MAIN RECOGNITION CYCLE
# ══════════════════════════════════════════════════════════════════════

_first_cycle = [True]

def run_cycle(bank: TemplateBank,
              rois: list[tuple],
              force_debug: bool = False) -> None:
    debug    = _first_cycle[0] or force_debug
    results: list[SlotResult] = []
    captures: list[tuple]     = []    

    with mss.mss() as sct:
        for i, (x, y, w, h) in enumerate(rois):
            # TỰ ĐỘNG MỞ RỘNG VÙNG CHỤP MÀN HÌNH THEO BIẾN PADDING
            pad_x = PADDING
            pad_y = PADDING
            bgra_padded = np.array(sct.grab({"left": x - pad_x, "top": y - pad_y,
                                             "width": w + 2*pad_x, "height": h + 2*pad_y}))
            roi_bin_padded = preprocess(bgra_padded)
            
            # Tiến hành nhận diện dựa trên ảnh mở rộng nâng cao
            result, roi_bin_cropped = recognize_slot(roi_bin_padded, bank, i)
            results.append(result)
            
            if debug or not result.accepted:
                captures.append((bgra_padded, roi_bin_cropped))
            else:
                captures.append(None)

    if debug:
        for i, (res, cap) in enumerate(zip(results, captures)):
            if cap:
                save_debug(cap[0], cap[1], res, bank)
        log.info(f"Debug images → {DEBUG_DIR}")

    for i, (res, cap) in enumerate(zip(results, captures)):
        if not res.accepted and cap:
            save_debug(cap[0], cap[1], res, bank, force=True)

    summary = '  '.join(str(r) for r in results)
    accepted = [r for r in results if r.accepted]
    log.info(f"[{len(accepted)}/5 accepted]  {summary}")

    if _first_cycle[0]:
        _first_cycle[0] = False

    if len(accepted) == len(results):
        for res in results:
            keyboard.press_and_release(res.key)
            time.sleep(KEYSTROKE_DELAY)
    else:
        failed = [str(i+1) for i, r in enumerate(results) if not r.accepted]
        log.warning(f"Skipped key press — unknown slot(s): {', '.join(failed)}")


# ══════════════════════════════════════════════════════════════════════
#  ROI CALIBRATION TOOL
# ══════════════════════════════════════════════════════════════════════

def calibrate_rois() -> None:
    try:
        import pyautogui
    except ImportError:
        log.error("pyautogui required for calibration: pip install pyautogui")
        sys.exit(1)

    rois_out: list[list] = []
    collected: set[str]  = set()

    print("━━━  ROI CALIBRATION  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  ROI size: {FIXED_W}×{FIXED_H}  (matches generate_templates.py)")
    print("  1. Switch to the game window — wait for letters to appear.")
    print("  2. Hover over the CENTER of each letter.")
    print("  3. Press 1 → 5 in order (left to right).")
    print("  4. After each press, check debug/calib_slotN_final.png")
    print("  Press Q to abort.\n")

    def on_key(event: keyboard.KeyboardEvent) -> None:
        if event.name not in [str(i) for i in range(1, 6)]:
            return
        if event.name in collected:
            return
        collected.add(event.name)
        slot_n = int(event.name)

        mx, my = pyautogui.position()
        x = mx - FIXED_W // 2
        y = my - FIXED_H // 2
        roi = [x, y, FIXED_W, FIXED_H]
        rois_out.append(roi)

        with mss.mss() as sct:
            bgra    = np.array(sct.grab({"left": x, "top": y,
                                          "width": FIXED_W, "height": FIXED_H}))
            roi_bin = preprocess(bgra)
            white   = np.count_nonzero(roi_bin)
            total   = FIXED_W * FIXED_H

        cv2.imwrite(os.path.join(DEBUG_DIR, f"calib_slot{slot_n}_red.png"),
                    bgra[:, :, 2])
        cv2.imwrite(os.path.join(DEBUG_DIR, f"calib_slot{slot_n}_final.png"),
                    roi_bin)

        ratio   = white / total
        quality = "✓ OK" if 0.03 < ratio < 0.75 else "⚠ CHECK IMAGE"
        print(f"  Slot {slot_n}: center=({mx},{my})  "
              f"white={white}/{total} ({ratio:.0%})  {quality}")

        if len(rois_out) == 5:
            _save_rois(rois_out)
            print(f"\n  Saved → {os.path.join(BASE_DIR, ROI_FILE)}")
            print("  Run without --calibrate to start the macro.")
            os._exit(0)

    keyboard.on_press(on_key)
    keyboard.wait('q')
    print("Calibration aborted.")


def _save_rois(rois: list) -> None:
    with open(os.path.join(BASE_DIR, ROI_FILE), 'w') as f:
        json.dump(rois, f, indent=2)


def _load_rois() -> list[tuple]:
    path = os.path.join(BASE_DIR, ROI_FILE)
    if os.path.exists(path):
        with open(path) as f:
            rois = [tuple(r) for r in json.load(f)]
        log.info(f"ROIs loaded from {ROI_FILE}:")
        for i, r in enumerate(rois):
            log.info(f"  Slot {i+1}: x={r[0]}  y={r[1]}  w={r[2]}  h={r[3]}")
        return rois
    log.warning(f"{ROI_FILE} not found — using DEFAULT_ROIS. Run --calibrate first!")
    return [tuple(r) for r in DEFAULT_ROIS]


if __name__ == '__main__':
    force_debug = '--debug' in sys.argv

    if '--calibrate' in sys.argv:
        calibrate_rois()
        sys.exit(0)

    log.info("Loading templates…")
    bank = TemplateBank.load(TEMPLATE_FILES)
    rois = _load_rois()

    log.info("")
    log.info(f"  Confidence threshold : {CONFIDENCE_THRESHOLD}")
    log.info(f"  Margin threshold     : {MARGIN_THRESHOLD}")
    log.info(f"  Fixed size           : {FIXED_W}×{FIXED_H}")
    log.info(f"  Hotkey               : [{HOTKEY.upper()}]")
    log.info(f"  Debug dir            : {DEBUG_DIR}")
    log.info("")
    log.info(f"Ready — [{HOTKEY.upper()}] trigger | [p] quit")

    keyboard.add_hotkey(
        HOTKEY,
        lambda: run_cycle(bank, rois, force_debug=force_debug)
    )
    keyboard.wait('p')
