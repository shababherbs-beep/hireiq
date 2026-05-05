from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic
import pdfplumber
import docx2txt
import io
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = Anthropic()

def extract_text(file_bytes, filename):
    if filename.endswith(".pdf"):
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    elif filename.endswith(".docx"):
        return docx2txt.process(io.BytesIO(file_bytes))
    return file_bytes.decode("utf-8", errors="ignore")

@app.post("/screen")
async def screen_cvs(
    job_description: str = Form(...),
    files: list[UploadFile] = File(...)
):
    results = []
    for file in files:
        content = await file.read()
        cv_text = extract_text(content, file.filename)

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": f"""You are an expert HR screener.

Job Description:
{job_description}

Candidate CV:
{cv_text[:3000]}

Respond ONLY with valid JSON:
{{
  "name": "candidate full name",
  "score": 85,
  "summary": "2 line summary",
  "strengths": ["strength1", "strength2"],
  "verdict": "Shortlist or Reject"
}}"""
            }]
        )

        try:
            data = json.loads(response.content[0].text)
        except:
            data = {"name": file.filename, "score": 0, "summary": "Parse error", "strengths": [], "verdict": "Reject"}

        data["filename"] = file.filename
        results.append(data)

    results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": results}

@app.get("/")
def root():
    return {"status": "HireIQ Backend Running!"}
