"""主Pipeline模块"""
import os
import sys
import json
import cv2
import tempfile
import shutil
from typing import List, Dict, Any, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.audio_processor import audio_to_words_with_timestamps, print_words_with_timestamps
from pipeline.video_processor import split_video_by_words
from pipeline.video_preprocessor import extract_audio_and_video
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
        input_video_path: str,
        output_file: Optional[str] = None,
        keep_extracted_files: bool = False
    ) -> Dict[str, Any]:
        """
        执行完整的处理流程
        
        Args:
            input_video_path: 输入视频文件路径（支持mp4、mov等格式）
            output_file: 输出JSON文件路径，如果为None则使用默认路径
            keep_extracted_files: 是否保留提取的音频和视频文件，默认False（临时文件会被删除）
        
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
        
        # 0. 视频预处理：从视频文件中提取音频和视频
        print("\n@@@ 开始视频预处理...")
        if not os.path.exists(input_video_path):
            raise ValueError(f"输入视频文件不存在: {input_video_path}")
        
        # 提取音频和视频到临时目录或输出目录
        temp_dir = None
        if not keep_extracted_files:
            temp_dir = tempfile.mkdtemp()
            extract_dir = temp_dir
        else:
            extract_dir = output_dir
        
        audio_path, video_path = extract_audio_and_video(
            input_video_path,
            output_dir=extract_dir
        )
        
        if audio_path is None or video_path is None:
            raise ValueError("视频预处理失败：无法提取音频或视频")
        
        try:
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
            
            result_data, last_image_path = split_video_by_words(
                video_path,
                words_list,
                output_dir=frames_output_dir,
                sampling_interval=self.config.sampling_interval
            )
            
            if not result_data:
                raise ValueError("视频处理失败")
            
            if not last_image_path:
                raise ValueError("视频处理失败：未能保存最后一帧")
            
            print("\n@@@ 视频处理完成！")
            print(f"@@@ 最后一帧路径: {last_image_path}")
            
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
            # 将路径转换为相对于项目根目录的路径，以便标注工具能够正确访问
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            def get_relative_path(path):
                """获取相对于项目根目录的路径"""
                if not path:
                    return path
                try:
                    abs_path = os.path.abspath(path)
                    if abs_path.startswith(project_root):
                        return os.path.relpath(abs_path, project_root)
                    return path
                except:
                    return path
            
            pipeline_data = {
                "input_video_path": get_relative_path(input_video_path),
                "video_path": get_relative_path(video_path),
                "audio_path": get_relative_path(audio_path),
                "last_image_path": get_relative_path(last_image_path),
                "last_image_path_absolute": last_image_path,  # 保留绝对路径作为备用
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
            
        finally:
            # 清理临时文件
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    print(f"\n@@@ 已清理临时文件目录: {temp_dir}")
                except Exception as e:
                    print(f"\n@@@ 清理临时文件失败: {e}")


def main():
    """主函数示例"""
    # 创建配置
    config = Config.from_env()
    
    # 创建Pipeline
    pipeline = IntentLabelPipeline(config)
    
    # 执行处理 - 现在只需要一个视频文件路径
    # 注意：建议使用 workflow_manager.py 来运行完整的流程
    # 这里提供一个示例路径，实际使用时请替换为你的视频路径
    input_video_path = input("请输入视频文件路径（或按回车使用默认路径）: ").strip()
    
    if not input_video_path:
        # 尝试从采集工具的数据目录中查找视频
        collection_data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'tools/data_collection/datas'
        )
        # 查找第一个视频文件作为示例
        input_video_path = None
        for root, dirs, files in os.walk(collection_data_dir):
            for file in files:
                if file.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
                    input_video_path = os.path.join(root, file)
                    print(f"使用找到的视频文件: {input_video_path}")
                    break
            if input_video_path:
                break
        
        if not input_video_path:
            print("❌ 未找到视频文件，请手动指定路径")
            print("💡 提示: 使用 python workflow_manager.py 可以更方便地选择视频")
            return
    
    try:
        result = pipeline.process(input_video_path)
        print("\n✅ Pipeline执行成功！")
        print(f"📊 处理了 {len(result['objects'])} 个物品")
    except Exception as e:
        print(f"\n❌ Pipeline执行失败: {e}")
        raise


if __name__ == "__main__":
    main()

