from ultralytics.models.sam import SAM2VideoPredictor
import os
import sys
import cv2
import numpy as np
from pydub import AudioSegment

# 获取项目根目录路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# Create SAM2VideoPredictor
MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "sam2.1_b.pt")
overrides = dict(conf=0.25, task="segment", mode="predict", imgsz=1024, model=MODEL_PATH)
predictor = SAM2VideoPredictor(overrides=overrides)

source = os.path.join(PROJECT_ROOT, "test_data", "IMG_3492_down.mp4") 

# # Run inference with single point
# results = predictor(source="IMG_3491.mp4", points=[920, 470], labels=[1])

# Run inference with multiple points
results = predictor(source=source, points=[[1000, 750], [1000, 300]], labels=[1, 1])

# # Run inference with multiple points prompt per object
# results = predictor(source="IMG_3491.mp4", points=[[[900, 800], [900, 300]]], labels=[[1, 1]])

# # Run inference with negative points prompt
# results = predictor(source="test.mp4", points=[[[920, 470], [909, 138]]], labels=[[1, 0]])

print("Results length: ", len(results))
print("Results[0].boxes.xywh: ", results[0].boxes.xywh)
# tensor([[902., 788., 220., 188.],
#         [905., 375., 166., 282.]]

save_dir = os.path.join(PROJECT_ROOT, "runs", "segment")
save_path = sorted(os.listdir(save_dir))[-1]
video_filename = os.path.basename(source).replace(".mp4", ".avi")
result_video_path = os.path.join(save_dir, save_path, video_filename)
print("Result video path: ", result_video_path)

out = cv2.VideoWriter(result_video_path.replace(".avi", "_with_lines.mp4"), cv2.VideoWriter_fourcc(*'mp4v'), 30, (1920, 1080))
up_video_path = os.path.join(PROJECT_ROOT, "test_data", "IMG_3492_up.mp4")

print("write up video")
cap = cv2.VideoCapture(up_video_path)
while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break
    out.write(frame)
cap.release()

print("write down video with lines")
# 逐帧读取视频，并且把两个框的中心点连线用红色虚线画出来，并重新保存为视频
cap = cv2.VideoCapture(result_video_path)
index = 0
while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break
    bbox1_center = (int(results[index].boxes.xywh[0][0]), int(results[index].boxes.xywh[0][1]))
    bbox2_center = (int(results[index].boxes.xywh[1][0]), int(results[index].boxes.xywh[1][1]))
    cv2.line(frame, bbox1_center, bbox2_center, (0, 0, 255), 2)
    index += 1
    # 保存为视频
    out.write(frame)

cap.release()
out.release()

# 使用 ffmpeg 将音频和视频合并
import subprocess
audio_path = os.path.join(PROJECT_ROOT, "test_data", "IMG_3492.mp3")
video_without_audio = result_video_path.replace(".avi", "_with_lines.mp4")
final_video_path = result_video_path.replace(".avi", "_with_lines_and_audio.mp4")

print(f"Merging audio and video using ffmpeg...")
print(f"Video: {video_without_audio}")
print(f"Audio: {audio_path}")
print(f"Output: {final_video_path}")

# 使用 ffmpeg 合并音频和视频
subprocess.run([
    "ffmpeg", "-y",  # -y 表示覆盖输出文件
    "-i", video_without_audio,  # 输入视频文件
    "-i", audio_path,  # 输入音频文件
    "-c:v", "copy",  # 复制视频流，不重新编码
    "-c:a", "aac",  # 音频编码为 AAC
    "-shortest",  # 以最短的流为准
    final_video_path
], check=True)

print(f"Final video with audio saved to: {final_video_path}")
