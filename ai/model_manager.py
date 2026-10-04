"""AI Model Manager for local models, hardware detection, quantization, and cloud fallbacks."""
import os
import gc
import json
import time
import httpx
import psutil
from typing import Dict, Any, Optional, Tuple
from config import settings
from logger import get_logger
from core.exceptions import ModelLoadError

logger = get_logger("ai.model_manager")

class ModelManager:
    """Manages AI model lifecycle, hardware resources, inference, and provider routing."""
    
    def __init__(self):
        self.device = "cpu"
        self.gpu_name = None
        self.vram_mb = 0
        self.ram_mb = 0
        self.model = None
        self.tokenizer = None
        self.is_loaded = False
        self.current_model_id = settings.LOCAL_MODEL_ID
        self.last_latency_ms = 0.0
        self._detect_hardware()
        
    def _detect_hardware(self) -> None:
        """Detect CPU, RAM, and GPU/VRAM."""
        mem = psutil.virtual_memory()
        self.ram_mb = int(mem.total / (1024 * 1024))
        
        try:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
                self.gpu_name = torch.cuda.get_device_name(0)
                self.vram_mb = int(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024))
                logger.info(f"GPU detected: {self.gpu_name} ({self.vram_mb} MB VRAM)")
            else:
                self.device = "cpu"
                logger.info(f"Running on CPU ({self.ram_mb} MB RAM)")
        except ImportError:
            self.device = "cpu"
            logger.info("Torch not imported yet. Defaulting hardware detection to CPU.")

        # Auto-model selection if enabled
        if settings.AUTO_MODEL:
            self.current_model_id = self.select_auto_model()

    def select_auto_model(self) -> str:
        """Select appropriate model ID based on available hardware."""
        if self.device == "cuda" and self.vram_mb >= 14000:
            return "Qwen/Qwen2.5-Coder-7B-Instruct"
        elif self.device == "cuda" and self.vram_mb >= 6000:
            return "Qwen/Qwen2.5-Coder-1.5B-Instruct"
        elif self.ram_mb >= 12000:
            return "Qwen/Qwen2.5-Coder-1.5B-Instruct"
        else:
            return "Qwen/Qwen2.5-Coder-0.5B-Instruct"

    def get_hardware_status(self) -> Dict[str, Any]:
        """Return real hardware and model status metrics."""
        vm = psutil.virtual_memory()
        status = {
            "device": self.device,
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_total_mb": self.ram_mb,
            "ram_used_mb": int(vm.used / (1024 * 1024)),
            "ram_percent": vm.percent,
            "gpu_name": self.gpu_name,
            "vram_mb": self.vram_mb,
            "vram_used_mb": 0,
            "model_id": self.current_model_id,
            "is_loaded": self.is_loaded,
            "provider": settings.AI_PROVIDER,
            "last_latency_ms": round(self.last_latency_ms, 2)
        }
        
        try:
            import torch
            if self.device == "cuda" and torch.cuda.is_available():
                status["vram_used_mb"] = int(torch.cuda.memory_allocated(0) / (1024 * 1024))
        except Exception:
            pass
            
        return status

    def load_model(self, model_id: Optional[str] = None) -> bool:
        """Lazily load the Hugging Face transformer model."""
        target_model = model_id or self.current_model_id or "Qwen/Qwen2.5-Coder-0.5B-Instruct"
        logger.info(f"Loading AI model '{target_model}' on {self.device}...")
        
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            
            hf_token = settings.HF_TOKEN
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                target_model,
                token=hf_token,
                trust_remote_code=True
            )
            
            torch_dtype = torch.float16 if self.device == "cuda" else torch.float32
            
            self.model = AutoModelForCausalLM.from_pretrained(
                target_model,
                torch_dtype=torch_dtype,
                device_map="auto" if self.device == "cuda" else None,
                token=hf_token,
                trust_remote_code=True,
                low_cpu_mem_usage=True
            )
            
            if self.device == "cpu":
                self.model = self.model.to("cpu")
                
            self.model.eval()
            self.is_loaded = True
            self.current_model_id = target_model
            logger.info(f"AI model '{target_model}' loaded successfully.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load local model '{target_model}': {e}")
            self.is_loaded = False
            self.model = None
            self.tokenizer = None
            return False

    def unload_model(self) -> bool:
        """Unload local model from memory."""
        logger.info("Unloading AI model from memory...")
        self.model = None
        self.tokenizer = None
        self.is_loaded = False
        gc.collect()
        
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
            
        logger.info("AI model unloaded.")
        return True

    async def generate(self, prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> str:
        """Generate response based on configured provider (local, HF inference, Groq, etc.)."""
        start_time = time.time()
        provider = settings.AI_PROVIDER.lower()
        
        try:
            if provider == "local":
                # Check if model is loaded in memory
                if self.is_loaded:
                    return self._generate_local(prompt, max_tokens, temperature)
                else:
                    logger.info("Local model not loaded in memory. Attempting HF Inference API with HF_TOKEN...")
                    try:
                        return await self._generate_hf_inference(prompt, max_tokens)
                    except Exception as e:
                        logger.warning(f"HF Inference API call failed: {e}. Falling back to deterministic engine.")
                        raise ModelLoadError(f"Local model not loaded and cloud inference failed: {e}")
                
            elif provider == "huggingface_inference":
                return await self._generate_hf_inference(prompt, max_tokens)
                
            elif provider == "groq":
                return await self._generate_groq(prompt, max_tokens, temperature)
                
            elif provider in ("custom_openai", "openrouter"):
                return await self._generate_openai_compatible(prompt, max_tokens, temperature)
                
            else:
                logger.warning(f"Unknown provider '{provider}', attempting HF inference.")
                return await self._generate_hf_inference(prompt, max_tokens)
                
        finally:
            self.last_latency_ms = (time.time() - start_time) * 1000

    def _generate_local(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Run inference on loaded local model."""
        import torch
        
        inputs = self.tokenizer(prompt, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature if temperature > 0 else 0.01,
                do_sample=temperature > 0,
                pad_token_id=self.tokenizer.eos_token_id
            )
            
        # Decode only newly generated tokens
        input_len = inputs["input_ids"].shape[1]
        generated_tokens = outputs[0][input_len:]
        return self.tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()

    async def _generate_hf_inference(self, prompt: str, max_tokens: int) -> str:
        """Query Hugging Face Inference API / Serverless Router."""
        hf_token = settings.HF_TOKEN
        model_name = self.current_model_id or "Qwen/Qwen2.5-Coder-1.5B-Instruct"
        api_url = f"https://api-inference.huggingface.co/models/{model_name}"
        
        headers = {}
        if hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"
            
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": 0.2,
                "return_full_text": False
            }
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(api_url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0 and "generated_text" in data[0]:
                    return data[0]["generated_text"].strip()
                elif isinstance(data, dict) and "generated_text" in data:
                    return data["generated_text"].strip()
            
            logger.warning(f"HF Inference API returned status {resp.status_code}: {resp.text}")
            raise ModelLoadError(f"HF Inference error ({resp.status_code}): {resp.text}")

    async def _generate_groq(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Query Groq API if configured."""
        if not settings.GROQ_API_KEY:
            raise ModelLoadError("GROQ_API_KEY is not configured.")
            
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    async def _generate_openai_compatible(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Query Custom OpenAI or OpenRouter endpoint."""
        api_key = settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY
        if not api_key:
            raise ModelLoadError("API key for OpenAI / OpenRouter not configured.")
            
        base_url = "https://openrouter.ai/api/v1/chat/completions" if settings.OPENROUTER_API_KEY else "https://api.openai.com/v1/chat/completions"
        model = "qwen/qwen-2.5-coder-32b-instruct" if settings.OPENROUTER_API_KEY else "gpt-4o-mini"
        
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

# Global model manager instance
model_manager = ModelManager()
