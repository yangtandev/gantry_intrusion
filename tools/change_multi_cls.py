import os

# 設定標註檔案的資料夾路徑
folder_path = r"/home/gini-jyxg/annotations/construction_safety_relabel/valid/20250324/labels"

# 定義類別轉換字典
class_mapping = {0:0, 1:0, 2:0, 3:0, 4:0, 5:0 }
# class_mapping = {1:0, 2:0}

# 遍歷資料夾中的所有標註檔案
for filename in os.listdir(folder_path):
    if filename.endswith(".txt"):
        file_path = os.path.join(folder_path, filename)
        
        # 讀取標註檔案的內容
        with open(file_path, "r") as file:
            lines = file.readlines()
        
        # 修改類別
        new_lines = []
        for line in lines:
            parts = line.strip().split()
            if len(parts) > 0:
                class_id = int(parts[0])
                if class_id in class_mapping:
                    new_class_id = class_mapping[class_id]
                    parts[0] = str(new_class_id)
                    new_line = " ".join(parts)
                    new_lines.append(new_line)
        
        # 寫回修改後的內容
        with open(file_path, "w") as file:
            for line in new_lines:
                file.write(line + "\n")

print("所有標註檔案的類別修改完成！")
