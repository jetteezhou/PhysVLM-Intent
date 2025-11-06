"""主Pipeline模块"""
import os
import sys
import json
import cv2
from typing import List, Dict, Any, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.audio_processor import audio_to_words_with_timestamps, print_words_with_timestamps
from pipeline.video_processor import split_video_by_words
from pipeline.llm_client import LLMClient
from config.settings import Config, PIPELINE_DATA_FILE


class IntentLabelPipeline:
    """意图推理与目标定位数据标注Pipeline"""
    
    def __init__(self, config: Optional[Config] = None):
        """
        初始化Pipeline
        
        Args:
            config: 配置对象，如果为None则使用默认配置
        """
        self.config = config or Config.from_env()
        self.llm_client = LLMClient(
            api_key=self.config.openai_api_key,
            base_url=self.config.openai_base_url,
            model_video_analysis=self.config.llm_model_video_analysis,
            model_object_description=self.config.llm_model_object_description,
            model_object_location=self.config.llm_model_object_location,
            # 不同环节的API配置
            api_key_video_analysis=self.config.openai_api_key_video_analysis,
            base_url_video_analysis=self.config.openai_base_url_video_analysis,
            api_key_object_description=self.config.openai_api_key_object_description,
            base_url_object_description=self.config.openai_base_url_object_description,
            api_key_object_location=self.config.openai_api_key_object_location,
            base_url_object_location=self.config.openai_base_url_object_location,
        )
    
    def process(
        self,
        audio_path: str,
        video_path: str,
        output_file: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行完整的处理流程
        
        Args:
            audio_path: 音频文件路径
            video_path: 视频文件路径
            output_file: 输出JSON文件路径，如果为None则使用默认路径
        
        Returns:
            处理结果字典
        """
        output_file = output_file or PIPELINE_DATA_FILE
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_file)
        if not output_dir:  # 如果output_file只有文件名，没有目录部分
            output_dir = self.config.output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            print(f"创建输出目录: {output_dir}")
        
        # 1. 语音识别
        print("\n@@@ 开始语音识别...")
        success, words_list = audio_to_words_with_timestamps(
            audio_path,
            api_key=self.config.dashscope_api_key
        )
        
        if not success or not words_list:
            raise ValueError("语音识别失败")
        
        print_words_with_timestamps(words_list)
        
        # 2. 视频分割和帧采样
        print("\n@@@ 开始处理视频分割...")
        if not os.path.exists(video_path):
            raise ValueError(f"视频文件不存在: {video_path}")
        
        # 提取视频文件名（不含扩展名）作为子文件夹名
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        frames_output_dir = os.path.join(self.config.output_dir, "output_frames", video_name)
        
        result_data = split_video_by_words(
            video_path,
            words_list,
            output_dir=frames_output_dir,
            sampling_interval=self.config.sampling_interval
        )
        
        if not result_data:
            raise ValueError("视频处理失败")
        
        last_image_path = result_data[-1]['图片路径列表'][-1]
        print("\n@@@ 视频处理完成！")
        
        # 3. 分析视频意图和物品描述
        print("\n@@@ 开始分析视频意图和物品描述...")
        video_description = self.llm_client.analyze_video_intent(result_data)
        print("\n@@@ 视频描述: ", video_description)
        
        # 4. 提取物品描述
        print("\n@@@ 开始提取物品描述...")
        object_descriptions = self.llm_client.extract_object_descriptions(video_description)
        print("\n@@@ 提取的物品描述: ", object_descriptions)
        
        # 5. 定位物品并生成结果
        print("\n@@@ 开始定位物品...")
        image = cv2.imread(last_image_path)
        if image is None:
            raise ValueError(f"无法读取图像: {last_image_path}")
        
        image_height, image_width = image.shape[:2]
        objects = []
        
        for i, description in enumerate(object_descriptions):
            print(f"\n@@@ 处理物品 {i+1}: {description}")
            point_data = self.llm_client.locate_object_in_image(description, last_image_path)
            
            point = point_data['point']
            label = point_data['label']
            
            # 归一化的 [y, x] 坐标，0-1000
            point_x = int(point[1]) / 1000
            point_y = int(point[0]) / 1000
            
            # 转化为图像中的绝对像素坐标
            point_u = int(point_x * image_width)
            point_v = int(point_y * image_height)
            
            print(f"@@@ 物品point at image: ({point_u}, {point_v})")
            
            # 在图像中画出物品的中心点
            cv2.circle(image, (point_u, point_v), 8, (0, 0, 255), -1)
            
            objects.append({
                "id": i,
                "description": description,
                "point": point,  # 归一化坐标 [y, x] 0-1000
                "label": label,
                "pixel_coords": [point_u, point_v],  # 绝对像素坐标 [x, y]
                "normalized_coords": [point_x, point_y]  # 归一化坐标 [x, y] 0-1
            })
        
        # 保存标注结果图像
        result_image_path = os.path.join(output_dir, "pipeline_point_result.jpg")
        cv2.imwrite(result_image_path, image)
        print(f"\n@@@ 物品定位结果已保存到: {result_image_path}")
        
        # 6. 构建并保存结果数据
        pipeline_data = {
            "video_path": video_path,
            "last_image_path": last_image_path,
            "video_description": video_description,
            "result_data": result_data,
            "objects": objects,
            "image_dimensions": {
                "width": image_width,
                "height": image_height
            }
        }
        
        # 保存到JSON文件
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(pipeline_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n@@@ 管道数据已保存到: {output_file}")
        
        return pipeline_data


def main():
    """主函数示例"""
    # 创建配置
    config = Config.from_env()
    
    # 创建Pipeline
    pipeline = IntentLabelPipeline(config)
    
    # 执行处理
    audio_path = 'test_data/IMG_3492.mp3'
    video_path = 'test_data/IMG_3492_up.mp4'
    
    try:
        result = pipeline.process(audio_path, video_path)
        print("\n✅ Pipeline执行成功！")
        print(f"📊 处理了 {len(result['objects'])} 个物品")
    except Exception as e:
        print(f"\n❌ Pipeline执行失败: {e}")
        raise


if __name__ == "__main__":
    main()

