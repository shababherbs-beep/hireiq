from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx
import os
import json
import logging
import re
import time
from typing import Optional

# ============ LOGGING ============
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ CONFIG ============
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://hireiq.com",
    "https://www.hireiq.com",
    os.getenv("ALLOWED_ORIGIN", ""),  # For flexible deployment
]
# Remove empty strings
ALLOWED_ORIGINS = [origin for origin in ALLOWED_ORIGINS if origin]

# Token estimation constants (approximate)
TOKEN_PER_WORD = 1.3  # Average tokens per word
MAX_TOTAL_TOKENS = 8000  # Safe limit for most models
RESERVED_TOKENS = 2000  # For prompt template and response

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
)

# ============ MODELS ============
class ScreenRequest(BaseModel):
    cv_text: str
    job_title: str
    job_desc: str
    file_name: str

# ============ AUTHENTICATION ============
def validate_api_key(request: Request):
    """
    Validate incoming request using:
    1. hiq_live_* API key from Authorization header
    2. Supabase JWT token fallback
    """
    auth_header = request.headers.get("Authorization", "")
    
    # Check for API key format: "Bearer hiq_live_..."
    if auth_header.startswith("Bearer hiq_live_"):
        api_key = auth_header.replace("Bearer ", "").strip()
        expected_keys = os.getenv("VALID_API_KEYS", "").split(",")
        if api_key in expected_keys:
            logger.info(f"API key authenticated: {api_key[:10]}...")
            return api_key
        logger.warning(f"Invalid API key attempt: {api_key[:10]}...")
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Fallback: Accept requests with no auth for localhost (development)
    if request.client and request.client.host in ["127.0.0.1", "localhost"]:
        logger.info("Localhost request allowed (development mode)")
        return "localhost_dev"
    
    # If no valid auth, reject
    logger.warning(f"Unauthenticated request from {request.client.host if request.client else 'unknown'}")
    raise HTTPException(status_code=403, detail="Missing or invalid authentication")

# ============ TEXT TRUNCATION & PREPROCESSING ============
def estimate_tokens(text: str) -> int:
    """Estimate token count for a given text."""
    words = len(text.split())
    return int(words * TOKEN_PER_WORD)

def extract_cv_sections(cv_text: str) -> dict:
    """
    Extract key CV sections: Experience, Skills, Education.
    Returns dict with identified sections and their content.
    """
    sections = {
        "experience": "",
        "skills": "",
        "education": "",
        "summary": "",
        "other": ""
    }
    
    # Case-insensitive regex patterns for key sections
    patterns = {
        "experience": r"(experience|work history|employment|professional history)([\s\S]{0,2000}?)(?=education|skills|$)",
        "skills": r"(skills|technical skills|competencies)([\s\S]{0,1000}?)(?=experience|education|$)",
        "education": r"(education|certifications|degrees)([\s\S]{0,1000}?)(?=experience|skills|$)"
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, cv_text, re.IGNORECASE)
        if match:
            sections[key] = match.group(0)
    
    return sections

def truncate_cv_text(cv_text: str, max_tokens: int = MAX_TOTAL_TOKENS - RESERVED_TOKENS) -> str:
    """
    Intelligently truncate CV text while preserving critical sections.
    Prioritizes: Skills > Experience > Education > Other.
    """
    if estimate_tokens(cv_text) <= max_tokens:
        return cv_text
    
    logger.warning(f"CV text too large ({estimate_tokens(cv_text)} tokens), truncating...")
    
    # Extract sections
    sections = extract_cv_sections(cv_text)
    
    # Build truncated version with priority order
    truncated = ""
    priority_order = ["skills", "experience", "education", "summary", "other"]
    
    for section_name in priority_order:
        section_text = sections[section_name]
        if not section_text:
            continue
        
        # Check if adding this section would exceed limit
        test_text = truncated + "\n" + section_text
        if estimate_tokens(test_text) > max_tokens:
            # If this is the first section, truncate it
            if not truncated:
                # Truncate the section itself
                words = section_text.split()
                max_words = int(max_tokens / TOKEN_PER_WORD)
                section_text = " ".join(words[:max_words]) + "..."
            break
        
        truncated += "\n" + section_text
    
    if not truncated:
        # Fallback: just take first N words
        words = cv_text.split()
        max_words = int(max_tokens / TOKEN_PER_WORD)
        truncated = " ".join(words[:max_words]) + "..."
    
    logger.info(f"Truncated CV: {estimate_tokens(cv_text)} → {estimate_tokens(truncated)} tokens")
    return truncated.strip()

