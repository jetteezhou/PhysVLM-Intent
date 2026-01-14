import requests
import base64
import json
import cv2
import numpy as np
import os

# SAM3 API 配置
SAM3_API_URL = "https://algo-pre.roboticsx.tencent.com/v1/models/sam3"


def normalize_to_pixel(norm_points: list, width: int, height: int) -> list:
    """
    将归一化坐标 (0-1) 转换为像素坐标

    Args:
        norm_points: 归一化坐标列表 [[x, y], ...] (0-1范围)
        width: 图像宽度
        height: 图像高度

    Returns:
        像素坐标列表 [[px, py], ...]
    """
    return [[int(p[0] * width), int(p[1] * height)] for p in norm_points]


def sam3_segment_with_points(image_path: str, points: list, point_labels: list = None,
                             output_path: str = None, confidence_threshold: float = 0.3) -> dict:
    """
    使用点坐标调用 SAM3 API 进行分割

    Args:
        image_path: 图像文件路径
        points: 点坐标列表 [[x, y], ...] (像素坐标)
        point_labels: 点标签列表 [1, 1, 0, ...] (1=前景, 0=背景)，默认全为前景
        output_path: 可视化输出路径 (可选，默认在 image_path 同目录生成)
        confidence_threshold: 置信度阈值

    Returns:
        dict: {
            'success': bool,
            'mask_path': str,       # 可视化结果路径
            'results': list,        # SAM3 返回的原始结果
            'results_count': int,   # 结果数量
            'error': str            # 错误信息 (如果失败)
        }
    """
    try:
        # 读取图像
        if not os.path.exists(image_path):
            return {'success': False, 'error': f'图像文件不存在: {image_path}'}

        image = cv2.imread(image_path)
        if image is None:
            return {'success': False, 'error': f'无法读取图像: {image_path}'}

        height, width = image.shape[:2]

        # 默认所有点为前景
        if point_labels is None:
            point_labels = [1] * len(points)

        # 将图像转换为 base64
        with open(image_path, 'rb') as f:
            base64_image = base64.b64encode(f.read()).decode('utf-8')

        # 构造 SAM3 API 请求
        payload = {
            "base64_image": base64_image,
            "points": points,
            "point_labels": point_labels,
            "confidence_threshold": confidence_threshold
        }

        # 调用 SAM3 API
        headers = {"Content-Type": "application/json"}
        response = requests.post(
            SAM3_API_URL, json=payload, headers=headers, timeout=30)

        if response.status_code != 200:
            return {'success': False, 'error': f'SAM3 API 返回错误: {response.status_code}'}

        result = response.json()
        results = result.get('results', [])

        if not results:
            return {
                'success': True,
                'mask_path': None,
                'results': [],
                'results_count': 0,
                'message': '未检测到分割结果'
            }

        # 筛选逻辑：只取有点在 mask 内的 mask，且置信度最高的
        if results and points:
            valid_results = []
            for res in results:
                mask_base64 = res.get('mask_base64')
                if not mask_base64:
                    continue

                # 解码 mask
                mask_data = base64.b64decode(mask_base64)
                mask_array = np.frombuffer(mask_data, np.uint8)
                mask = cv2.imdecode(mask_array, cv2.IMREAD_GRAYSCALE)

                if mask is None:
                    continue

                # 调整尺寸以匹配原图
                if mask.shape[:2] != (height, width):
                    mask = cv2.resize(mask, (width, height))

                # 检查标注点是否在 mask 内 (阈值 128)
                # 要求所有点都在 mask 内，或者至少有一个点在 mask 内（根据需求调整）
                points_in_mask_count = 0
                total_valid_points = 0

                for point in points:
                    px, py = int(point[0]), int(point[1])
                    if 0 <= px < width and 0 <= py < height:
                        total_valid_points += 1
                        if mask[py, px] > 128:
                            points_in_mask_count += 1

                # 要求至少有一个点在 mask 内，且所有有效点中至少有一半在 mask 内
                if points_in_mask_count > 0 and (total_valid_points == 0 or points_in_mask_count >= total_valid_points / 2):
                    valid_results.append({
                        'result': res,
                        'points_in_mask': points_in_mask_count,
                        'total_points': total_valid_points
                    })

            if valid_results:
                # 优先选择包含最多点的 mask，如果相同则选择 score 最高的
                best_entry = max(valid_results, key=lambda x: (
                    x['points_in_mask'],  # 优先：包含的点数量
                    x['result'].get('score', 0)  # 其次：置信度
                ))
                best_result = best_entry['result']
                results = [best_result]
                result['results'] = results
                print(
                    f"  [筛选成功] 找到 {len(valid_results)} 个包含标注点的 Mask，已选择包含 {best_entry['points_in_mask']}/{best_entry['total_points']} 个点的 Mask (Score: {best_result.get('score', 0):.3f})")
            else:
                results = []
                result['results'] = []
                print(f"  [筛选失败] 没有 Mask 包含标注点，已过滤所有结果")
                return {
                    'success': False,
                    'error': '没有找到包含标注点的 Mask，请检查标注点位置',
                    'mask_path': None,
                    'results': [],
                    'results_count': 0
                }

        # 生成输出路径
        if output_path is None:
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            output_dir = os.path.dirname(image_path)
            output_path = os.path.join(output_dir, f"{base_name}_sam_mask.jpg")

        # 调试日志：确认传入 visualize_results 的点坐标
        print(f"  [DEBUG] 传入 visualize_results 的像素坐标: {points}")
        print(f"  [DEBUG] 图像尺寸: {width} x {height}")

        # 可视化结果（只显示与标注点最相关的第一个mask）
        vis_image = visualize_results(
            image, result,
            points=points,
            point_labels=point_labels,
            output_path=output_path,
            single_mask=True  # 只显示第一个mask，用于验证标注点是否在物体上
        )

        return {
            'success': True,
            'mask_path': output_path,
            'results': results,
            'results_count': len(results),
            'message': f'成功生成 {len(results)} 个分割结果'
        }

    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'SAM3 API 请求超时'}
    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': f'SAM3 API 请求失败: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'处理失败: {str(e)}'}


