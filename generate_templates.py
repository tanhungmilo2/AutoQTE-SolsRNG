import mss
import numpy as np
import cv2
import keyboard
import pyautogui

# Kích thước khung chụp - Bạn có thể tinh chỉnh lại (ví dụ 60x60, 70x70) 
# sao cho vừa khít với viền ngôi sao trong game
WIDTH = 64
HEIGHT = 80 

KEY_MAP = {'1': 'w', '2': 'a', '3': 's', '4': 'd'}

print("--- TOOL TẠO TEMPLATE ---")
print("1. Mở game lên.")
print("2. Di chuyển trỏ chuột vào CHÍNH GIỮA chữ cái cần chụp.")
print("3. Bấm phím số: 1 (cho W), 2 (cho A), 3 (cho S), 4 (cho D).")

with mss.mss() as sct:
    for num, letter in KEY_MAP.items():
        keyboard.wait(num)
        
        # Lấy tọa độ chuột ngay lúc bấm
        mouse_x, mouse_y = pyautogui.position()
        
        # Căn chuột vào tâm khung hình
        left = int(mouse_x - WIDTH / 2)
        top = int(mouse_y - HEIGHT / 2)
        
        capture_box = {
            "left": left, 
            "top": top, 
            "width": WIDTH, 
            "height": HEIGHT
        }
        
        # Chụp màn hình
        raw = sct.grab(capture_box)
        
        # Chuyển dữ liệu ảnh sang mảng numpy (Định dạng mặc định của mss là BGRA)
        img = np.array(raw)
        
        # BƯỚC QUAN TRỌNG: Trích xuất riêng kênh màu Đỏ (Red Channel)
        # Kênh màu: Blue=0, Green=1, Red=2
        red_channel = img[:, :, 2]
        
        # Áp dụng Thresholding (Nhị phân hóa) trực tiếp lên kênh Đỏ
        # Otsu sẽ tự động tìm ngưỡng cắt đẹp nhất để tách chữ đỏ ra khỏi nền tối
        _, thresh = cv2.threshold(red_channel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Lưu file
        cv2.imwrite(f"{letter}.png", thresh)
        print(f"[+] Đã tạo template: {letter}.png - Tâm tại ({mouse_x}, {mouse_y})")