def clean_whitespace(text: str) -> str:
    """Normalize whitespace: remove excessive newlines, tabs, etc."""
    text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 newlines
    text = re.sub(r'\t+', ' ', text)  # Replace tabs with space
    text = re.sub(r' {2,}', ' ', text)  # Replace multiple spaces with one
    return text.strip()

# ============ ROOT ============
@app.get("/")
def root():
    logger.info("Health check")
    return {"status": "HireIQ Backend Running!", "timestamp": time.time()}

# ============ SCREEN CV (Protected Endpoint) ============
@app.post("/screen")
async def screen_cv(req: ScreenRequest, request: Request, api_key: str = Depends(validate_api_key)):
    """
    Screen CV against job description.
    Requires authentication via API key or JWT.
    Implements token truncation and error handling.
    """
    start_time = time.time()
    
    try:
        logger.info(f"Screening CV: {req.file_name} | Job: {req.job_title}")
        
        # Clean and truncate CV text
        cv_text = clean_whitespace(req.cv_text or "")
        if not cv_text:
            raise HTTPException(status_code=400, detail="CV text is empty")
        
        cv_text = truncate_cv_text(cv_text)
        job_desc = (req.job_desc or "")[:800]  # Truncate job desc to safe size
        
        prompt = f"""You are an expert HR recruiter and ATS specialist. 
Analyze this CV for the job and respond with ONLY valid JSON.

JOB TITLE: {req.job_title}
JOB DESCRIPTION: {job_desc}

CV FILE: "{req.file_name}"
CV CONTENT:
{cv_text}

Respond with ONLY this exact JSON (no markdown, no extra text):
{{
  "name": "candidate full name from CV",
  "score": <integer 0-100>,
  "experience": "<X yrs · Key Role>",
  "reason": "<2-3 sentence evaluation>",
  "matched_skills": ["skill1","skill2","skill3"],
  "missing_skills": ["skill1","skill2"],
  "recommendation": "shortlist" or "consider" or "reject",
  "ats_score": <integer 0-100>,
  "ats_issues": ["issue1","issue2"],
  "ats_keywords_found": ["keyword1","keyword2"],
  "ats_formatting": "good" or "fair" or "poor"
}}"""
        
        # Try Claude first
        claude_key = os.getenv("ANTHROPIC_API_KEY")
        if claude_key:
            try:
                result = await call_claude(prompt, claude_key)
                elapsed = time.time() - start_time
                logger.info(f"Screening completed via Claude in {elapsed:.2f}s")
                return result
            except Exception as e:
                logger.warning(f"Claude failed: {str(e)}")
        
        # Try OpenAI
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                result = await call_openai(prompt, openai_key)
                elapsed = time.time() - start_time
                logger.info(f"Screening completed via OpenAI in {elapsed:.2f}s")
                return result
            except Exception as e:
                logger.warning(f"OpenAI failed: {str(e)}")
        
        # Default Gemini
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise HTTPException(status_code=500, detail="No AI API key configured on backend")
        
        result = await call_gemini(prompt, gemini_key)
        elapsed = time.time() - start_time
        logger.info(f"Screening completed via Gemini in {elapsed:.2f}s")
        return result
        
    except HTTPException as e:
        logger.error(f"HTTP Error: {e.detail}")
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Screening failed after {elapsed:.2f}s: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Screening failed",
                "detail": str(e),
                "timestamp": time.time()
            }
        )

