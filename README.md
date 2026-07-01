# AutoQTE-SolsRNG

An automated Python tool to instantly solve WASD QTE and escape boss stuns in Sol's RNG (Roblox).

## Description
- **Vietnamese:** Công cụ tự động nhận diện chữ cái (W, A, S, D) trên màn hình và tự động giả lập bấm phím để nhanh chóng thoát khỏi hiệu ứng khống chế (Stun) của Boss trong chế độ Hell Mode của tựa game Sol's RNG trên Roblox.
- **English:** An automated Python tool to instantly detect WASD characters on screen and automatically simulate key presses to quickly escape Boss stuns in Sol's RNG Hell Mode (Roblox).

## Dependencies
This tool requires the following Python libraries for screen capturing, image processing, and hardware-level key simulation:
- opencv-python
- numpy
- mss
- keyboard
- pyautogui
- pydirectinput

## Installation and Usage Guide

Follow these steps to set up the virtual environment and run the script on your local machine:

1. Create a virtual environment:
   `python -m venv .venv`

2. Activate the virtual environment (Windows):
   `.\.venv\Scripts\activate`

3. Install required libraries:
   `pip install -r requirements.txt`

4. Run the script:
   `python main.py`

## Setting up requirements.txt

If you haven't created the requirements file yet, create a file named `requirements.txt` in the root directory and paste the following content into it:

opencv-python
numpy
mss
keyboard
pyautogui
pydirectinput
