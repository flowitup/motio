"""Điểm vào cho engine đóng gói (PyInstaller): motio-engine engine --port 0 --token …"""
import sys

from motio.__main__ import main

if __name__ == "__main__":
    main(sys.argv[1:])
