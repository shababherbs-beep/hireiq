# HireIQ Backend Integration Guide

## Step 8: Core Backend API Shielding & Input Truncation

This document outlines the production-grade security and optimization updates applied to the HireIQ backend (`backend/backend/main.py`).

---

## 🔐 API Authentication

### Overview
All `/screen` endpoint requests now require authentication via an API key or JWT token.

### How to Authenticate

**Using API Key (Recommended for Frontend)**
```javascript
const apiKey = "hiq_live_abc123xyz..."; // Generate in dashboard

const response = await fetch("https://api.hireiq.com/screen", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${apiKey}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    cv_text: "...",
    job_title: "...",
    job_desc: "...",
    file_name: "resume.pdf"
  })
});
```

### Development Mode
Localhost requests (127.0.0.1) are auto-approved in development without authentication.

### Valid Origins (CORS)
- `http://localhost:3000`
- `http://localhost:8000`
- `https://hireiq.com`
- `https://www.hireiq.com`
- Custom origins via `ALLOWED_ORIGIN` env var

---

## 📏 Intelligent Input Truncation

### Problem Solved
Large CVs (PDFs with 10k+ words) would cause LLM token overflow or truncation bugs.

### Solution
The backend now:
1. **Estimates tokens** before sending to LLM (1 word ≈ 1.3 tokens)
2. **Extracts key sections** (Experience, Skills, Education)
3. **Intelligently prioritizes** which sections to keep if truncation needed
4. **Safely degrades** to first-N-words if structure extraction fails

### Max Token Budget
- **Total limit**: 8,000 tokens
- **Reserved for prompt/response**: 2,000 tokens
- **Available for CV text**: 6,000 tokens (~4,600 words)

### Automatic Cleaning
- Removes excessive newlines (max 2 consecutive)
- Converts tabs to spaces
- Normalizes multiple spaces to single space

**Result**: No more truncation errors, consistent LLM output quality.

---

## ⚠️ Error Handling & User-Friendly Responses

### Rate Limit Errors
```json
{
  "error": "Screening failed",
  "detail": "Claude API rate limited. Please retry in a moment.",
  "timestamp": 1716129600.123
}
```
→ **Frontend Action**: Show toast: "Rate limit hit. Retrying in 30 seconds..."

### Timeout Errors
```json
{
  "error": "Screening failed",
  "detail": "OpenAI request timed out. Please retry.",
  "timestamp": 1716129600.123
}
```
→ **Frontend Action**: Show toast: "Screening took too long. Try again?"

### Invalid JSON Response
```json
{
  "error": "Screening failed",
  "detail": "Gemini returned invalid JSON response",
  "timestamp": 1716129600.123
}
```
→ **Frontend Action**: Show toast: "Service error. Contact support."

### Empty CV Error
```json
{
  "error": "Screening failed",
  "detail": "CV text is empty",
  "timestamp": 1716129600.123
}
```
→ **Frontend Action**: Show form validation: "Please upload a CV."

---

## 📊 Logging & Observability

All backend operations are logged with timestamps:

```
INFO: Screening CV: resume.pdf | Job: Senior Developer
INFO: Screening completed via Claude in 3.45s
WARNING: Claude failed: Rate limit exceeded
ERROR: Screening failed after 1.23s: Connection timeout
```

### Key Metrics Logged
- Screening start/completion
- AI provider used
- Response time (seconds)
- Errors with full context
- Authentication successes/failures

---

## 🚀 Required Configuration

### .env File
```env
# AI API Keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# API Key Management
VALID_API_KEYS=hiq_live_abc123,hiq_live_def456,hiq_live_ghi789

# CORS (Optional)
ALLOWED_ORIGIN=https://custom.domain.com

# System
PORT=3000
NODE_ENV=production
```

### Install Dependencies
```bash
cd backend/backend
pip install -r requirements.txt
```

---

## 🔄 Request/Response Flow

### Request
```javascript
POST /screen
Header: Authorization: Bearer hiq_live_abc123
Body: {
  cv_text: "Full CV text here...",
  job_title: "Software Engineer",
  job_desc: "We're looking for...",
  file_name: "john_doe_resume.pdf"
}
```

### Processing Pipeline
1. ✅ Validate authentication
2. ✅ Clean whitespace
3. ✅ Estimate token count
4. ✅ Truncate intelligently if needed
5. ✅ Call LLM (Claude > OpenAI > Gemini)
6. ✅ Parse JSON response
7. ✅ Log timing/metrics
8. ✅ Return structured result

### Success Response
```json
{
  "name": "John Doe",
  "score": 92,
  "experience": "8 yrs · Senior Developer",
  "reason": "Strong match with required tech stack and experience level.",
  "matched_skills": ["Python", "FastAPI", "React"],
  "missing_skills": ["Kubernetes"],
  "recommendation": "shortlist",
  "ats_score": 88,
  "ats_issues": ["Formatting could be cleaner"],
  "ats_keywords_found": ["API", "Full-stack"],
  "ats_formatting": "good"
}
```

---

## 🛠️ Frontend Integration Checklist

- [ ] Store API key from dashboard in secure frontend storage
- [ ] Include `Authorization` header on all `/screen` requests
- [ ] Handle error responses with `detail` field
- [ ] Show loading spinner during screening (avg 3-5 seconds)
- [ ] Implement retry logic for rate limits (exponential backoff)
- [ ] Log errors to Supabase for debugging
- [ ] Validate CV text is not empty before sending
- [ ] Decode JWT/API key scope to ensure Pro/Enterprise access

---

## 📝 Notes for Developers

- **Timeout**: Extended to 45 seconds to accommodate slower LLMs
- **Token Estimation**: Approximation only; actual token usage may vary slightly
- **Retry Strategy**: Recommend 3-retry exponential backoff (1s, 2s, 4s) on timeout
- **Logging**: All operations logged; check backend logs for screening failures
- **CORS**: Localhost always allowed in dev; production requires explicit allow-list

---

**Version**: 1.0 | **Updated**: May 19, 2026 | **Status**: Production Ready
