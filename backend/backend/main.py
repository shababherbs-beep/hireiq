from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ MODELS ============
class ScreenRequest(BaseModel):
    cv_text: str
    job_title: str
    job_desc: str
    file_name: str

# ============ ROOT ============
@app.get("/")
def root():
    return {"status": "HireIQ Backend Running!"}

# ============ SCREEN CV ============
@app.post("/screen")
async def screen_cv(req: ScreenRequest):
    prompt = f"""You are an expert HR recruiter and ATS specialist. 
Analyze this CV for the job and respond with ONLY valid JSON.

JOB TITLE: {req.job_title}
JOB DESCRIPTION: {req.job_desc[:800]}

CV FILE: "{req.file_name}"
CV CONTENT:
{req.cv_text or 'CV text could not be extracted'}

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
    claude_key = os.getenv("CLAUDE_KEY")
    if claude_key:
        try:
            return await call_claude(prompt, claude_key)
        except Exception as e:
            print(f"Claude failed: {e}")

    # Try OpenAI
    openai_key = os.getenv("OPENAI_KEY")
    if openai_key:
        try:
            return await call_openai(prompt, openai_key)
        except Exception as e:
            print(f"OpenAI failed: {e}")

    # Default Gemini
    gemini_key = os.getenv("GEMINI_KEY")
    if not gemini_key:
        raise HTTPException(status_code=500, detail="No AI API key configured")
    return await call_gemini(prompt, gemini_key)

# ============ CLAUDE ============
async def call_claude(prompt: str, api_key: str):
    async with httpx.AsyncClient(timeout=30) as client:
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
        data = res.json()
        if "error" in data:
            raise Exception(data["error"]["message"])
        import json
        raw = data["content"][0]["text"]
        return json.loads(raw.replace("```json","").replace("```","").strip())

# ============ OPENAI ============
async def call_openai(prompt: str, api_key: str):
    async with httpx.AsyncClient(timeout=30) as client:
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
        data = res.json()
        if "error" in data:
            raise Exception(data["error"]["message"])
        import json
        raw = data["choices"][0]["message"]["content"]
        return json.loads(raw.replace("```json","").replace("```","").strip())

# ============ GEMINI ============
async def call_gemini(prompt: str, api_key: str):
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
            }
        )
        data = res.json()
        if "error" in data:
            raise Exception(data["error"]["message"])
        import json
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(raw.replace("```json","").replace("```","").strip())
