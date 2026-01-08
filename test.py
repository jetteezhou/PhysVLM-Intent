import requests
import base64
import json
import cv2
import numpy as np
from PIL import Image
import os


def visualize_results(image, result, points=None, point_labels=None, boxes=None, box_labels=None, output_path="test.jpg"):
    """可视化 SAM3 推理结果"""
    height, width = image.shape[:2]
    vis_image = image.copy()

    # 绘制点
    if points:
        for idx, point in enumerate(points):
            if point_labels and idx < len(point_labels):
                if point_labels[idx] == 1:
                    cv2.circle(vis_image, tuple(point), 10,
                               (0, 255, 0), -1)  # 绿色，正向点
                else:
                    cv2.circle(vis_image, tuple(point), 10,
                               (0, 0, 255), -1)  # 红色，负向点
            else:
                cv2.circle(vis_image, tuple(point),
                           10, (0, 255, 0), -1)  # 默认绿色

    # 绘制边界框（输入的提示框）
    if boxes:
        for idx, box in enumerate(boxes):
            x1, y1, x2, y2 = box
            if box_labels and idx < len(box_labels):
                if box_labels[idx] == 1:
                    cv2.rectangle(vis_image, (int(x1), int(y1)),
                                  (int(x2), int(y2)), (0, 255, 0), 2)  # 绿色，正向框
                else:
                    cv2.rectangle(vis_image, (int(x1), int(y1)),
                                  (int(x2), int(y2)), (0, 0, 255), 2)  # 红色，负向框
            else:
                cv2.rectangle(vis_image, (int(x1), int(y1)),
                              (int(x2), int(y2)), (0, 255, 0), 2)  # 默认绿色

    # 处理每个结果
    colors = [
        (255, 0, 0),    # 蓝色
        (0, 255, 0),    # 绿色
        (0, 0, 255),    # 红色
        (255, 255, 0),  # 青色
        (255, 0, 255),  # 洋红色
        (0, 255, 255),  # 黄色
    ]

    for idx, res in enumerate(result.get('results', [])):
        mask_base64 = res.get('mask_base64')
        bbox = res.get('bbox')
        score = res.get('score', 0)

        if mask_base64:
            # 解码 mask
            mask_data = base64.b64decode(mask_base64)
            mask_array = np.frombuffer(mask_data, np.uint8)
            mask = cv2.imdecode(mask_array, cv2.IMREAD_GRAYSCALE)

            if mask is not None:
                # 调整 mask 尺寸以匹配原图
                if mask.shape[:2] != (height, width):
                    mask = cv2.resize(mask, (width, height))

                # 创建彩色 mask（半透明）
                mask_colored = np.zeros_like(vis_image)
                color = colors[idx % len(colors)]
                mask_colored[mask > 128] = color

                # 叠加 mask（半透明）
                vis_image = cv2.addWeighted(
                    vis_image, 0.7, mask_colored, 0.3, 0)

                # 绘制结果边界框
                if bbox:
                    x1, y1, x2, y2 = bbox
                    cv2.rectangle(vis_image, (x1, y1), (x2, y2), color, 2)

                    # 添加分数标签
                    label = f"Score: {score:.2f}"
                    cv2.putText(vis_image, label, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                print(f"结果 {idx + 1}: score={score:.3f}, bbox={bbox}")
            else:
                print(f"结果 {idx + 1}: 无法解码 mask")
        else:
            print(f"结果 {idx + 1}: 没有 mask 数据")

    # 保存可视化结果
    cv2.imwrite(output_path, vis_image)
    print(f"\n可视化结果已保存到: {output_path}")

    # 同时保存原图和 mask 的对比
    if result.get('results'):
        comparison = np.hstack([image, vis_image])
        comparison_path = output_path.replace('.jpg', '_comparison.jpg')
        cv2.imwrite(comparison_path, comparison)
        print(f"对比图已保存到: {comparison_path}")

    return vis_image


def test_with_points():
    """测试使用 points 提示"""
    print("=" * 60)
    print("测试 1: 使用 Points 提示")
    print("=" * 60)

    # 读取图片
    image_path = "face_db/zibo.jpg"
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"无法读取图片: {image_path}")

    height, width = image.shape[:2]
    print(f"图片尺寸: {width} x {height}")

    # 计算点的坐标
    center_x = width // 2
    center_y = height // 2 + 40
    positive_point = [center_x, center_y]
    positive_point2 = [center_x, center_y + 10]
    positive_point3 = [center_x, center_y - 10]

    negative_x = 30
    negative_y = height // 2
    negative_point = [negative_x, negative_y]

    send_points = [positive_point, positive_point2,
                   positive_point3, negative_point]
    send_point_labels = [1, 1, 1, 0]

    print(f"正向点: {send_points[:3]}")
    print(f"负向点: {send_points[3]}")

    # 将图片转换为 Base64
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')

    # 构造请求数据
    payload = {
        "base64_image": base64_image,
        "points": send_points,
        "point_labels": send_point_labels,
        "confidence_threshold": 0.3
    }

    # 发送 POST 请求
    # url = "http://localhost:8000/v1/models/sam3"
    url = "https://algo-pre.roboticsx.tencent.com/v1/models/sam3"
    headers = {"Content-Type": "application/json"}

    print(f"\n发送请求到: {url}")
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        print(f"请求失败，状态码: {response.status_code}")
        print(f"错误信息: {response.text}")
        raise Exception(f"请求失败: {response.text}")

    result = response.json()
    print(f"\n收到 {len(result.get('results', []))} 个结果")

    # 可视化结果
    visualize_results(image, result, points=send_points,
                      point_labels=send_point_labels, output_path="test_points.jpg")


