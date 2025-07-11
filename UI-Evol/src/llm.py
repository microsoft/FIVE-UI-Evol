import base64
from PIL import Image
import io
from typing import List, Union
from azure.identity import AzureCliCredential, get_bearer_token_provider
from openai import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_fixed
import numpy as np
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from azure.core.exceptions import ClientAuthenticationError
from pathlib import Path  
import mimetypes 
from config import config

class Llm:
    def __init__(self, model:str):
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_fixed(5),
            retry=retry_if_exception_type(ClientAuthenticationError)
        )
        def get_token_provider_with_retry():
            return get_bearer_token_provider(
                AzureCliCredential(), "https://cognitiveservices.azure.com/.default"
            )

        self.token_provider = get_token_provider_with_retry()
        self.model = model

    def encode_image(self, image: Union[str, Image.Image]) -> tuple[str, str]:
        if isinstance(image, str):  
            suffix = Path(image).suffix.lower()  
            mime = mimetypes.types_map.get(suffix, "image/png")  
            with open(image, "rb") as f:  
                return base64.b64encode(f.read()).decode(), mime  
        else:  
            buffer = io.BytesIO()  
            image = image.convert("RGB")  
            image.save(buffer, format="JPEG", quality=95, subsampling=0)  
            return base64.b64encode(buffer.getvalue()).decode(), "image/jpeg" 
 
    def get_base64_payload(self, b64: str, mime: str, detail="high"):  
        return {  
            "type": "image_url",  
            "image_url": {  
                "url": f"data:{mime};base64,{b64}",  
                "detail": detail,  
            },  
        }  
    
    def get_url_payload(self, url: str) -> dict:
        return {
            "type": "image_url",
            "image_url": {
                "url": url
            }
        }
    
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def process_request(self, system_prompt: str, question: str, images: Union[str, Image.Image, List[Union[str, Image.Image]]]) -> str:  

        azure_endpoint_list_4o = config.gpt4o_endpoints
        azure_endpoint_list_o3 = config.o3_endpoints

        azure_endpoint_random = ""

        if self.model == "gpt-4o-0806-global":
            azure_endpoint_random = np.random.choice(azure_endpoint_list_4o)
        elif self.model == "o3":
            azure_endpoint_random = np.random.choice(azure_endpoint_list_o3)

        self.client = AzureOpenAI(
            api_version=config.api_version,
            azure_endpoint=azure_endpoint_random,
            azure_ad_token_provider=self.token_provider
        )

        if system_prompt==None:
            system_prompt = "You are a helpful assistant."

        if images is None:
            images = []
       
        if not isinstance(images, list):  
            images = [images]  
 
        content = [{"type": "text", "text": question}]  
        for img in images:  
            b64, mime = self.encode_image(img)  
            content.append(self.get_base64_payload(b64, mime, detail="high"))  
 
        if self.model != "o1" and self.model !="o3":
            response = self.client.chat.completions.create(  
                model=self.model,  
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {  
                        "role": "user",  
                        "content": content  
                    }  
                ],
                frequency_penalty=0.0,
                n=1,
                presence_penalty=0.0,
                temperature=0,
                top_p=1.0,  
            )
        else:
            response = self.client.chat.completions.create(  
                model=self.model,  
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {  
                        "role": "user",  
                        "content": content  
                    }  
                ],
                frequency_penalty=0.0,
                n=1,
                presence_penalty=0.0,
                top_p=1.0,  
            )
            
        return response.choices[0].message.content