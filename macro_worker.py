from __future__ import annotations

import argparse
import json
import os
import sys
import time

import cv2
import keyboard
import mss
import numpy as np
import pyautogui

try:
    import pydirectinput
except ImportError:
    pydirectinput = None


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROI_FILE = os.path.join(BASE_DIR, "rois.json")
DEBUG_DIR = os.path.join(BASE_DIR, "debug")

HOTKEY: str = "e"
QUIT_KEY: str = "p"
CONFIDENCE_THRESHOLD: float = 0.35
MARGIN_THRESHOLD: float = 0.05
FIXED_SIZE = (64, 80)
DEFAULT_ROIS = [
    (183, 390, 64, 80),
    (353, 390, 64, 80),
    (528, 390, 64, 80),
    (698, 390, 64, 80),
    (868, 390, 64, 80),
]
TEMPLATE_FILES = {
    "w": ("slot1_w.png", "w.png"),
    "a": ("slot1_a.png", "a.png"),
    "s": ("slot1_s.png", "s.png"),
    "d": ("slot1_d.png", "d.png"),
}
MORPH_KERNEL = np.ones((2, 2), np.uint8)


def log(message: str):
    print(message, flush=True)


def preprocess_bgra(bgra: np.ndarray) -> np.ndarray:
    red = bgra[:, :, 2]
    _, thresholded = cv2.threshold(red, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cleaned = cv2.morphologyEx(thresholded, cv2.MORPH_OPEN, MORPH_KERNEL)
    return cv2.resize(cleaned, FIXED_SIZE, interpolation=cv2.INTER_NEAREST)


def load_rois() -> list[tuple[int, int, int, int]]:
    if not os.path.exists(ROI_FILE):
        log(f"WARNING: {ROI_FILE} not found; using default ROIs.")
        return DEFAULT_ROIS

    with open(ROI_FILE, encoding="utf-8") as f:
        rois = json.load(f)
    if len(rois) != 5:
        raise RuntimeError(f"Expected 5 ROIs in {ROI_FILE}, found {len(rois)}.")
    return [tuple(map(int, roi)) for roi in rois]


def load_templates() -> dict[str, np.ndarray]:
    templates: dict[str, np.ndarray] = {}
    for key, filenames in TEMPLATE_FILES.items():
        path = next(
            (os.path.join(BASE_DIR, name) for name in filenames if os.path.exists(os.path.join(BASE_DIR, name))),
            None,
        )
        if path is None:
            raise RuntimeError(f"Missing template for {key.upper()}: expected one of {', '.join(filenames)}")

        raw = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if raw is None:
            raise RuntimeError(f"Could not read template: {path}")

        _, thresholded = cv2.threshold(raw, 127, 255, cv2.THRESH_BINARY)
        templates[key] = cv2.resize(thresholded, FIXED_SIZE, interpolation=cv2.INTER_NEAREST)
    return templates


def score_slot(slot_image: np.ndarray, templates: dict[str, np.ndarray]) -> tuple[str, float, float]:
    scores = {
        key: float(cv2.matchTemplate(slot_image, template, cv2.TM_CCOEFF_NORMED)[0, 0])
        for key, template in templates.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_key, best_score = ranked[0]
    second_score = ranked[1][1]
    return best_key, best_score, best_score - second_score


def capture_sequence(debug: bool = False) -> list[str]:
    rois = load_rois()
    templates = load_templates()
    accepted: list[str] = []

    if debug:
        os.makedirs(DEBUG_DIR, exist_ok=True)

    with mss.mss() as sct:
        for index, (x, y, width, height) in enumerate(rois, start=1):
            bgra = np.array(sct.grab({"left": x, "top": y, "width": width, "height": height}))
            processed = preprocess_bgra(bgra)
            best_key, best_score, margin = score_slot(processed, templates)

            if debug:
                cv2.imwrite(os.path.join(DEBUG_DIR, f"slot{index}_raw_bgr.png"), cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR))
                cv2.imwrite(os.path.join(DEBUG_DIR, f"slot{index}_final.png"), processed)

            if best_score >= CONFIDENCE_THRESHOLD and margin >= MARGIN_THRESHOLD:
                accepted.append(best_key)
                log(f"[ACCEPTED] Slot {index}: {best_key.upper()} score={best_score:.3f} margin={margin:.3f}")
            else:
                log(f"[SKIPPED] Slot {index}: {best_key.upper()} score={best_score:.3f} margin={margin:.3f}")

    return accepted


def press_sequence(sequence: list[str]):
    if not sequence:
        log("WARNING: No confident keys detected; nothing pressed.")
        return

    log(f"Pressing sequence: {' '.join(key.upper() for key in sequence)}")
    for key in sequence:
        if pydirectinput is not None:
            pydirectinput.press(key)
        else:
            keyboard.press_and_release(key)
        time.sleep(0.08)


def run_macro(debug: bool = False):
    load_rois()
    load_templates()
    log(f"Ready. Press [{HOTKEY.upper()}] to scan/press. Press [{QUIT_KEY.upper()}] to quit.")

    while True:
        if keyboard.is_pressed(QUIT_KEY):
            break
        if not keyboard.is_pressed(HOTKEY):
            time.sleep(0.03)
            continue

        while keyboard.is_pressed(HOTKEY):
            time.sleep(0.03)
        sequence = capture_sequence(debug=debug)
        if len(sequence) == 5:
            log("[ACCEPTED] 5/5 slots detected.")
        else:
            log(f"WARNING: Only {len(sequence)}/5 slots detected confidently.")
        press_sequence(sequence)
        time.sleep(0.25)

    log("Quit key pressed. Exiting macro.")


def calibrate_rois():
    os.makedirs(DEBUG_DIR, exist_ok=True)
    rois: list[tuple[int, int, int, int]] = []
    log("Calibration started.")
    log("Hover the center of each slot, then press 1, 2, 3, 4, 5.")

    with mss.mss() as sct:
        for slot in range(1, 6):
            log(f"Waiting for slot {slot}: press [{slot}] while your mouse is centered on it.")
            keyboard.wait(str(slot))
            mouse_x, mouse_y = pyautogui.position()
            x = int(mouse_x - FIXED_SIZE[0] / 2)
            y = int(mouse_y - FIXED_SIZE[1] / 2)
            roi = (x, y, FIXED_SIZE[0], FIXED_SIZE[1])
            rois.append(roi)

            bgra = np.array(sct.grab({"left": x, "top": y, "width": FIXED_SIZE[0], "height": FIXED_SIZE[1]}))
            cv2.imwrite(os.path.join(DEBUG_DIR, f"calib_slot{slot}_red.png"), bgra[:, :, 2])
            cv2.imwrite(os.path.join(DEBUG_DIR, f"calib_slot{slot}_final.png"), preprocess_bgra(bgra))
            log(f"Slot {slot}: center=({mouse_x}, {mouse_y}) roi={roi}")
            time.sleep(0.25)

    with open(ROI_FILE, "w", encoding="utf-8") as f:
        json.dump(rois, f, indent=2)
    log(f"Saved {len(rois)} ROIs to {ROI_FILE}")


def main() -> int:
    parser = argparse.ArgumentParser(description="WASD macro worker")
    parser.add_argument("--calibrate", action="store_true", help="Calibrate the 5 screen ROIs")
    parser.add_argument("--debug", action="store_true", help="Save debug images while scanning")
    args = parser.parse_args()

    try:
        if args.calibrate:
            calibrate_rois()
        else:
            run_macro(debug=args.debug)
    except KeyboardInterrupt:
        log("Interrupted. Exiting.")
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
