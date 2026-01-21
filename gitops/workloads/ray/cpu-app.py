import os
import ray
from ray import serve
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import time
import logging

logger = logging.getLogger(__name__)

@serve.deployment
class TextGenerator:
    def __init__(self, model_id: str = None, max_length: int = 100):
        # Get model path from environment or use default
        self.model_id = model_id or os.environ.get('MODEL_ID', '/mnt/models/models/tinyllama')
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Loading model from {self.model_id} on device: {self.device}")
        
        # Load model and tokenizer from local path (S3-mounted)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            torch_dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
            device_map="auto" if self.device.type == "cuda" else None,
            local_files_only=True  # Only use local files, no HuggingFace download
        )
        
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
            
        self.max_length = max_length
        logger.info(f"Model loaded successfully on {self.device}")

    async def __call__(self, request):
        try:
            data = await request.json()
            prompt = data.get("prompt", "Hello, how are you?")
            max_tokens = int(data.get("max_tokens", self.max_length))
            
            start_time = time.time()
            
            # Tokenize input
            inputs = self.tokenizer.encode(prompt, return_tensors="pt").to(self.device)
            
            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs,
                    max_length=inputs.shape[1] + max_tokens,
                    num_return_sequences=1,
                    temperature=0.7,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id
                )
            
            # Decode response
            response_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            generated_text = response_text[len(prompt):].strip()
            
            inference_time = time.time() - start_time
            
            return {
                "prompt": prompt,
                "generated_text": generated_text,
                "inference_time_seconds": round(inference_time, 3),
                "device_used": str(self.device),
                "gpu_available": torch.cuda.is_available(),
                "model_device": str(next(self.model.parameters()).device),
                "model_path": self.model_id
            }
            
        except Exception as e:
            logger.error(f"Error during inference: {str(e)}")
            return {
                "error": str(e),
                "device_used": str(self.device),
                "gpu_available": torch.cuda.is_available(),
                "model_path": self.model_id
            }

# Create deployment
deployment = TextGenerator.bind()
