"""LLM客户端模块"""
import re
import openai
from typing import List, Dict, Any, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.image_utils import image_to_base64
from config.settings import (
    LLM_MODEL,
    LLM_MODEL_VIDEO_ANALYSIS,
    LLM_MODEL_OBJECT_DESCRIPTION,
    LLM_MODEL_OBJECT_LOCATION
)


class LLMClient:
    """LLM客户端封装类"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: Optional[str] = None,
        model_video_analysis: Optional[str] = None,
        model_object_description: Optional[str] = None,
        model_object_location: Optional[str] = None,
        # 不同环节的API配置
        api_key_video_analysis: Optional[str] = None,
        base_url_video_analysis: Optional[str] = None,
        api_key_object_description: Optional[str] = None,
        base_url_object_description: Optional[str] = None,
        api_key_object_location: Optional[str] = None,
        base_url_object_location: Optional[str] = None,
    ):
        """
        初始化LLM客户端
        
        Args:
            api_key: OpenAI API密钥（默认配置）
            base_url: API基础URL（默认配置）
            model: 统一模型名称（向后兼容，如果提供则所有环节使用相同模型）
            model_video_analysis: 视频意图分析模型
            model_object_description: 物品描述提取模型
            model_object_location: 物品定位模型
            api_key_video_analysis: 视频意图分析API密钥（如果为None则使用默认api_key）
            base_url_video_analysis: 视频意图分析API URL（如果为None则使用默认base_url）
            api_key_object_description: 物品描述提取API密钥（如果为None则使用默认api_key）
            base_url_object_description: 物品描述提取API URL（如果为None则使用默认base_url）
            api_key_object_location: 物品定位API密钥（如果为None则使用默认api_key）
            base_url_object_location: 物品定位API URL（如果为None则使用默认base_url）
        """
        # 默认客户端（向后兼容）
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        
        # 不同环节的客户端配置 - 如果为None则使用默认配置
        self.client_video_analysis = openai.OpenAI(
            api_key=api_key_video_analysis or api_key,
            base_url=base_url_video_analysis or base_url,
        )
        
        self.client_object_description = openai.OpenAI(
            api_key=api_key_object_description or api_key,
            base_url=base_url_object_description or base_url,
        )
        
        self.client_object_location = openai.OpenAI(
            api_key=api_key_object_location or api_key,
            base_url=base_url_object_location or base_url,
        )
        
        # 如果提供了统一的 model，则所有环节使用相同模型（向后兼容）
        if model:
            self.model_video_analysis = model
            self.model_object_description = model
            self.model_object_location = model
        else:
            # 否则使用各自独立的配置
            self.model_video_analysis = model_video_analysis or LLM_MODEL_VIDEO_ANALYSIS
            self.model_object_description = model_object_description or LLM_MODEL_OBJECT_DESCRIPTION
            self.model_object_location = model_object_location or LLM_MODEL_OBJECT_LOCATION
        
        # 向后兼容：保留统一的模型配置
        self.model = model or LLM_MODEL
    
    def analyze_video_intent(self, result_data: List[Dict[str, Any]]) -> str:
        """
        分析视频意图和物品描述
        
        Args:
            result_data: 视频处理结果数据
        
        Returns:
            视频描述文本
        """
        message = self._build_video_analysis_message(result_data)
        response = self.client_video_analysis.chat.completions.create(
            model=self.model_video_analysis,
            messages=message
        )
        return response.choices[0].message.content
    
    def extract_object_descriptions(self, video_description: str) -> List[str]:
        """
        从视频描述中提取物品描述
        
        Args:
            video_description: 视频描述文本
        
        Returns:
            物品描述列表（最多2个）
        """
        message = self._build_object_description_message(video_description)
        response = self.client_object_description.chat.completions.create(
            model=self.model_object_description,
            messages=message
        )
        
        content = response.choices[0].message.content
        match_group = re.findall(r'<description>(.*?)</description>', content)
        return match_group
    
    def locate_object_in_image(
        self,
        object_description: str,
        image_path: str
    ) -> Dict[str, Any]:
        """
        在图像中定位物品
        
        Args:
            object_description: 物品描述
            image_path: 图像文件路径
        
        Returns:
            包含point和label的字典
        """
        message = self._build_object_point_message(object_description, image_path)
        response = self.client_object_location.chat.completions.create(
            model=self.model_object_location,
            messages=message
        )
        
        content = response.choices[0].message.content.replace("```json", "").replace("```", "")
        point_data_json = re.search(r'\{.*\}', content, re.DOTALL)
        
        if point_data_json:
            import json
            return json.loads(point_data_json.group())
        else:
            raise ValueError(f"无法解析LLM响应: {content}")
    
    def _build_video_analysis_message(self, result_data: List[Dict[str, Any]]) -> List[Dict]:
        """构建视频分析消息"""
        message = [{
            "role": "system",
            "content": "你是一个专业的视频分析师，根据视频内容，分析视频中的人物的意图和动作，并分析视频中任务意图所涉及的物品详细描述。"
        }]
        
        for item in result_data:
            word = item['词汇']
            image_paths = item['图片路径列表']
            message.append({
                "role": "user",
                "content": [{"type": "text", "text": "\n" + word + ":"}]
            })
            
            for image_path in image_paths:
                base64_image = image_to_base64(image_path)
                if base64_image:
                    message[-1]['content'].append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                    })
        
        return message
    
    def _build_object_description_message(self, video_description: str) -> List[Dict]:
        """构建物品描述提取消息"""
        message = [{
            "role": "system",
            "content": "你是一个专业的语义结构提取专家，根据对视频的描述文本内容，提取出人物意图所涉及到的2个物品的最有辨识度的简洁描述。按照以下格式返回：<description>物品1的简洁描述</description><description>物品2的简洁描述</description>"
        }]
        message.append({
            "role": "user",
            "content": [{"type": "text", "text": video_description}]
        })
        return message
    
    def _build_object_point_message(self, object_description: str, image_path: str) -> List[Dict]:
        """构建物品定位消息"""
        prompt = (
            f"Point to object: {object_description} in the image. The label returned should be an identifying name for the object detected."
            """The answer should follow the json format: {"point": <point>, "label": <label>}. The point is in [y, x] format normalized to 0-1000."""
        )
        
        base64_image = image_to_base64(image_path)
        if not base64_image:
            raise ValueError(f"无法读取图像: {image_path}")
        
        message = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                }
            ]
        }]
        return message

