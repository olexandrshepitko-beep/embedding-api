from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
import numpy as np
import logging, os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Embedding API", version="1.0.0")

# Load model on startup
MODEL_NAME = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")
model = None

class EmbedRequest(BaseModel):
    texts: list[str]
    batch_size: int = 32

class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    dimensions: int
    count: int
    model: str

@app.on_event("startup")
async def load_model():
    global model
    logger.info(f"Loading model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    logger.info(f"Model loaded. Dims: {model.get_sentence_embedding_dimension()}")

@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME, "loaded": model is not None}

@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    if model is None:
        raise HTTPException(503, "Model not loaded yet")
    if not req.texts:
        raise HTTPException(400, "Empty texts list")
    
    embeddings = model.encode(req.texts, batch_size=req.batch_size, show_progress_bar=False)
    dims = embeddings.shape[1] if len(embeddings.shape) > 1 else 0
    
    return EmbedResponse(
        embeddings=embeddings.tolist(),
        dimensions=dims,
        count=len(req.texts),
        model=MODEL_NAME
    )

@app.post("/embed-single")
async def embed_single(text: str):
    if model is None:
        raise HTTPException(503, "Model not loaded yet")
    emb = model.encode([text], show_progress_bar=False)
    return {"embedding": emb[0].tolist(), "dimensions": emb.shape[1]}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
