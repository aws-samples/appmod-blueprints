import os
from ray import serve
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.engine.async_llm_engine import AsyncLLMEngine
from vllm.sampling_params import SamplingParams
import time

@serve.deployment(
    name="mistral-deployment",
    ray_actor_options={"num_gpus": 1},
    max_concurrent_queries=100
)
class VLLMDeployment:
    def __init__(self):
        model_id = os.environ.get('MODEL_ID', 'mistralai/Mistral-7B-Instruct-v0.2')
        max_model_len = int(os.environ.get('MAX_MODEL_LEN', '8192'))
        
        # Check if model_id is a local path
        is_local = model_id.startswith('/') or os.path.exists(model_id)
        
        engine_args = AsyncEngineArgs(
            model=model_id,
            tensor_parallel_size=1,
            dtype="auto",
            gpu_memory_utilization=0.9,
            max_model_len=max_model_len,
            trust_remote_code=True,
            download_dir=None if is_local else None  # Don't download if local
        )
        
        self.engine = AsyncLLMEngine.from_engine_args(engine_args)
        self.model_id = model_id

    async def __call__(self, request):
        data = await request.json()
        prompt = data.get("prompt", "Hello")
        max_tokens = int(data.get("max_tokens", 100))
        
        start_time = time.time()
        
        sampling_params = SamplingParams(
            temperature=0.7,
            max_tokens=max_tokens,
            top_p=0.9
        )
        
        results_generator = self.engine.generate(prompt, sampling_params, request_id=f"req-{start_time}")
        
        final_output = None
        async for request_output in results_generator:
            final_output = request_output
        
        generated_text = final_output.outputs[0].text if final_output else ""
        inference_time = time.time() - start_time
        
        return {
            "prompt": prompt,
            "generated_text": generated_text,
            "inference_time_seconds": round(inference_time, 3),
            "model": self.model_id,
            "device": "cuda"
        }

deployment = VLLMDeployment.bind()
