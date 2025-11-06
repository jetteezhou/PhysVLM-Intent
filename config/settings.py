"""配置和常量设置"""
import os
from typing import Optional

# API配置 - 默认配置
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-173e3ccde2ef4b42826a5f53b96155c2")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-proj-1234567890")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:8000/v1")

# 不同环节的API配置 - 如果为None则使用默认配置
OPENAI_API_KEY_VIDEO_ANALYSIS = os.getenv("OPENAI_API_KEY_VIDEO_ANALYSIS", None)  # 视频意图分析API密钥
OPENAI_BASE_URL_VIDEO_ANALYSIS = os.getenv("OPENAI_BASE_URL_VIDEO_ANALYSIS", None)  # 视频意图分析API URL

OPENAI_API_KEY_OBJECT_DESCRIPTION = os.getenv("OPENAI_API_KEY_OBJECT_DESCRIPTION", None)  # 物品描述提取API密钥
OPENAI_BASE_URL_OBJECT_DESCRIPTION = os.getenv("OPENAI_BASE_URL_OBJECT_DESCRIPTION", None)  # 物品描述提取API URL

OPENAI_API_KEY_OBJECT_LOCATION = os.getenv("OPENAI_API_KEY_OBJECT_LOCATION", None)  # 物品定位API密钥
OPENAI_BASE_URL_OBJECT_LOCATION = os.getenv("OPENAI_BASE_URL_OBJECT_LOCATION", None)  # 物品定位API URL

# 模型配置
ASR_MODEL = "fun-asr-realtime"

# LLM模型配置 - 不同环节使用不同的模型
LLM_MODEL_VIDEO_ANALYSIS = os.getenv("LLM_MODEL_VIDEO_ANALYSIS", "gemini-2.5-pro")  # 视频意图分析模型
LLM_MODEL_OBJECT_DESCRIPTION = os.getenv("LLM_MODEL_OBJECT_DESCRIPTION", "gemini-2.5-pro")  # 物品描述提取模型
LLM_MODEL_OBJECT_LOCATION = os.getenv("LLM_MODEL_OBJECT_LOCATION", "qwen3-vl-235b-a22b-instruct")  # 物品定位模型

# 向后兼容：保留默认模型配置
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-pro")

# 音频处理配置
AUDIO_SAMPLE_RATE = 16000
AUDIO_FORMAT = "mp3"
AUDIO_CHANNELS = 1  # 单声道

# 视频处理配置
DEFAULT_SAMPLING_INTERVAL = 300  # 毫秒
DEFAULT_OUTPUT_DIR = "pipeline/outputs"

# 输出文件配置
PIPELINE_DATA_FILE = "pipeline/outputs/pipeline_data.json"


class Config:
    """配置类"""
    
    def __init__(
        self,
        dashscope_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        openai_base_url: Optional[str] = None,
        # 不同环节的API配置
        openai_api_key_video_analysis: Optional[str] = None,
        openai_base_url_video_analysis: Optional[str] = None,
        openai_api_key_object_description: Optional[str] = None,
        openai_base_url_object_description: Optional[str] = None,
        openai_api_key_object_location: Optional[str] = None,
        openai_base_url_object_location: Optional[str] = None,
        # 模型配置
        llm_model: Optional[str] = None,
        llm_model_video_analysis: Optional[str] = None,
        llm_model_object_description: Optional[str] = None,
        llm_model_object_location: Optional[str] = None,
        sampling_interval: int = DEFAULT_SAMPLING_INTERVAL,
        output_dir: str = DEFAULT_OUTPUT_DIR,
    ):
        # 默认API配置
        default_api_key = openai_api_key or OPENAI_API_KEY
        default_base_url = openai_base_url or OPENAI_BASE_URL
        
        self.dashscope_api_key = dashscope_api_key or DASHSCOPE_API_KEY
        self.openai_api_key = default_api_key
        self.openai_base_url = default_base_url
        
        # 不同环节的API配置 - 如果为None则使用默认配置
        self.openai_api_key_video_analysis = (
            openai_api_key_video_analysis or 
            OPENAI_API_KEY_VIDEO_ANALYSIS or 
            default_api_key
        )
        self.openai_base_url_video_analysis = (
            openai_base_url_video_analysis or 
            OPENAI_BASE_URL_VIDEO_ANALYSIS or 
            default_base_url
        )
        
        self.openai_api_key_object_description = (
            openai_api_key_object_description or 
            OPENAI_API_KEY_OBJECT_DESCRIPTION or 
            default_api_key
        )
        self.openai_base_url_object_description = (
            openai_base_url_object_description or 
            OPENAI_BASE_URL_OBJECT_DESCRIPTION or 
            default_base_url
        )
        
        self.openai_api_key_object_location = (
            openai_api_key_object_location or 
            OPENAI_API_KEY_OBJECT_LOCATION or 
            default_api_key
        )
        self.openai_base_url_object_location = (
            openai_base_url_object_location or 
            OPENAI_BASE_URL_OBJECT_LOCATION or 
            default_base_url
        )
        
        # 如果提供了统一的 llm_model，则所有环节使用相同模型（向后兼容）
        if llm_model:
            self.llm_model_video_analysis = llm_model
            self.llm_model_object_description = llm_model
            self.llm_model_object_location = llm_model
        else:
            # 否则使用各自独立的配置
            self.llm_model_video_analysis = llm_model_video_analysis or LLM_MODEL_VIDEO_ANALYSIS
            self.llm_model_object_description = llm_model_object_description or LLM_MODEL_OBJECT_DESCRIPTION
            self.llm_model_object_location = llm_model_object_location or LLM_MODEL_OBJECT_LOCATION
        
        # 向后兼容：保留统一的模型配置
        self.llm_model = llm_model or LLM_MODEL
        
        self.sampling_interval = sampling_interval
        self.output_dir = output_dir
    
    @classmethod
    def from_env(cls):
        """从环境变量创建配置"""
        return cls()

