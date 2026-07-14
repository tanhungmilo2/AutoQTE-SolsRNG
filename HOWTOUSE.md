ENG:
# Environment Setup & Calibration Guide (Alternate Display Configurations)

Due to display discrepancies between the target environment (1920x1200, 125% scaling) and the host environment (1920x1080, 100% scaling), utilizing pre-existing templates (`slot1_w.png`, `slot1_a.png`, `slot1_s.png`, `slot1_d.png`) and the `rois.json` configuration is **not supported** — in-game UI elements will render at different pixel dimensions on your screen, meaning the reference templates will no longer align.

Please execute the following procedure in order (Estimated time: **2 minutes**):

## Step 1 — Environment Initialization & Dependencies
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Step 2 — Local Template Generation
Launch the game environment and execute:
```bash
python generate_templates.py
```
- Position your cursor precisely over the **center** of the letter W in-game → press `1`
- Center of A → press `2`
- Center of S → press `3`
- Center of D → press `4`

This process generates four local files: `w.png`, `a.png`, `s.png`, and `d.png` in the directory. Rename (or duplicate) these files to `slot1_w.png`, `slot1_a.png`, `slot1_s.png`, and `slot1_d.png` — overwriting the existing assets in the repository.

## Step 3 — Region of Interest (ROI) Calibration
```bash
python main.py --calibrate
```
- Position the cursor over the center of **Slot 1** → press `1`, **Slot 2** → press `2`... up to **Slot 5**
- The system will automatically generate and save a localized `rois.json` configuration.

## Step 4 — Pre-Execution Diagnostics
```bash
python diagnose_v2.py
```
This diagnostic script renders the captured screenshot alongside the reference template, allowing you to instantly verify alignment and identify configuration errors prior to live execution.

## Step 5 — System Execution
```bash
python macro_hub.py
```
Press the `E` key (default hotkey) to trigger the recognition sequence.

---
### Troubleshooting: Recognition Failures (Low Confidence Score / `[unknown]`)
If the system fails to recognize inputs, inspect the output files within the `debug/` directory (specifically the `..._2_otsu.png` files) — if the characters do not resolve to distinct, sharp white shapes on a black background, in-game lighting or boss visual effects (VFX) may be introducing noise into the red channel. Please provide the affected debug images so that the `CONFIDENCE_THRESHOLD` and `MARGIN_THRESHOLD` parameters in `main.py` can be adjusted accordingly.
















VIE:
# Hướng dẫn cài tool trên máy khác (độ phân giải / scale khác)

Vì máy bạn (1920x1200, scale 125%) khác máy chủ (1920x1080, scale 100%),
**không thể** copy y nguyên `slot1_w.png`, `slot1_a.png`, `slot1_s.png`,
`slot1_d.png` và `rois.json` sang dùng — chữ W/A/S/D trong game sẽ hiện
với kích thước pixel khác trên màn hình bạn, nên các ảnh mẫu (template)
cũ sẽ không khớp nữa.

Làm theo đúng thứ tự bên dưới, chỉ mất khoảng 2 phút:

## Bước 1 — Cài thư viện
```
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Bước 2 — Tạo template CHO RIÊNG MÁY BẠN
Mở game, chạy:
```
python generate_templates.py
```
- Di chuyển chuột vào **chính giữa** chữ W trong game → bấm phím `1`
- Chính giữa chữ A → bấm `2`
- Chính giữa chữ S → bấm `3`
- Chính giữa chữ D → bấm `4`

Xong sẽ có 4 file `w.png`, `a.png`, `s.png`, `d.png` trong thư mục.
Đổi tên (hoặc copy) 4 file này thành `slot1_w.png`, `slot1_a.png`,
`slot1_s.png`, `slot1_d.png` — ghi đè lên file cũ trong repo.

## Bước 3 — Calibrate ROI CHO RIÊNG MÁY BẠN
```
python main.py --calibrate
```
- Hover chuột vào giữa slot 1 → bấm `1`, slot 2 → bấm `2`... đến slot 5
- Xong sẽ tự lưu ra `rois.json` mới

## Bước 4 — Kiểm tra trước khi chạy thật
```
python diagnose_v2.py
```
File này show song song ảnh chụp thật vs template, giúp thấy ngay nếu
còn lệch/sai trước khi bấm phím thật trong lúc chơi.

## Bước 5 — Chạy tool
```
python macro_hub.py
```
Bấm phím `E` (hotkey mặc định) để trigger nhận diện.

---
### Nếu vẫn không nhận được (score thấp/`[unknown]`)
Mở vài ảnh trong thư mục `debug/` (đặc biệt file `..._2_otsu.png`) —
nếu chữ cái không rõ nét màu trắng trên nền đen, có thể do hiệu ứng
ánh sáng/VFX của boss làm nhiễu kênh đỏ. Báo lại ảnh đó để chỉnh
`CONFIDENCE_THRESHOLD` / `MARGIN_THRESHOLD` trong `main.py` cho phù hợp.