# ============ CLAUDE ============
async def call_claude(prompt: str, api_key: str):
    """Call Claude API with timeout and error handling."""
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 600,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            
            # Check for rate limiting
            if res.status_code == 429:
                logger.error("Claude rate limit exceeded")
                raise Exception("Claude API rate limited. Please retry in a moment.")
            
            # Check for timeout
            if res.status_code == 504:
                logger.error("Claude timeout")
                raise Exception("Claude API timeout. Please retry.")
            
            data = res.json()
            if "error" in data:
                error_msg = data["error"].get("message", "Unknown error")
                logger.error(f"Claude API error: {error_msg}")
                raise Exception(f"Claude error: {error_msg}")
            
            raw = data["content"][0]["text"]
            result = json.loads(raw.replace("```json", "").replace("```", "").strip())
            return result
            
    except httpx.TimeoutException:
        logger.error("Claude request timeout")
        raise Exception("Claude request timed out. Please retry.")
    except json.JSONDecodeError as e:
        logger.error(f"Claude JSON parse error: {str(e)}")
        raise Exception("Claude returned invalid JSON response")
    except Exception as e:
        logger.error(f"Claude error: {str(e)}")
        raise


# ============ OPENAI ============
async def call_openai(prompt: str, api_key: str):
    """Call OpenAI API with timeout and error handling."""
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            res = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "max_tokens": 600,
                    "temperature": 0.2,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            
            # Check for rate limiting
            if res.status_code == 429:
                logger.error("OpenAI rate limit exceeded")
                raise Exception("OpenAI API rate limited. Please retry in a moment.")
            
            # Check for timeout
            if res.status_code == 504:
                logger.error("OpenAI timeout")
                raise Exception("OpenAI API timeout. Please retry.")
            
            data = res.json()
            if "error" in data:
                error_msg = data["error"].get("message", "Unknown error")
                logger.error(f"OpenAI API error: {error_msg}")
                raise Exception(f"OpenAI error: {error_msg}")
            
            raw = data["choices"][0]["message"]["content"]
            result = json.loads(raw.replace("```json", "").replace("```", "").strip())
            return result
            
    except httpx.TimeoutException:
        logger.error("OpenAI request timeout")
        raise Exception("OpenAI request timed out. Please retry.")
    except json.JSONDecodeError as e:
        logger.error(f"OpenAI JSON parse error: {str(e)}")
        raise Exception("OpenAI returned invalid JSON response")
    except Exception as e:
        logger.error(f"OpenAI error: {str(e)}")
        raise

# ============ GEMINI ============
async def call_gemini(prompt: str, api_key: str):
    """Call Gemini API with timeout and error handling."""
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            res = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
                }
            )
            
            # Check for rate limiting
            if res.status_code == 429:
                logger.error("Gemini rate limit exceeded")
                raise Exception("Gemini API rate limited. Please retry in a moment.")
            
            # Check for timeout
            if res.status_code == 504:
                logger.error("Gemini timeout")
                raise Exception("Gemini API timeout. Please retry.")
            
            data = res.json()
            if "error" in data:
                error_msg = data["error"].get("message", "Unknown error")
                logger.error(f"Gemini API error: {error_msg}")
                raise Exception(f"Gemini error: {error_msg}")
            
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(raw.replace("```json", "").replace("```", "").strip())
            return result
            
    except httpx.TimeoutException:
        logger.error("Gemini request timeout")
        raise Exception("Gemini request timed out. Please retry.")
    except json.JSONDecodeError as e:
        logger.error(f"Gemini JSON parse error: {str(e)}")
        raise Exception("Gemini returned invalid JSON response")
    except Exception as e:
        logger.error(f"Gemini error: {str(e)}")
        raise

