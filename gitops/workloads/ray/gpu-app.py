import os
import time
import logging
from ray import serve
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

logger = logging.getLogger(__name__)

@serve.deployment(
    name="gpu-deployment",
    ray_actor_options={"num_gpus": 1}
)
class TransformersDeployment:
    def __init__(self):
        model_id = os.environ.get('MODEL_ID', '/mnt/models/models/mistral-7b')
        self.model_id = model_id
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        logger.info(f"Loading model from {self.model_id} on device: {self.device}")
        print(f"Loading model from: {model_id}")
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            device_map="auto",
            local_files_only=True
        )
        
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        logger.info(f"Model loaded successfully on {self.device}")
        print(f"Model loaded successfully: {model_id}")

    async def __call__(self, request):
        try:
            data = await request.json()
            prompt = data.get("prompt", "Hello")
            max_tokens = int(data.get("max_tokens", 100))
            
            start_time = time.time()
            
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=0.7,
                    top_p=0.9,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id
                )
            
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

deployment = TransformersDeployment.bind()
