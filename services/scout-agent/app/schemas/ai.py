from pydantic import BaseModel


class VisionExtractRequest(BaseModel):
    image_path: str
    prompt: str


class VisionExtractResponse(BaseModel):
    text: str
    structured: dict | None = None
