import json
import os

# 路徑配置
coco_annotation_file = r'/home/gini-jyxg/annotations/construction_safety_origin/train/_annotations.coco.json'
output_dir = r'/home/gini-jyxg/annotations/construction_safety_origin/train'
os.makedirs(output_dir, exist_ok=True)

# 讀取 COCO 標註文件
with open(coco_annotation_file, 'r') as f:
    coco_data = json.load(f)

# 建立類別映射字典和連續的類別 ID 對應
categories = coco_data['categories']
category_map = {category['id']: category['name'] for category in categories}
category_id_map = {category['id']: i for i, category in enumerate(categories)}

# 解析圖像資訊
images = coco_data['images']
image_map = {image['id']: image for image in images}

# 處理每個標註並生成 YOLO 格式文件
for annotation in coco_data['annotations']:
    image_id = annotation['image_id']
    category_id = annotation['category_id']
    bbox = annotation['bbox']

    # 檢查類別 ID 是否存在於 category_id_map 中
    if category_id not in category_id_map:
        continue  # 如果 ID 不在範圍內，跳過

    # 將 COCO 類別 ID 轉換為連續的 YOLO 類別 ID
    yolo_category_id = category_id_map[category_id]

    # 獲取圖像資訊
    image_info = image_map[image_id]
    img_width = image_info['width']
    img_height = image_info['height']

    # 計算 YOLO 格式的座標
    x_min, y_min, bbox_width, bbox_height = bbox
    center_x = (x_min + bbox_width / 2) / img_width
    center_y = (y_min + bbox_height / 2) / img_height
    yolo_width = bbox_width / img_width
    yolo_height = bbox_height / img_height

    # YOLO 格式行
    yolo_annotation = f"{yolo_category_id} {center_x} {center_y} {yolo_width} {yolo_height}\n"

    # 輸出文件路徑
    yolo_file_path = os.path.join(output_dir, f"{os.path.splitext(image_info['file_name'])[0]}.txt")

    # 將標註寫入 YOLO 文件
    with open(yolo_file_path, 'a') as yolo_file:
        yolo_file.write(yolo_annotation)

print("Conversion completed.")