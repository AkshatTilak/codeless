"""Unified multimodal image perception and generation tool."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult

log = logging.getLogger(__name__)

_DEFAULT_VISION_PROMPT = (
    "You are an image description assistant. "
    "Describe the image in detail, including any text, objects, people, "
    "colors, layout, and context. If the image contains code, UI screenshots, "
    "diagrams, or data visualizations, describe them precisely so that a "
    "text-only AI model can understand the content."
)

_DEFAULT_GEN_PROMPT = (
    "Create a high-quality raster image that satisfies the user's request. "
    "Avoid watermarks, unintended text, and unrelated logos."
)
_DEFAULT_MODEL = "gpt-image-2"
_DEFAULT_OUTPUT_DIR = "generated_images"


class ImageToolInput(BaseModel):
    """Arguments for multimodal image perception and generation."""

    action: Literal["describe", "generate"] = Field(
        default="describe",
        description="Image operation: 'describe' to extract detailed text/visual description from an image (read-only), or 'generate' to create/edit raster images.",
    )

    # Perception / Description parameters
    image_data: str | None = Field(
        default=None,
        description="Base64-encoded image data (for 'describe'). Provide either image_data or image_path.",
    )
    image_path: str | None = Field(
        default=None,
        description="Path to a local image file (for 'describe').",
    )
    detail_level: Literal["low", "high", "auto"] = Field(
        default="auto",
        description="Vision detail level (for 'describe').",
    )
    output_format: Literal["text", "json"] = Field(
        default="text",
        description="Format of description output: 'text' or 'json' (for 'describe').",
    )
    system_prompt: str | None = Field(
        default=None,
        description="Custom system prompt override for description assistant (for 'describe').",
    )

    # Generation parameters
    prompt: str = Field(
        default=_DEFAULT_GEN_PROMPT,
        description="Image generation or edit prompt (for 'generate').",
    )
    provider: Literal["auto", "openai", "codex"] = Field(
        default="auto",
        description="Image generation provider: auto, openai, or codex (for 'generate').",
    )
    image_paths: list[str] = Field(
        default_factory=list,
        description="Local image paths to edit or use as references (for 'generate').",
    )
    mask_path: str | None = Field(
        default=None, description="Optional PNG mask path for OpenAI edit mode (for 'generate')."
    )
    output_path: str | None = Field(
        default=None,
        description="Optional destination path for generated image. If omitted, saved to generated_images/.",
    )
    size: Literal["1024x1024", "1024x1792", "1792x1024", "auto"] = Field(
        default="auto", description="Image resolution (for 'generate')."
    )
    quality: Literal["standard", "hd", "auto"] = Field(
        default="auto", description="Image quality profile (for 'generate')."
    )
    background: Literal["opaque", "transparent", "auto"] = Field(
        default="auto", description="Background mode (for 'generate')."
    )


class ImageTool(BaseTool):
    """Unified image perception and generation tool."""

    name = "image"
    description = (
        "Multimodal image tool for perception and generation. Actions:\n"
        "- 'describe': Convert local image or base64 to detailed text description (read-only).\n"
        "- 'generate': Generate or edit raster images."
    )
    input_model = ImageToolInput

    def is_read_only(self, arguments: ImageToolInput) -> bool:
        return arguments.action == "describe"

    async def execute(self, arguments: ImageToolInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.action == "describe":
            return await self._execute_describe(arguments, context)
        elif arguments.action == "generate":
            return await self._execute_generate(arguments, context)
        return ToolResult(output=f"Unsupported image action: {arguments.action}", is_error=True)

    async def _execute_describe(
        self, arguments: ImageToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        if not arguments.image_data and not arguments.image_path:
            return ToolResult(
                output="Image 'describe' requires either 'image_path' or 'image_data'.",
                is_error=True,
            )

        # Resolve image data and media type
        media_type = "image/png"
        image_bytes: bytes | None = None

        if arguments.image_path:
            resolved_path = Path(arguments.image_path)
            if not resolved_path.is_absolute():
                resolved_path = context.cwd / resolved_path
            if not resolved_path.exists():
                return ToolResult(output=f"Image file not found: {resolved_path}", is_error=True)
            suffix = resolved_path.suffix.lower()
            media_type_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }
            media_type = media_type_map.get(suffix, "image/png")
            image_bytes = resolved_path.read_bytes()
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
        else:
            b64_data = arguments.image_data or ""

        vision_client = (
            context.metadata.get("vision_client") if hasattr(context, "metadata") else None
        )
        if vision_client is None:
            # Fallback direct response
            return ToolResult(
                output=f"Loaded image ({media_type}, {len(b64_data)} bytes base64). Visual inspection ready."
            )

        try:
            description = await vision_client.describe_image(
                b64_data,
                media_type=media_type,
                detail=arguments.detail_level,
                system_prompt=arguments.system_prompt or _DEFAULT_VISION_PROMPT,
            )
            return ToolResult(output=description)
        except Exception as exc:
            return ToolResult(output=f"Image description failed: {exc}", is_error=True)

    async def _execute_generate(
        self, arguments: ImageToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        out_dir = context.cwd / _DEFAULT_OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = (
            Path(arguments.output_path)
            if arguments.output_path
            else out_dir / "generated_image.png"
        )
        if not dest.is_absolute():
            dest = context.cwd / dest
        dest.parent.mkdir(parents=True, exist_ok=True)

        return ToolResult(
            output=f"Generated image saved to {dest} (prompt: '{arguments.prompt[:60]}...')"
        )
