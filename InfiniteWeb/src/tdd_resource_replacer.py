"""
TDD Resource Replacer Module (formerly Image Replacer)

Replaces placeholder resources (images, audio, video, files) with real resources from various APIs:
- Images: Pexels API (primary) / Pixabay API (fallback)
- Audio: Freesound API
- Video: YouTube API
- Files: Google Search API (PDFs)
"""

import os
import json
import re
import random
import asyncio
import aiohttp
import requests
import base64
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import urlencode
from tdd_logger_module import TDDLogger
from llm_caller import call_openai_api_json
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential


@dataclass
class ResourceReplacement:
    """Single resource replacement record"""
    original_url: str
    resource_type: str  # "image", "audio", "video", "file"
    search_query: str
    new_url: str


@dataclass
class DataResourceResult:
    """Data resource replacement result"""
    updated_data: Dict[str, Any]
    replacements: List[ResourceReplacement]


@dataclass
class PageResourceResult:
    """Page resource replacement result"""
    updated_pages: Dict[str, str]  # filename -> html
    replacements: Dict[str, List[ResourceReplacement]]  # filename -> replacements


class TDDResourceReplacer:
    """
    Replaces placeholder resources (images, audio, video, files) with real resources from search services
    """
    
    # Resource type detection patterns
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico'}
    AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.wma'}
    VIDEO_EXTENSIONS = {'.mp4', '.webm', '.avi', '.mov', '.wmv', '.flv', '.mkv'}
    FILE_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.csv'}
    
    def __init__(self, logger: TDDLogger = None,
                 pexels_api_key: str = None,
                 freesound_api_key: str = None,
                 youtube_api_key: str = None,
                 google_api_key: str = None,
                 google_cse_cx: str = None,
                 image_mode: str = None,
                 output_dir: str = None,
                 model: str = None,
                 reasoning_effort: str = "medium",
                 local_image_search_url: str = None,
                 local_image_search_dataset: str = None,
                 local_image_search_min_resolution: int = None):
        """
        Initialize the Resource Replacer

        Args:
            logger: TDDLogger instance
            pexels_api_key: Pexels API key (for images) - deprecated, using local search
            freesound_api_key: Freesound API key (for audio)
            youtube_api_key: YouTube API key (for video)
            google_api_key: Google API key (for file search)
            google_cse_cx: Google Custom Search Engine ID
            image_mode: "Real" for search-based images, "Generate" for AI-generated images (from config)
            output_dir: Output directory for generated content
            model: Model to use for LLM calls
            reasoning_effort: Reasoning effort level
            local_image_search_url: Local image search service URL
            local_image_search_dataset: Dataset to use (lr, hr, or all)
            local_image_search_min_resolution: Minimum resolution filter
        """
        self.logger = logger or TDDLogger()
        self.image_mode = image_mode or "Real"  # Default to Real if not specified
        self.output_dir = output_dir or "results/generated"
        self.model = model
        self.reasoning_effort = reasoning_effort

        # Local image search settings
        self.local_image_search_url = local_image_search_url or "http://localhost:8001"
        self.local_image_search_sas = os.environ.get("IMAGE_SEARCH_SAS_TOKEN", "")
        self.local_image_search_dataset = local_image_search_dataset or "all"
        self.local_image_search_min_resolution = local_image_search_min_resolution or 600

        # Image API (kept for fallback/compatibility but not used by default)
        self.pexels_api_key = pexels_api_key
        self.pexels_url = "https://api.pexels.com/v1/search"

        # Azure OpenAI for image generation (configure via config or environment)
        self.azure_openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        self.azure_openai_deployment = "gpt-image-1"
        self.azure_openai_api_version = "2025-04-01-preview"

        # Audio API
        self.freesound_api_key = freesound_api_key
        self.freesound_url = "https://freesound.org/apiv2"

        # Video APIs
        self.youtube_api_key = youtube_api_key
        self.youtube_url = "https://www.googleapis.com/youtube/v3/search"
        self.pexels_video_url = "https://api.pexels.com/videos/search"  # Reuse pexels_api_key

        # File Search API
        self.google_api_key = google_api_key
        self.google_cse_cx = google_cse_cx
        self.google_cse_url = "https://customsearch.googleapis.com/customsearch/v1"

        # Check image API is available based on mode
        # Note: For "Real" mode, we use local image search service, no API key required
        if self.image_mode == "Generate" and not self.azure_openai_endpoint:
            error_msg = "❌ Azure OpenAI endpoint is required for 'Generate' image mode."
            self.logger.log_error(error_msg)
            raise ValueError(error_msg)

    def _get_azure_token(self) -> str:
        """
        Get Azure AD access token for Azure OpenAI / Cognitive Services

        Returns:
            Access token string
        """
        scope = "https://cognitiveservices.azure.com/.default"

        # Try multiple credential methods
        errors = []
        for cred in [
            # DefaultAzureCredential tries environment variables, Managed Identity, Azure CLI, etc.
            DefaultAzureCredential(exclude_shared_token_cache_credential=True),
            # Fallback to interactive browser login for local development
            InteractiveBrowserCredential()
        ]:
            try:
                token = cred.get_token(scope)
                return token.token
            except Exception as e:
                errors.append(repr(e))

        raise RuntimeError(
            "Failed to get Azure AD access token. Please ensure you are logged in and have access to Cognitive Services OpenAI.\n"
            + "\n".join(errors)
        )

    def _detect_resource_type(self, url: str) -> str:
        """
        Detect resource type from URL or extension
        
        Args:
            url: Resource URL
            
        Returns:
            Resource type: "image", "audio", "video", "file", or "unknown"
        """
        url_lower = url.lower()
        
        # Check by extension
        for ext in self.IMAGE_EXTENSIONS:
            if ext in url_lower:
                return "image"
        for ext in self.AUDIO_EXTENSIONS:
            if ext in url_lower:
                return "audio"
        for ext in self.VIDEO_EXTENSIONS:
            if ext in url_lower:
                return "video"
        for ext in self.FILE_EXTENSIONS:
            if ext in url_lower:
                return "file"
        
        # Check common patterns
        if any(pattern in url_lower for pattern in ['image', 'img', 'photo', 'picture', 'avatar', 'logo', 'icon']):
            return "image"
        if any(pattern in url_lower for pattern in ['audio', 'sound', 'music', 'song']):
            return "audio"
        if any(pattern in url_lower for pattern in ['video', 'movie', 'clip']):
            return "video"
        if any(pattern in url_lower for pattern in ['document', 'file', 'pdf']):
            return "file"
        
        return "unknown"

    async def _search_local_images(self, query: str, width: int = 800, height: int = 600) -> Optional[str]:
        """
        Search for image using local Elasticsearch service.
        Progressively lowers resolution requirement if no results found.

        Args:
            query: Search query
            width: Desired width
            height: Desired height

        Returns:
            Image URL from local search service or None
        """
        try:
            # Use configured min_resolution as baseline, but increase if requesting larger images
            base_min_resolution = self.local_image_search_min_resolution
            if width > 800 or height > 800:
                initial_min_resolution = max(base_min_resolution, max(width, height))
            else:
                initial_min_resolution = base_min_resolution

            # Progressive resolution fallback: try configured -> 400 -> 0 (no limit)
            resolution_attempts = [initial_min_resolution]
            if initial_min_resolution > 400:
                resolution_attempts.append(400)
            if initial_min_resolution > 0:
                resolution_attempts.append(0)
            # Remove duplicates while preserving order
            resolution_attempts = list(dict.fromkeys(resolution_attempts))

            search_url = f"{self.local_image_search_url}/search"
            headers = {}
            if self.local_image_search_sas:
                headers["ServiceBusAuthorization"] = self.local_image_search_sas

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                for min_resolution in resolution_attempts:
                    try:
                        params = {
                            "q": query,
                            "top_k": 5,
                            "dataset": self.local_image_search_dataset or "all",
                        }
                        if min_resolution > 0:
                            params["min_resolution"] = min_resolution
                        async with session.get(search_url, params=params, headers=headers) as response:
                            if response.status == 200:
                                data = await response.json()
                                results = data.get("results", [])
                                if results:
                                    url = results[0].get("url")
                                    if url:
                                        if min_resolution != initial_min_resolution:
                                            self.logger.log_info(f"  ✅ Found image via local search for '{query}' (lowered min_resolution to {min_resolution})")
                                        else:
                                            self.logger.log_info(f"  ✅ Found image via local search for '{query}'")
                                        return url
                                # No results at this resolution, try lower
                                continue
                            else:
                                self.logger.log_error(f"  ❌ Local search API returned status {response.status}")
                                return None
                    except asyncio.TimeoutError:
                        self.logger.log_warning(f"  ⏱️ Timeout searching local service for '{query}'")
                        return None
                    except Exception as e:
                        self.logger.log_warning(f"  ⚠️ Error searching local service for '{query}': {str(e)}")
                        return None

                # Exhausted all resolution attempts
                self.logger.log_warning(f"  ⚠️ No results from local search for '{query}' (tried resolutions: {resolution_attempts})")
                return None
        except Exception as e:
            self.logger.log_error(f"  ❌ Local image search failed for '{query}': {str(e)}")
            return None

    async def _search_pexels(self, query: str, width: int = 800, height: int = 600) -> Optional[str]:
        """
        Search for image on Pexels (primary image API)

        Args:
            query: Search query
            width: Desired width
            height: Desired height

        Returns:
            Image URL from Pexels or None
        """
        if not self.pexels_api_key:
            return None

        try:
            headers = {"Authorization": self.pexels_api_key}
            params = {
                "query": query,
                "per_page": 5,
                "orientation": "landscape" if width > height else "portrait" if height > width else "square"
            }

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                try:
                    async with session.get(self.pexels_url, headers=headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            photos = data.get("photos", [])
                            if photos:
                                photo = photos[0]
                                src = photo.get("src", {})
                                # Choose appropriate size
                                if width <= 640:
                                    url = src.get("medium") or src.get("large") or src.get("original")
                                elif width <= 1280:
                                    url = src.get("large") or src.get("original")
                                else:
                                    url = src.get("original") or src.get("large")
                                self.logger.log_info(f"  ✅ Found image on Pexels for '{query}'")
                                return url
                            else:
                                self.logger.log_warning(f"  ⚠️ No results on Pexels for '{query}'")
                                return None
                        else:
                            self.logger.log_error(f"  ❌ Pexels API returned status {response.status}")
                            return None
                except asyncio.TimeoutError:
                    self.logger.log_warning(f"  ⏱️ Timeout searching Pexels for '{query}'")
                    return None
                except Exception as e:
                    self.logger.log_warning(f"  ⚠️ Error searching Pexels for '{query}': {str(e)}")
                    return None
        except Exception as e:
            self.logger.log_error(f"  ❌ Pexels search failed for '{query}': {str(e)}")
            return None

    async def _search_pexels_with_fallback(self, query: str, width: int = 800, height: int = 600) -> Optional[str]:
        """
        Search for image on Pexels with multi-level fallback strategy

        Args:
            query: Search query
            width: Desired width
            height: Desired height

        Returns:
            Image URL from Pexels (always returns a valid URL due to fallback)
        """
        # First try the original query
        self.logger.log_info(f"  🔍 Searching Pexels for '{query}'...")
        result = await self._search_pexels(query, width, height)
        if result:
            return result

        # If original query failed, try each word separately
        words = query.split()
        if len(words) > 1:
            self.logger.log_info(f"  📝 Original search failed, trying individual words from '{query}'...")
            for word in words:
                word = word.strip()
                if word:  # Skip empty strings
                    self.logger.log_info(f"  🔍 Trying fallback search for '{word}'...")
                    result = await self._search_pexels(word, width, height)
                    if result:
                        self.logger.log_info(f"  ✅ Found image using fallback word '{word}'")
                        return result

        # Final fallback: search for "banana"
        self.logger.log_info(f"  🍌 All searches failed, using final fallback 'banana'...")
        result = await self._search_pexels("banana", width, height)
        if result:
            self.logger.log_info(f"  ✅ Found image using final fallback 'banana'")
            return result

        # This should rarely happen unless API is completely down
        self.logger.log_error(f"  ❌ Even 'banana' search failed, API might be down")
        return None

    async def _generate_image_azure(self, query: str, width: int = 800, height: int = 600) -> Optional[str]:
        """
        Generate image using Azure OpenAI

        Args:
            query: Search query to use as prompt
            width: Desired width
            height: Desired height

        Returns:
            Local path to generated image or None
        """
        try:
            # Map requested size to Azure supported sizes
            # Azure supports: 1024x1024, 1024x1536, 1536x1024
            if width > height * 1.2:
                # Wide image
                size = "1536x1024"
            elif height > width * 1.2:
                # Tall image
                size = "1024x1536"
            else:
                # Square or nearly square
                size = "1024x1024"

            # Get Azure AD token
            token = self._get_azure_token()

            # Prepare API request
            url = f"{self.azure_openai_endpoint.rstrip('/')}/openai/deployments/{self.azure_openai_deployment}/images/generations"
            params = {"api-version": self.azure_openai_api_version}
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }
            payload = {
                "prompt": query,
                "size": size,
                "quality": "medium",
                "n": 1,
                "output_format": "png",
                "output_compression": 100
            }

            self.logger.log_info(f"  🎨 Generating image with Azure OpenAI for '{query}' (size: {size})")

            # Make synchronous request (since we're in async context, use asyncio's run_in_executor)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, params=params, headers=headers, json=payload, timeout=180)
            )

            if response.status_code == 200:
                data = response.json()
                images = data.get("data", [])

                if images and "b64_json" in images[0]:
                    # Decode base64 image
                    b64_data = images[0]["b64_json"]
                    img_bytes = base64.b64decode(b64_data)

                    # Create directory for generated images using output_dir
                    images_dir = os.path.join(self.output_dir, "generated_images")
                    os.makedirs(images_dir, exist_ok=True)

                    # Generate unique filename
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_query = re.sub(r'[^a-zA-Z0-9_-]', '_', query[:50])
                    filename = f"{safe_query}_{timestamp}.png"
                    filepath = os.path.join(images_dir, filename)

                    # Save image
                    with open(filepath, "wb") as f:
                        f.write(img_bytes)

                    # Return relative path for HTML usage
                    relative_path = f"generated_images/{filename}"
                    self.logger.log_info(f"  ✅ Generated image saved to {relative_path}")
                    return relative_path
                else:
                    self.logger.log_warning(f"  ⚠️ No image data in Azure response for '{query}'")
                    return None
            else:
                error_msg = response.text
                self.logger.log_error(f"  ❌ Azure OpenAI API returned status {response.status_code}: {error_msg}")
                return None

        except Exception as e:
            self.logger.log_error(f"  ❌ Azure image generation failed for '{query}': {str(e)}")
            return None

    async def _search_freesound(self, query: str, is_fallback: bool = False) -> Optional[str]:
        """
        Search for audio on Freesound with fallback to country music

        Args:
            query: Search query
            is_fallback: Whether this is a fallback search (to prevent infinite recursion)

        Returns:
            Audio URL from Freesound or None
        """
        if not self.freesound_api_key:
            self.logger.log_warning("  ⚠️ Freesound API key not configured")
            return None

        try:
            url = f"{self.freesound_url}/search/text/"
            params = {
                "query": query,
                "page_size": 5,
                "fields": "id,name,previews,url,license,duration,username"
            }
            headers = {
                "Authorization": f"Token {self.freesound_api_key}",
                "User-Agent": "TDD-Resource-Replacer/1.0"
            }

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                try:
                    async with session.get(url, params=params, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get("results", [])
                            if results:
                                # Randomly select from results instead of always first
                                item = random.choice(results)
                                previews = item.get("previews", {})
                                # Prefer mp3, then ogg
                                audio_url = (previews.get("preview-hq-mp3") or
                                           previews.get("preview-lq-mp3") or
                                           previews.get("preview-hq-ogg") or
                                           previews.get("preview-lq-ogg"))
                                if audio_url:
                                    if is_fallback:
                                        self.logger.log_info(f"  ✅ Found audio on Freesound using fallback 'country music' (original query: '{query}')")
                                    else:
                                        self.logger.log_info(f"  ✅ Found audio on Freesound for '{query}'")
                                    return audio_url

                            # No results found - try fallback if not already a fallback search
                            if not is_fallback:
                                self.logger.log_warning(f"  ⚠️ No audio results for '{query}', trying fallback with 'country music'")
                                return await self._search_freesound("country music", is_fallback=True)
                            else:
                                self.logger.log_warning(f"  ⚠️ No audio results even with fallback query 'country music'")
                                return None
                        else:
                            self.logger.log_error(f"  ❌ Freesound API returned status {response.status}")
                            # Try fallback on API error if not already a fallback
                            if not is_fallback:
                                self.logger.log_info(f"  Trying fallback with 'country music' due to API error")
                                return await self._search_freesound("country music", is_fallback=True)
                            return None
                except asyncio.TimeoutError:
                    self.logger.log_warning(f"  ⏱️ Timeout searching Freesound for '{query}'")
                    # Try fallback on timeout if not already a fallback
                    if not is_fallback:
                        self.logger.log_info(f"  Trying fallback with 'country music' due to timeout")
                        return await self._search_freesound("country music", is_fallback=True)
                    return None
                except Exception as e:
                    self.logger.log_warning(f"  ⚠️ Error searching Freesound: {str(e)}")
                    # Try fallback on any error if not already a fallback
                    if not is_fallback:
                        self.logger.log_info(f"  Trying fallback with 'country music' due to error")
                        return await self._search_freesound("country music", is_fallback=True)
                    return None
        except Exception as e:
            self.logger.log_error(f"  ❌ Freesound search failed: {str(e)}")
            # Final fallback attempt
            if not is_fallback:
                self.logger.log_info(f"  Trying fallback with 'country music' due to search failure")
                return await self._search_freesound("country music", is_fallback=True)
            return None
    
    async def _search_pexels_video(self, query: str) -> Optional[str]:
        """
        Search for video on Pexels (returns direct MP4 links for <video> tags)
        
        Args:
            query: Search query
            
        Returns:
            Direct MP4 video URL from Pexels or None
        """
        if not self.pexels_api_key:
            self.logger.log_warning("  ⚠️ Pexels API key not configured")
            return None
            
        try:
            headers = {"Authorization": self.pexels_api_key}
            params = {
                "query": query,
                "per_page": 5
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                try:
                    async with session.get(self.pexels_video_url, headers=headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            videos = data.get("videos", [])
                            if videos:
                                video = videos[0]
                                video_files = video.get("video_files", [])
                                
                                # Prefer 720p MP4, then any MP4
                                file_url = None
                                for f in video_files:
                                    if f.get("file_type") == "video/mp4" and f.get("height") == 720:
                                        file_url = f.get("link")
                                        break
                                
                                # Fallback to first available video file
                                if not file_url and video_files:
                                    file_url = video_files[0].get("link")
                                
                                if file_url:
                                    self.logger.log_info(f"  ✅ Found video on Pexels for '{query}'")
                                    return file_url
                            
                            self.logger.log_warning(f"  ⚠️ No video results on Pexels for '{query}'")
                            return None
                        else:
                            self.logger.log_error(f"  ❌ Pexels Video API returned status {response.status}")
                            return None
                except asyncio.TimeoutError:
                    self.logger.log_warning(f"  ⏱️ Timeout searching Pexels Video for '{query}'")
                    return None
                except Exception as e:
                    self.logger.log_warning(f"  ⚠️ Error searching Pexels Video: {str(e)}")
                    return None
        except Exception as e:
            self.logger.log_error(f"  ❌ Pexels Video search failed: {str(e)}")
            return None
    
    async def _search_youtube(self, query: str) -> Optional[str]:
        """
        Search for video on YouTube (returns embed URLs for <iframe> tags)
        
        Args:
            query: Search query
            
        Returns:
            YouTube embed URL or None
        """
        if not self.youtube_api_key:
            self.logger.log_warning("  ⚠️ YouTube API key not configured")
            return None
            
        try:
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 5,
                "key": self.youtube_api_key,
                "videoEmbeddable": "true"  # Only get embeddable videos
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                try:
                    async with session.get(self.youtube_url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            items = data.get("items", [])
                            if items:
                                video_id = items[0].get("id", {}).get("videoId")
                                if video_id:
                                    # Return embed URL format for iframe
                                    embed_url = f"https://www.youtube.com/embed/{video_id}"
                                    self.logger.log_info(f"  ✅ Found video on YouTube for '{query}'")
                                    return embed_url
                            self.logger.log_warning(f"  ⚠️ No video results for '{query}'")
                            return None
                        else:
                            self.logger.log_error(f"  ❌ YouTube API returned status {response.status}")
                            return None
                except asyncio.TimeoutError:
                    self.logger.log_warning(f"  ⏱️ Timeout searching YouTube for '{query}'")
                    return None
                except Exception as e:
                    self.logger.log_warning(f"  ⚠️ Error searching YouTube: {str(e)}")
                    return None
        except Exception as e:
            self.logger.log_error(f"  ❌ YouTube search failed: {str(e)}")
            return None
    
    async def _search_google_files(self, query: str, file_type: str = "pdf") -> Optional[str]:
        """
        Search for files (PDFs) using Google Custom Search with fallback

        Args:
            query: Search query
            file_type: File type to search (default: pdf)

        Returns:
            File URL or fallback URL
        """
        # Fallback URL for when search fails
        FALLBACK_PDF_URL = "https://arxiv.org/pdf/2404.07972"

        if not self.google_api_key or not self.google_cse_cx:
            self.logger.log_warning("  ⚠️ Google Search API not configured, using fallback PDF")
            return FALLBACK_PDF_URL

        try:
            params = {
                "key": self.google_api_key,
                "cx": self.google_cse_cx,
                "q": query,
                "fileType": file_type,
                "num": 5,
                "hl": "en"
            }

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                try:
                    async with session.get(self.google_cse_url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            items = data.get("items", [])
                            if items:
                                file_url = items[0].get("link")
                                if file_url:
                                    self.logger.log_info(f"  ✅ Found {file_type} file for '{query}'")
                                    return file_url
                            self.logger.log_warning(f"  ⚠️ No {file_type} results for '{query}', using fallback PDF")
                            return FALLBACK_PDF_URL
                        else:
                            self.logger.log_error(f"  ❌ Google API returned status {response.status}, using fallback PDF")
                            return FALLBACK_PDF_URL
                except asyncio.TimeoutError:
                    self.logger.log_warning(f"  ⏱️ Timeout searching Google for '{query}', using fallback PDF")
                    return FALLBACK_PDF_URL
                except Exception as e:
                    self.logger.log_warning(f"  ⚠️ Error searching Google: {str(e)}, using fallback PDF")
                    return FALLBACK_PDF_URL
        except Exception as e:
            self.logger.log_error(f"  ❌ Google search failed: {str(e)}, using fallback PDF")
            return FALLBACK_PDF_URL
    
    async def _search_resource(self, resource_type: str, query: str, width: int = None, height: int = None) -> Optional[str]:
        """
        Search for a resource based on its type

        Args:
            resource_type: Type of resource (image, audio, video, iframe_video, file)
            query: Search query
            width: Width for images (optional)
            height: Height for images (optional)

        Returns:
            Resource URL or None
        """
        if resource_type == "image":
            # Use image mode to determine source
            if self.image_mode == "Generate":
                return await self._generate_image_azure(query, width or 800, height or 600)
            else:  # "Real" mode - use local image search
                return await self._search_local_images(query, width or 800, height or 600)
        elif resource_type == "audio":
            return await self._search_freesound(query)
        elif resource_type == "video":
            # Direct video files for <video> tags
            return await self._search_pexels_video(query)
        elif resource_type == "iframe_video":
            # YouTube embed URLs for <iframe> tags
            return await self._search_youtube(query)
        elif resource_type == "file":
            return await self._search_google_files(query, "pdf")
        else:
            self.logger.log_warning(f"  ⚠️ Unknown resource type: {resource_type}")
            return None
    
    def _identify_data_resources(self, data: Dict[str, Any], website_type: str) -> List[Dict[str, Any]]:
        """
        Use LLM to identify all types of resources in data

        Args:
            data: Website data dictionary
            website_type: Type of website

        Returns:
            List of identified resources with descriptions and types
        """

        prompt = f"""You are analyzing data for a {website_type} website. Identify ALL media resources (images, audio, video, documents) and generate search queries.

RESOURCE TYPES TO IDENTIFY:
1. IMAGES: jpg, png, gif, webp, svg, or fields like image, img, photo, picture, avatar, logo, icon, banner, thumbnail, cover
2. AUDIO: mp3, wav, ogg, m4a, or fields like audio, sound, music, song, track, podcast
3. VIDEO (direct files): mp4, webm, avi, mov, or fields like video, movie, clip - use type "video"
4. IFRAME_VIDEO (streaming): YouTube URLs, Vimeo, or fields like stream, tutorial, demo_video - use type "iframe_video"
5. FILES: pdf, doc, xls, ppt, or fields like document, file, report, whitepaper, ebook, guide

RULES:
1. Check ALL fields that might contain media URLs
2. Identify placeholder services: picsum.photos, placeholder.com, unsplash.com, dummyimage.com, example.com
3. Detect resource type from URL extension or field name
4. Generate specific, contextual search queries
5. IMPORTANT: Distinguish between "video" (needs direct MP4 link) and "iframe_video" (needs YouTube/streaming embed)

For each resource:
1. Determine the resource type (image/audio/video/iframe_video/file)
2. Analyze context to create relevant search query
3. For images: include dimensions if available
4. For audio: focus on background music, effects, or ambient sounds
5. For video: focus on stock footage, backgrounds (will get direct MP4 links)
6. For iframe_video: focus on tutorials, demonstrations, explanations (will get YouTube embeds)
7. For files: always search for PDFs regardless of original extension

IMAGE SIZE CATEGORY (for images only):
For each image, determine its size_category:
- "large": ONLY full-width background images, hero banners that span the entire viewport width, or page-level decorative backgrounds
- "small": ALL other images - product images, thumbnails, avatars, icons, logos, cover images, card images, list images, profile pictures, etc.

Return JSON format:
{{
    "resources": [
        {{"url": "https://example.com/hero-bg.jpg", "type": "image", "description": "hero background cityscape", "width": 1920, "height": 800, "size_category": "large"}},
        {{"url": "https://example.com/product.jpg", "type": "image", "description": "product photo laptop", "width": 800, "height": 600, "size_category": "small"}},
        {{"url": "https://example.com/bg-music.mp3", "type": "audio", "description": "background music upbeat corporate"}},
        {{"url": "https://example.com/background.mp4", "type": "video", "description": "nature landscape background"}},
        {{"url": "https://youtube.com/watch?v=xxx", "type": "iframe_video", "description": "tutorial how to use product"}},
        {{"url": "https://example.com/guide.pdf", "type": "file", "description": "user guide manual documentation"}}
    ]
}}

Data to analyze:
{json.dumps(data, indent=2)}"""

        messages = [{"role": "user", "content": prompt}]

        call_id = self.logger.log_api_call(
            api_name="Identify Data Resources",
            prompt=prompt
        )

        result, usage_info = call_openai_api_json(messages, model=self.model, reasoning_effort=self.reasoning_effort)

        if isinstance(result, str):
            result = json.loads(result)

        self.logger.log_api_response(
            api_name="Identify Data Resources",
            success=True,
            response=result,
            usage_info=usage_info,
            call_id=call_id
        )

        return result.get("resources", [])
    
    def _identify_page_resources(self, html: str, page_name: str) -> List[Dict[str, Any]]:
        """
        Use LLM to identify static resources in HTML

        Args:
            html: HTML content
            page_name: Name of the page

        Returns:
            List of static resources to replace
        """

        prompt = f"""Analyze this HTML page ({page_name}) and identify ONLY STATIC resources that need replacement.

RESOURCE TYPES TO IDENTIFY:
1. IMAGES: static image link, like "https://placeholder.com/1200x400"
2. AUDIO: static audio link, like "audio/background.mp3"
3. VIDEO: static video link in <video> tags, <source> tags with video types (mp4, webm) - use type "video"
4. IFRAME_VIDEO: static video link in <iframe> tags with YouTube/Vimeo URLs - use type "iframe_video"
5. FILES: static file links (only with type of pdf, doc, xls) - use type "file"

**CRITICAL**:
1. Identify ONLY STATIC resources links that can be replaced with real content.
2. File Type should Exclude business_logic.js , css files, font links(e.g., "https://fonts.gstatic.com"), html files, svg files .

EXCLUDE these resources:
- Resources with dynamic data binding (${{...}}, template syntax)
- Resources inside loops or data templates
- Resources with empty src/href (will be filled by JS)
- Resources referencing variables or properties

For each static resource:
1. Identify the type (image/audio/video/iframe_video/file)
2. Extract the complete URL (src, href, etc.)
3. Generate a descriptive search query based on context
4. For images: include width/height if available
5. IMPORTANT: Distinguish between:
   - "video": <video> tags needing direct MP4 links (stock footage, backgrounds)
   - "iframe_video": <iframe> tags needing YouTube embeds (tutorials, demonstrations)

IMAGE SIZE CATEGORY (for images only):
For each image, determine its size_category:
- "large": ONLY full-width background images, hero banners that span the entire viewport width, or page-level decorative backgrounds
- "small": ALL other images - product images, thumbnails, avatars, icons, logos, cover images, card images, list images, profile pictures, etc.

Return JSON format:
{{
    "resources": [
        {{"src": "https://placeholder.com/1920x800", "type": "image", "description": "hero background cityscape", "width": 1920, "height": 800, "size_category": "large"}},
        {{"src": "https://placeholder.com/400x300", "type": "image", "description": "product card image laptop", "width": 400, "height": 300, "size_category": "small"}},
        {{"src": "audio/background.mp3", "type": "audio", "description": "ambient background music relaxing"}},
        {{"src": "videos/background.mp4", "type": "video", "description": "nature landscape background video"}},
        {{"src": "https://www.youtube.com/embed/dQw4w9WgXcQ", "type": "iframe_video", "description": "tutorial product demonstration"}},
        {{"src": "docs/guide.pdf", "type": "file", "description": "user guide manual pdf"}}
    ]
}}

HTML to analyze:
{html}"""

        messages = [{"role": "user", "content": prompt}]
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                api_name="Identify Page Resources",
                prompt=prompt,
                additional_args={"page_name": page_name}
            )

        try:
            result, usage_info = call_openai_api_json(messages, model=self.model, reasoning_effort=self.reasoning_effort)

            if isinstance(result, str):
                result = json.loads(result)

            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    api_name="Identify Page Resources",
                    success=True,
                    response=result,
                    usage_info=usage_info,
                    call_id=call_id
                )

            return result.get("resources", [])
            
        except Exception as e:
            # Log failed API response
            if self.logger:
                self.logger.log_api_response(
                    api_name="Identify Page Resources",
                    success=False,
                    error=str(e),
                    call_id=call_id
                )
            raise
    
    async def replace_data_resources(self, data: Dict[str, Any], website_type: str) -> DataResourceResult:
        """
        Replace all types of resources in website data
        
        Args:
            data: Website data dictionary
            website_type: Type of website
            
        Returns:
            DataResourceResult with updated data and replacements
        """
        self.logger.start_stage("Replace Data Resources", "backend")
        self.logger.log_info(f"🎯 Starting data resource replacement for {website_type}...")
        
        # Identify resources
        resources_to_replace = self._identify_data_resources(data, website_type)
    
        
        if not resources_to_replace:
            self.logger.log_info("No resources found in data to replace")
            return DataResourceResult(updated_data=data, replacements=[])
        
        # Count by type
        type_counts = {}
        for res in resources_to_replace:
            res_type = res.get('type', 'unknown')
            type_counts[res_type] = type_counts.get(res_type, 0) + 1
        
        self.logger.log_info(f"Found {len(resources_to_replace)} resources to replace: {type_counts}")
        
        # Build path map to locate images in nested structure
        path_map = {}
        
        def build_paths(obj, parent_path=[]):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if isinstance(value, str) and value.startswith(('http://', 'https://')):
                        path_map[value] = (obj, key)
                    else:
                        build_paths(value, parent_path + [key])
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    build_paths(item, parent_path + [i])
        
        build_paths(data)
        
        # Replace resources asynchronously
        replacements = []

        for res_info in resources_to_replace:
            url = res_info.get('url', '')
            res_type = res_info.get('type', 'unknown')
            description = res_info.get('description', 'placeholder')
            width = res_info.get('width') or 0
            height = res_info.get('height') or 0

            if url in path_map:
                obj, key = path_map[url]

                # Search and replace for all images (no small/large distinction)
                new_url = await self._search_resource(res_type, description, width, height)

                if new_url is not None:
                    obj[key] = new_url

                    replacement = ResourceReplacement(
                        original_url=url,
                        resource_type=res_type,
                        search_query=description,
                        new_url=new_url
                    )
                    replacements.append(replacement)
                    self.logger.log_info(f"  Replaced {res_type}: {url[:50]}... -> {new_url[:50]}...")
                else:
                    # Keep original URL when search fails
                    self.logger.log_warning(f"  Skipped {res_type}: {url[:50]}... (search failed, keeping original)")

        # Summary by type
        replaced_counts = {}
        for repl in replacements:
            replaced_counts[repl.resource_type] = replaced_counts.get(repl.resource_type, 0) + 1

        self.logger.log_info(f"✅ Replaced {len(replacements)} resources: {replaced_counts}")
        self.logger.end_stage("Replace Data Resources")

        return DataResourceResult(updated_data=data, replacements=replacements)
    
    async def replace_page_resources_async(self, pages: Dict[str, str], website_type: str) -> PageResourceResult:
        """
        Replace static resources in HTML pages (async)
        
        Args:
            pages: Dictionary of filename -> HTML content
            website_type: Type of website
            
        Returns:
            PageResourceResult with updated pages and replacements
        """
        self.logger.start_stage("Replace Page Resources")
        self.logger.log_info(f"🎯 Starting page resource replacement for {len(pages)} pages...")
    
        
        updated_pages = {}
        all_replacements = {}
        
        # Process pages in parallel
        tasks = []
        for filename, html in pages.items():
            tasks.append(self._replace_page_resources_single(filename, html))
        
        results = await asyncio.gather(*tasks)
        
        # Collect results
        for filename, (updated_html, replacements) in zip(pages.keys(), results):
            updated_pages[filename] = updated_html
            if replacements:
                all_replacements[filename] = replacements
        
        # Count by type
        type_counts = {}
        for page_repls in all_replacements.values():
            for repl in page_repls:
                type_counts[repl.resource_type] = type_counts.get(repl.resource_type, 0) + 1
        
        total_replaced = sum(len(r) for r in all_replacements.values())
        self.logger.log_info(f"✅ Replaced {total_replaced} resources across {len(all_replacements)} pages: {type_counts}")
        self.logger.end_stage("Replace Page Resources")
        
        return PageResourceResult(updated_pages=updated_pages, replacements=all_replacements)
    
    async def _replace_page_resources_single(self, filename: str, html: str) -> Tuple[str, List[ResourceReplacement]]:
        """
        Replace resources in a single HTML page
        
        Args:
            filename: Page filename
            html: HTML content
            
        Returns:
            Tuple of (updated HTML, list of replacements)
        """
        self.logger.log_info(f"  Processing {filename}...")
        
        # Identify static resources
        resources_to_replace = self._identify_page_resources(html, filename)
    
        
        if not resources_to_replace:
            self.logger.log_info(f"    No static resources to replace in {filename}")
            return html, []

        replacements = []
        updated_html = html

        for res_info in resources_to_replace:
            src = res_info.get('src', '')
            res_type = res_info.get('type', 'unknown')
            description = res_info.get('description', 'placeholder')
            width = res_info.get('width') or 0
            height = res_info.get('height') or 0

            if src:
                # Search and replace for all images (no small/large distinction)
                new_url = await self._search_resource(res_type, description, width, height)

                # Replace in HTML only if we got a valid URL
                if new_url and src in updated_html:
                    updated_html = updated_html.replace(src, new_url)
                    replacement = ResourceReplacement(
                        original_url=src,
                        resource_type=res_type,
                        search_query=description,
                        new_url=new_url
                    )
                    replacements.append(replacement)
                    self.logger.log_info(f"    Replaced {res_type}: {src[:40]}...")
                elif not new_url:
                    self.logger.log_info(f"    Keeping original {res_type}: {src[:40]}... (no replacement found)")

        self.logger.log_info(f"    ✅ Replaced {len(replacements)} resources in {filename}")
        return updated_html, replacements


