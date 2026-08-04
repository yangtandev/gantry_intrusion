import os

# 設定標註檔資料夾路徑
annotations_folder = r"/home/gini-jyxg/valid/labels"

# 指定要刪除的類別
# 0. 人
# 1. 自行車
# 2. 小汽車
# 3. 摩托車
# 4. 飛機
# 5. 公車
# 6. 火車
# 7. 卡車
# 8. 船
# 9. 交通燈
# 10. 消防栓
# 11. 停車標誌
# 12. 停車計時器
# 13. 長椅
# 14. 鳥
# 15. 貓
# 16. 狗
# 17. 馬
# 18. 綿羊
# 19. 牛
# 20. 大象
# 21. 熊
# 22. 斑馬
# 23. 長頸鹿
# 24. 背包
# 25. 雨傘
# 26. 手提包
# 27. 領帶
# 28. 行李箱
# 29. 飛盤
# 30. 滑雪板
# 31. 雪橇
# 32. 球類運動
# 33. 風箏
# 34. 棒球棒
# 35. 棒球手套
# 36. 滑板
# 37. 衝浪板
# 38. 網球拍
# 39. 瓶子
# 40. 酒杯
# 41. 杯子
# 42. 叉子
# 43. 刀子
# 44. 湯匙
# 45. 碗
# 46. 香蕉
# 47. 蘋果
# 48. 三明治
# 49. 橙子
# 50. 花椰菜
# 51. 胡蘿蔔
# 52. 熱狗
# 53. 比薩
# 54. 甜甜圈
# 55. 蛋糕
# 56. 椅子
# 57. 沙發
# 58. 盆栽植物
# 59. 床
# 60. 餐桌
# 61. 廁所
# 62. 電視/顯示器
# 63. 筆記本電腦
# 64. 滑鼠
# 65. 遙控器
# 66. 鍵盤
# 67. 手機
# 68. 微波爐
# 69. 烤箱
# 70. 烤麵包機
# 71. 水槽
# 72. 冰箱
# 73. 書
# 74. 鬧鐘
# 75. 花瓶
# 76. 剪刀
# 77. 泰迪熊
# 78. 吹風機
# 79. 牙刷

# 預計保留：

classes_to_delete = {
      0,  2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20 ,21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79
}
# classes_to_delete = {
#     4, 8, 9, 10, 11, 12, 17, 18, 19, 20, 21, 22, 23, 30, 31, 46, 47, 48, 49, 50, 51, 52, 54, 55, 57, 59, 60, 61, 64, 65, 67, 71, 79
# }

# 建立類別映射表，移除要刪除的類別後重新排列編號
new_class_map = {}
current_class = 0
for class_id in range(80):  # 假設原始類別範圍為 0~79
    if class_id not in classes_to_delete:
        new_class_map[class_id] = current_class
        current_class += 1

# 遍歷資料夾內的標註檔
for filename in os.listdir(annotations_folder):
    if filename.endswith(".txt"):  # 處理 .txt 文件
        file_path = os.path.join(annotations_folder, filename)
        
        # 讀取原始標註內容
        with open(file_path, "r") as file:
            lines = file.readlines()
        
        # 過濾並重新編號
        updated_lines = []
        for line in lines:
            parts = line.split()
            class_id = int(parts[0])  # 提取類別編號
            if class_id in classes_to_delete:
                continue  # 忽略需要刪除的類別
            # 將保留的類別重新編號
            new_class_id = new_class_map[class_id]
            updated_line = f"{new_class_id} " + " ".join(parts[1:]) + "\n"
            updated_lines.append(updated_line)
        
        # 如果文件變空則刪除，否則覆蓋保存
        if updated_lines:
            with open(file_path, "w") as file:
                file.writelines(updated_lines)
            print(f"已更新: {file_path}")
        else:
            os.remove(file_path)
            print(f"已刪除空文件: {file_path}")
