import os

directory = r'/home/gini-jyxg/annotations/valid'  # 替換為目標目錄路徑

# 取得目錄中的所有檔案
files = os.listdir(directory)

# 分離出 jpg 和 txt 檔案
jpg_files = {os.path.splitext(file)[0] for file in files if file.endswith('.jpg')}
txt_files = {os.path.splitext(file)[0] for file in files if file.endswith('.txt')}

# 找出沒有匹配的 jpg 檔案
unmatched_jpgs = jpg_files - txt_files

# 刪除無法匹配的 jpg 檔案
for unmatched in unmatched_jpgs:
    jpg_path = os.path.join(directory, unmatched + '.jpg')
    os.remove(jpg_path)
    print(f"Deleted: {jpg_path}")

print("Done!")

