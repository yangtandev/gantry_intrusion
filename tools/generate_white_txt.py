import os
import sys

# 设置要检查的文件夹路径
folder_path = sys.argv[1] if len(sys.argv) > 1 else "img_log"

# 获取文件夹中的所有文件名
files = os.listdir(folder_path)

# 遍历所有文件
for file in files:
    # 检查文件是否为图片（假设图片格式为jpg、png等，可以根据实际情况添加更多格式）
    if file.lower().endswith(('.jpg', '.jpeg', '.png','.bmp')):
        # 获取文件名（不包含扩展名）
        filename_without_ext = os.path.splitext(file)[0]
        
        # 构建对应的txt文件名
        txt_filename = filename_without_ext + '.txt'
        txt_filepath = os.path.join(folder_path, txt_filename)
        
        # 检查是否存在同名的txt文件
        if not os.path.exists(txt_filepath):
            # 创建一个内容为空的txt文件
            with open(txt_filepath, 'w') as txt_file:
                pass

print("已生成缺失的空白txt文件")