def visualize_results(image, result, points=None, point_labels=None, boxes=None, box_labels=None, output_path="test.jpg", single_mask=False):
    """
    可视化 SAM3 推理结果

    Args:
        image: 原始图像
        result: SAM3 返回的结果
        points: 点坐标列表
        point_labels: 点标签列表
        boxes: 边界框列表
        box_labels: 边界框标签列表
        output_path: 输出路径
        single_mask: 是否只显示第一个mask（与标注点最相关的那个），默认False显示所有
    """
    height, width = image.shape[:2]
    
    # 根据输出文件格式决定是否使用透明背景
    is_png = output_path and output_path.lower().endswith('.png')
    
    if is_png:
        # 创建带有 Alpha 通道的透明图像
        vis_image = np.zeros((height, width, 4), dtype=np.uint8)
        # 注意：OpenCV 的 BGR 顺序，Alpha 在第 4 位
    else:
        vis_image = image.copy()

    # 绘制点
    if points:
        for idx, point in enumerate(points):
            color = (0, 255, 0, 255) if not point_labels or (idx < len(point_labels) and point_labels[idx] == 1) else (0, 0, 255, 255)
            cv2.circle(vis_image, tuple(point), 10, color, -1)

    # 绘制边界框
    if boxes:
        for idx, box in enumerate(boxes):
            x1, y1, x2, y2 = box
            color = (0, 255, 0, 255) if not box_labels or (idx < len(box_labels) and box_labels[idx] == 1) else (0, 0, 255, 255)
            cv2.rectangle(vis_image, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)

    # 处理分割结果
    colors = [
        (255, 0, 0, 255),    # 蓝色
        (0, 255, 0, 255),    # 绿色
        (0, 0, 255, 255),    # 红色
        (255, 255, 0, 255),  # 青色
        (255, 0, 255, 255),  # 洋红色
        (0, 255, 255, 255),  # 黄色
    ]

    results_to_process = result.get('results', [])

    # 如果 single_mask=True，只处理第一个结果（与标注点最相关的那个）
    if single_mask and results_to_process:
        results_to_process = [results_to_process[0]]

    for idx, res in enumerate(results_to_process):
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

                # 如果 single_mask=True 且有标注点，只保留包含标注点的连通区域
                if single_mask and points:
                    # 二值化 mask
                    binary_mask = (mask > 128).astype(np.uint8)

                    # 连通组件分析
                    num_labels, labels = cv2.connectedComponents(binary_mask)

                    # 找到包含任意标注点的连通组件
                    valid_labels = set()
                    for point in points:
                        px, py = int(point[0]), int(point[1])
                        # 确保点在图像范围内
                        if 0 <= px < width and 0 <= py < height:
                            label_at_point = labels[py, px]
                            if label_at_point > 0:  # 0 是背景
                                valid_labels.add(label_at_point)

                    # 只保留包含标注点的连通组件
                    if valid_labels:
                        new_mask = np.zeros_like(mask)
                        for valid_label in valid_labels:
                            new_mask[labels == valid_label] = 255
                        mask = new_mask
                        print(f"  ✓ 标注点在物体上，保留 {len(valid_labels)} 个包含标注点的区域")
                        # 标注正确，用蓝色显示 mask
                        mask_color = (255, 0, 0, 255) if is_png else (255, 0, 0)  # 蓝色表示正确
                    else:
                        # 标注点不在任何 mask 区域内 - 显示 SAM3 返回的 mask，但用红色
                        print(f"  ⚠️ 警告: 标注点不在SAM检测的物体区域内！")
                        print(f"  ⚠️ SAM3返回的mask在其他位置，用红色显示对比")
                        # 保留原始 mask，但会用红色显示
                        # 在图像上添加警告文字
                        warn_color = (0, 0, 255, 255) if is_png else (0, 0, 255)
                        cv2.putText(vis_image, "WARNING: SAM3 detected different object!",
                                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, warn_color, 2)
                        cv2.putText(vis_image, "Red=SAM3 result, Green=Your click",
                                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, warn_color, 2)
                        # 标注点用绿色大圈标记
                        for point in points:
                            px, py = int(point[0]), int(point[1])
                            click_color = (0, 255, 0, 255) if is_png else (0, 255, 0)
                            cv2.circle(vis_image, (px, py), 25, click_color, 3)  # 绿色大圈=你的标注
                        # 用红色显示 SAM3 的 mask
                        mask_color = (0, 0, 255, 255) if is_png else (0, 0, 255)  # 红色表示错位
                else:
                    # 不是 single_mask 模式，使用默认颜色
                    mask_color = colors[idx % len(colors)]

                # 调试：打印 mask 信息
                mask_pixels = np.sum(mask > 128)
                print(
                    f"  [DEBUG] mask 非零像素数: {mask_pixels}, mask颜色: {mask_color}")

                # 创建彩色 mask
                if is_png:
                    # 对于 PNG，直接在 vis_image 的 mask 区域填充颜色和 alpha
                    mask_indices = mask > 128
                    # 只有在 mask 区域才设置颜色和透明度
                    # mask_color 已经是 (B, G, R, 255)
                    # 我们希望 mask 区域有 0.3 的透明度 (约 77/255)
                    c = list(mask_color)
                    c[3] = 120 # 约 0.47 透明度，与前端保持一致
                    vis_image[mask_indices] = c
                else:
                    # 对于 JPG，使用叠加方式
                    mask_colored = np.zeros_like(vis_image)
                    mask_colored[mask > 128] = mask_color[:3]
                    vis_image = cv2.addWeighted(
                        vis_image, 0.7, mask_colored, 0.3, 0)

                # 绘制结果边界框
                if bbox:
                    x1, y1, x2, y2 = bbox
                    # 确保 bbox 颜色也是 4 通道的
                    b_color = mask_color if is_png else mask_color[:3]
                    cv2.rectangle(vis_image, (x1, y1), (x2, y2), b_color, 2)

                    # 添加分数标签
                    label = f"Score: {score:.2f}"
                    # 文本背景
                    if is_png:
                        cv2.putText(vis_image, label, (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, b_color, 2)
                    else:
                        cv2.putText(vis_image, label, (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, b_color, 2)

                print(f"结果 {idx + 1}: score={score:.3f}, bbox={bbox}")
            else:
                print(f"结果 {idx + 1}: 无法解码 mask")
        else:
            print(f"结果 {idx + 1}: 没有 mask 数据")

    # 保存可视化结果
    cv2.imwrite(output_path, vis_image)
    print(f"\n可视化结果已保存到: {output_path}")

    # 同时保存原图和 mask 的对比（只在非 single_mask 模式下）
    if result.get('results') and not single_mask:
        # 处理 4 通道图像以便与原图合并
        vis_to_show = vis_image
        if vis_image.shape[2] == 4:
            # 如果是透明背景，将其叠加到原图上进行对比
            vis_to_show = image.copy()
            mask_indices = vis_image[:, :, 3] > 0
            # 使用 alpha 混合
            alpha = vis_image[mask_indices, 3:4] / 255.0
            vis_to_show[mask_indices] = (vis_image[mask_indices, :3] * alpha + 
                                         vis_to_show[mask_indices] * (1 - alpha)).astype(np.uint8)
        
        comparison = np.hstack([image, vis_to_show])
        comparison_path = output_path.replace('.png', '_comparison.png').replace('.jpg', '_comparison.jpg')
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
