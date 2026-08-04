import os
import shutil
import random
import sys

# 定義源資料夾和目標資料夾
source_folder = sys.argv[1] if len(sys.argv) > 1 else "img_log"
train_images_folder = os.path.join(source_folder, 'train', 'images')
train_labels_folder = os.path.join(source_folder, 'train', 'labels')
val_images_folder = os.path.join(source_folder, 'valid', 'images')
val_labels_folder = os.path.join(source_folder, 'valid', 'labels')

# 確保目標資料夾存在，如果不存在，則創建它們
for folder in [train_images_folder, train_labels_folder, val_images_folder, val_labels_folder]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# 獲取所有圖片文件和對應的標註文件
file_pairs = []
for file_name in os.listdir(source_folder):
    if file_name.endswith('.jpg') or file_name.endswith('.png')or file_name.endswith('.bmp'):
        img_path = os.path.join(source_folder, file_name)
        label_path = os.path.join(source_folder, file_name.replace('.jpg', '.txt').replace('.png', '.txt'))
        
        if os.path.isfile(img_path) and os.path.isfile(label_path):
            file_pairs.append((img_path, label_path))

# 隨機打亂文件對
random.shuffle(file_pairs)

# 限制文件數量，如果文件不足，則使用全部文件
# file_pairs = file_pairs[:5000]

# 計算分配的索引
split_index = int(0.8 * len(file_pairs))

# 將文件對分配到訓練集和驗證集
train_pairs = file_pairs[:split_index]
val_pairs = file_pairs[split_index:]

# 定義複製文件的函數
def copy_files(file_pairs, img_target_folder, label_target_folder):
    for img_path, label_path in file_pairs:
        shutil.copy(img_path, os.path.join(img_target_folder, os.path.basename(img_path)))
        shutil.copy(label_path, os.path.join(label_target_folder, os.path.basename(label_path)))

# 複製訓練集文件
copy_files(train_pairs, train_images_folder, train_labels_folder)

# 複製驗證集文件
copy_files(val_pairs, val_images_folder, val_labels_folder)

print(f"訓練集文件數量: {len(train_pairs)}")
print(f"驗證集文件數量: {len(val_pairs)}")
