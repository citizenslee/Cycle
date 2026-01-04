# auto_main.py
import time
from datetime import datetime
import devices_events_auto
import available_staff  # <--- 1. 导入新模块

SCAN_INTERVAL = 10

print("自动化服务启动")

while True:
    try:
        # 现有的设备扫描任务
        devices_events_auto.run_device_event_scan()
        
        # <--- 2. 加入人员扫描任务
        available_staff.scan_available_staff()
        
    except Exception as e:
        print(f"Main Loop Error: {e}")

    time.sleep(SCAN_INTERVAL)