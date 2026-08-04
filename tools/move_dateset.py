import os
import shutil

# 定義來源和目標目錄
source_directory = r'/home/gini-jyxg/annotations/construction_safety_origin/valid'
target_directory = r'/home/gini-jyxg/annotations/construction_safety_check/valid/20250407'

# 確保目標目錄存在
os.makedirs(target_directory, exist_ok=True)

# 取得來源目錄中的所有檔案
files = os.listdir(source_directory)

# 分離出 jpg 和 txt 檔案名稱（不含副檔名）
jpg_files = {os.path.splitext(file)[0] for file in files if file.endswith('.jpg')}
txt_files = {os.path.splitext(file)[0] for file in files if file.endswith('.txt')}

# 取得成對的檔案名稱
paired_files = list(jpg_files & txt_files)

# 限制最多選取 100 組
paired_files = paired_files[:12]

# 移動檔案到目標目錄
for file_base in paired_files:
    jpg_path = os.path.join(source_directory, f"{file_base}.jpg")
    txt_path = os.path.join(source_directory, f"{file_base}.txt")
    shutil.move(jpg_path, target_directory)
    shutil.move(txt_path, target_directory)

print(f"已成功移動 {len(paired_files)} 組檔案到 {target_directory}")
