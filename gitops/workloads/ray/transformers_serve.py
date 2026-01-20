import os
from ray import serve
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

@serve.deployment(
    name="gpu-deployment",
    ray_actor_options={"num_gpus": 1}
)
class TransformersDeployment:
    def __init__(self):
        model_id = os.environ.get('MODEL_ID', '/mnt/models/tinyllama')
        
        print(f"Loading model from: {model_id}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            device_map="auto",
            local_files_only=True
        )
        self.model_id = model_id
        print(f"Model loaded successfully: {model_id}")

    async def __call__(self, request):
        data = await request.json()
        prompt = data.get("prompt", "Hello")
        max_tokens = int(data.get("max_tokens", 100))
        
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=0.7,
                top_p=0.9,
                do_sample=True
            )
        
        generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        return {
            "prompt": prompt,
            "generated_text": generated_text,
            "model": self.model_id,
            "device": str(self.model.device)
        }

deployment = TransformersDeployment.bind()
