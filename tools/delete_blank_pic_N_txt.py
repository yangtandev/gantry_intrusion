import os

# 定義資料夾路徑
data_dir = r'/home/gini-jyxg/annotations/train2017'

# 遍歷資料夾中的所有檔案
for file_name in os.listdir(data_dir):
    if file_name.endswith('.txt'):  # 確保是txt檔案
        file_path = os.path.join(data_dir, file_name)
        
        # 檢查檔案是否為空
        if os.path.getsize(file_path) == 0:
            # 刪除空白的txt檔案
            os.remove(file_path)
            print(f'Deleted empty label file: {file_path}')
            
            # 刪除對應的圖片檔案
            image_file = os.path.splitext(file_name)[0] + '.jpg'  # 假設圖片格式為jpg
            image_path = os.path.join(data_dir, image_file)
            
            if os.path.exists(image_path):
                os.remove(image_path)
                print(f'Deleted corresponding image file: {image_path}')
            else:
                print(f'Corresponding image file not found: {image_path}')

print("完成空白txt檔案及其對應圖片的刪除")