def test_with_boxes():
    """测试使用 boxes 提示"""
    print("\n" + "=" * 60)
    print("测试 2: 使用 Boxes 提示")
    print("=" * 60)

    # 读取图片
    image_path = "face_db/zibo.jpg"
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"无法读取图片: {image_path}")

    height, width = image.shape[:2]
    print(f"图片尺寸: {width} x {height}")

    # 计算边界框坐标 [x1, y1, x2, y2]
    # 正向框：图片中心区域
    center_x = width // 2
    center_y = height // 2
    box_size = min(width, height) // 3
    positive_box = [
        center_x - box_size // 2,
        center_y - box_size // 2,
        center_x + box_size // 2,
        center_y + box_size // 2
    ]

    # 负向框：左上角区域
    negative_box = [0, 0, width // 4, height // 4]

    send_boxes = [positive_box, negative_box]
    send_box_labels = [1, 0]  # 1 为正向框，0 为负向框

    print(f"正向框: {positive_box}")
    print(f"负向框: {negative_box}")

    # 将图片转换为 Base64
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')

    # 构造请求数据
    payload = {
        "base64_image": base64_image,
        "boxes": send_boxes,
        "box_labels": send_box_labels,
        "confidence_threshold": 0.3
    }

    # 发送 POST 请求
    # url = "http://localhost:8000/v1/models/sam3"
    url = "https://algo-pre.roboticsx.tencent.com/v1/models/sam3"
    headers = {"Content-Type": "application/json"}

    print(f"\n发送请求到: {url}")
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        print(f"请求失败，状态码: {response.status_code}")
        print(f"错误信息: {response.text}")
        raise Exception(f"请求失败: {response.text}")

    result = response.json()
    print(f"\n收到 {len(result.get('results', []))} 个结果")

    # 可视化结果
    visualize_results(image, result, boxes=send_boxes,
                      box_labels=send_box_labels, output_path="test_boxes.jpg")


def test_with_points_and_boxes():
    """测试同时使用 points 和 boxes 提示"""
    print("\n" + "=" * 60)
    print("测试 3: 同时使用 Points 和 Boxes 提示")
    print("=" * 60)

    # 读取图片
    image_path = "face_db/zibo.jpg"
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"无法读取图片: {image_path}")

    height, width = image.shape[:2]
    print(f"图片尺寸: {width} x {height}")

    # 计算点的坐标
    center_x = width // 2
    center_y = height // 2
    positive_point = [center_x, center_y]

    # 计算边界框坐标
    box_size = min(width, height) // 4
    positive_box = [
        center_x - box_size,
        center_y - box_size,
        center_x + box_size,
        center_y + box_size
    ]

    send_points = [positive_point]
    send_point_labels = [1]
    send_boxes = [positive_box]
    send_box_labels = [1]

    print(f"正向点: {positive_point}")
    print(f"正向框: {positive_box}")

    # 将图片转换为 Base64
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')

    # 构造请求数据
    payload = {
        "base64_image": base64_image,
        "points": send_points,
        "point_labels": send_point_labels,
        "boxes": send_boxes,
        "box_labels": send_box_labels,
        "confidence_threshold": 0.3
    }

    # 发送 POST 请求
    # url = "http://localhost:8000/v1/models/sam3"
    url = "https://algo-pre.roboticsx.tencent.com/v1/models/sam3"
    headers = {"Content-Type": "application/json"}

    print(f"\n发送请求到: {url}")
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        print(f"请求失败，状态码: {response.status_code}")
        print(f"错误信息: {response.text}")
        raise Exception(f"请求失败: {response.text}")

    result = response.json()
    print(f"\n收到 {len(result.get('results', []))} 个结果")

    # 可视化结果
    visualize_results(image, result, points=send_points, point_labels=send_point_labels,
                      boxes=send_boxes, box_labels=send_box_labels, output_path="test_points_boxes.jpg")


if __name__ == "__main__":
    # 运行所有测试
    try:
        test_with_points()
        test_with_boxes()
        test_with_points_and_boxes()
        print("\n" + "=" * 60)
        print("所有测试完成！")
        print("=" * 60)
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
