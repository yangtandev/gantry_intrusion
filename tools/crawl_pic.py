import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
import requests

# 設定搜尋關鍵字與儲存路徑
query = "吊車"
output_folder = "crane_images"

if not os.path.exists(output_folder):
    os.makedirs(output_folder)

driver = webdriver.Chrome()  # 請確保已安裝 ChromeDriver
url = f"https://duckduckgo.com/?q={query}&t=h_&iax=images&ia=images"
driver.get(url)

# 模擬滾動以載入更多圖片
for _ in range(5):
    driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
    time.sleep(2)

# 抓取圖片連結
images = driver.find_elements(By.CSS_SELECTOR, "img.tile--img__img")

# 下載圖片
for index, image in enumerate(images):
    src = image.get_attribute("src")
    if src and src.startswith("http"):
        img_data = requests.get(src).content
        with open(os.path.join(output_folder, f"crane_{index}.jpg"), "wb") as f:
            f.write(img_data)

driver.quit()