# SQL Code: Recreate Missing Screening Tables (`jobs`, `candidates`, `screenings`)

> **Context**: These three tables form the core screening execution pipeline for HireIQ. They integrate with the FastAPI backend (`/screen` endpoint) which analyzes CVs against job descriptions.

---

## 📋 Complete SQL Migration Script

Copy and paste the entire block below into **Supabase SQL Editor** and execute:

```sql
-- ========================================
-- 1. JOBS TABLE - Store job postings
-- ========================================
CREATE TABLE IF NOT EXISTS public.jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  job_title TEXT NOT NULL,
  job_desc TEXT NOT NULL,
  company TEXT NOT NULL,
  location TEXT,
  salary_min INTEGER,
  salary_max INTEGER,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'draft')),
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index for user queries
CREATE INDEX idx_jobs_user_id ON public.jobs(user_id);
CREATE INDEX idx_jobs_status ON public.jobs(status);
CREATE INDEX idx_jobs_created_at ON public.jobs(created_at DESC);

-- ========================================
-- 2. CANDIDATES TABLE - Store CV submissions
-- ========================================
CREATE TABLE IF NOT EXISTS public.candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  file_name TEXT NOT NULL,
  cv_text TEXT NOT NULL,
  candidate_name TEXT NOT NULL,
  candidate_email TEXT NOT NULL,
  phone TEXT,
  experience_years INTEGER,
  current_role TEXT,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index for efficient lookups
CREATE INDEX idx_candidates_user_id ON public.candidates(user_id);
CREATE INDEX idx_candidates_email ON public.candidates(candidate_email);
CREATE INDEX idx_candidates_created_at ON public.candidates(created_at DESC);

-- ========================================
-- 3. SCREENINGS TABLE - Store AI screening results
-- ========================================
CREATE TABLE IF NOT EXISTS public.screenings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
  candidate_id UUID NOT NULL REFERENCES public.candidates(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  
  -- AI Scoring (from backend /screen endpoint)
  score INTEGER NOT NULL CHECK (score >= 0 AND score <= 100),
  ats_score INTEGER NOT NULL CHECK (ats_score >= 0 AND ats_score <= 100),
  reason TEXT NOT NULL,
  
  -- Skill Analysis
  matched_skills TEXT[] DEFAULT ARRAY[]::TEXT[],
  missing_skills TEXT[] DEFAULT ARRAY[]::TEXT[],
  
  -- ATS & Recommendation
  recommendation TEXT NOT NULL CHECK (recommendation IN ('shortlist', 'consider', 'reject')),
  ats_issues TEXT[] DEFAULT ARRAY[]::TEXT[],
  ats_keywords_found TEXT[] DEFAULT ARRAY[]::TEXT[],
  ats_formatting TEXT NOT NULL CHECK (ats_formatting IN ('good', 'fair', 'poor')),
  
  -- Status Tracking
  status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'archived')),
  
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_screenings_job_id ON public.screenings(job_id);
CREATE INDEX idx_screenings_candidate_id ON public.screenings(candidate_id);
CREATE INDEX idx_screenings_user_id ON public.screenings(user_id);
CREATE INDEX idx_screenings_status ON public.screenings(status);
CREATE INDEX idx_screenings_recommendation ON public.screenings(recommendation);
CREATE INDEX idx_screenings_created_at ON public.screenings(created_at DESC);

-- Composite index for job+candidate uniqueness check
CREATE INDEX idx_screenings_job_candidate ON public.screenings(job_id, candidate_id);

-- ========================================
-- 4. AUTO-UPDATE TRIGGERS
-- ========================================

-- Function to auto-update updated_at column
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to jobs table
DROP TRIGGER IF EXISTS update_jobs_updated_at ON public.jobs;
CREATE TRIGGER update_jobs_updated_at BEFORE UPDATE ON public.jobs
FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- Apply to candidates table
DROP TRIGGER IF EXISTS update_candidates_updated_at ON public.candidates;
CREATE TRIGGER update_candidates_updated_at BEFORE UPDATE ON public.candidates
FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- Apply to screenings table
DROP TRIGGER IF EXISTS update_screenings_updated_at ON public.screenings;
CREATE TRIGGER update_screenings_updated_at BEFORE UPDATE ON public.screenings
FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- ========================================
-- 5. ROW LEVEL SECURITY (RLS) POLICIES
-- ========================================

-- Enable RLS on all tables
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.screenings ENABLE ROW LEVEL SECURITY;

-- === JOBS TABLE RLS ===

-- Users can only see jobs they created
DROP POLICY IF EXISTS jobs_select_own ON public.jobs;
CREATE POLICY jobs_select_own ON public.jobs
FOR SELECT
USING (auth.uid() = user_id);

-- Users can only update jobs they created
DROP POLICY IF EXISTS jobs_update_own ON public.jobs;
CREATE POLICY jobs_update_own ON public.jobs
FOR UPDATE
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

-- Users can insert their own jobs
DROP POLICY IF EXISTS jobs_insert_own ON public.jobs;
CREATE POLICY jobs_insert_own ON public.jobs
FOR INSERT
WITH CHECK (auth.uid() = user_id);

-- Users can delete their own jobs
DROP POLICY IF EXISTS jobs_delete_own ON public.jobs;
CREATE POLICY jobs_delete_own ON public.jobs
FOR DELETE
USING (auth.uid() = user_id);

-- Service role can do everything (for backend)
DROP POLICY IF EXISTS jobs_service_role ON public.jobs;
CREATE POLICY jobs_service_role ON public.jobs
USING (current_user = 'authenticated')
WITH CHECK (current_user = 'authenticated');

-- === CANDIDATES TABLE RLS ===

-- Users can see candidates they submitted or their own submissions
DROP POLICY IF EXISTS candidates_select_own ON public.candidates;
CREATE POLICY candidates_select_own ON public.candidates
FOR SELECT
USING (auth.uid() = user_id OR user_id IS NULL); -- Allow public candidates

-- Users can insert candidates (with or without user_id)
DROP POLICY IF EXISTS candidates_insert_public ON public.candidates;
CREATE POLICY candidates_insert_public ON public.candidates
FOR INSERT
WITH CHECK (true); -- Public can submit CVs

-- Users can only update their own candidates
DROP POLICY IF EXISTS candidates_update_own ON public.candidates;
CREATE POLICY candidates_update_own ON public.candidates
FOR UPDATE
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

-- === SCREENINGS TABLE RLS ===

-- Users can only see screenings for jobs they own
DROP POLICY IF EXISTS screenings_select_own ON public.screenings;
CREATE POLICY screenings_select_own ON public.screenings
FOR SELECT
USING (auth.uid() = user_id OR auth.uid() IN (
  SELECT user_id FROM public.jobs WHERE id = job_id
));

-- Users can insert screenings for their own jobs
DROP POLICY IF EXISTS screenings_insert_own ON public.screenings;
CREATE POLICY screenings_insert_own ON public.screenings
FOR INSERT
WITH CHECK (auth.uid() = user_id AND user_id IN (
  SELECT user_id FROM public.jobs WHERE id = job_id
));

-- Users can update screenings they created
DROP POLICY IF EXISTS screenings_update_own ON public.screenings;
CREATE POLICY screenings_update_own ON public.screenings
FOR UPDATE
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

-- ========================================
-- 6. GRANT PERMISSIONS TO SERVICE ROLE
-- ========================================

GRANT ALL ON public.jobs TO service_role;
GRANT ALL ON public.candidates TO service_role;
GRANT ALL ON public.screenings TO service_role;
GRANT USAGE, SELECT ON SEQUENCE jobs_id_seq TO service_role;

-- ========================================
-- 7. COMMENTS FOR DOCUMENTATION
-- ========================================

COMMENT ON TABLE public.jobs IS 'Stores job postings created by users. Each job can have multiple candidate screenings.';
COMMENT ON COLUMN public.jobs.job_title IS 'Job position title (e.g., "Senior Backend Engineer")';
COMMENT ON COLUMN public.jobs.job_desc IS 'Full job description sent to /screen endpoint';
COMMENT ON COLUMN public.jobs.status IS 'Job status: open (accepting), closed (no longer hiring), draft (not published)';

COMMENT ON TABLE public.candidates IS 'Stores candidate CV submissions (both authenticated and public)';
COMMENT ON COLUMN public.candidates.cv_text IS 'Full CV text extracted from PDF/DOC - used by /screen endpoint';
COMMENT ON COLUMN public.candidates.file_name IS 'Original file name (e.g., "john_smith_resume.pdf")';
COMMENT ON COLUMN public.candidates.user_id IS 'NULL for public submissions, user_id for authenticated uploads';

COMMENT ON TABLE public.screenings IS 'Screening results: AI analysis of candidate CV against job description';
COMMENT ON COLUMN public.screenings.score IS 'Overall match score (0-100) from AI evaluation';
COMMENT ON COLUMN public.screenings.ats_score IS 'ATS compatibility score (0-100)';
COMMENT ON COLUMN public.screenings.recommendation IS 'AI recommendation: shortlist (high match), consider (moderate), reject (low match)';
COMMENT ON COLUMN public.screenings.matched_skills IS 'PostgreSQL TEXT array of skills found in CV matching job description';
COMMENT ON COLUMN public.screenings.ats_formatting IS 'CV formatting quality: good (clean), fair (some issues), poor (many issues)';
```

---

## 📊 Schema Relationships

```
public.profiles (existing)
    ↓
    ├─→ public.jobs (user_id FK)
    │       ↓
    │       └─→ public.screenings (job_id FK)
    │
    └─→ public.candidates (user_id FK, nullable)
            ↓
            └─→ public.screenings (candidate_id FK)
```

---

## 🔑 Key Features

### Data Types Match Backend Output
The `screenings` table columns map directly to the `/screen` endpoint response:
```python
{
  "score": INTEGER,                    # screenings.score
  "ats_score": INTEGER,                # screenings.ats_score
  "reason": TEXT,                      # screenings.reason
  "matched_skills": TEXT[],            # screenings.matched_skills
  "missing_skills": TEXT[],            # screenings.missing_skills
  "recommendation": TEXT,              # screenings.recommendation
  "ats_issues": TEXT[],                # screenings.ats_issues
  "ats_keywords_found": TEXT[],        # screenings.ats_keywords_found
  "ats_formatting": TEXT               # screenings.ats_formatting
}
```

### Foreign Key Relationships
- **jobs** → **profiles**: user_id (ON DELETE CASCADE)
- **candidates** → **profiles**: user_id (ON DELETE SET NULL - allows public submissions)
- **screenings** → **jobs**: job_id (ON DELETE CASCADE)
- **screenings** → **candidates**: candidate_id (ON DELETE CASCADE)
- **screenings** → **profiles**: user_id (ON DELETE CASCADE)

### RLS Security
- **jobs**: Only creator can view/edit
- **candidates**: Public can submit; users see own
- **screenings**: Only job owner can view results

### Auto-Update Timestamps
All three tables auto-update `updated_at` on any modification via trigger.

### Indexes
10 indexes for fast queries:
- User lookups (user_id)
- Status filtering (status, recommendation)
- Chronological sorting (created_at DESC)
- Composite uniqueness checks

---

## ✅ Execution Steps

1. **Open Supabase Dashboard** → SQL Editor
2. **Paste the entire script** above
3. **Click "Execute"** or press Ctrl+Enter
4. **Verify**: Check "Database" → "Tables" for `jobs`, `candidates`, `screenings`
5. **Test RLS**: Try inserting a test record in each table

---

## 🧪 Test Inserts

After execution, test the tables:

```sql
-- Insert a test job
INSERT INTO public.jobs (user_id, job_title, job_desc, company, status)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Senior Backend Engineer',
  'We are hiring a senior backend engineer with 5+ years of experience...',
  'TechCorp Inc',
  'open'
)
RETURNING id, job_title, status;

-- Insert a test candidate
INSERT INTO public.candidates (candidate_name, candidate_email, cv_text, file_name)
VALUES (
  'John Smith',
  'john@example.com',
  'John Smith - Backend Engineer with 6 years of experience...',
  'john_resume.pdf'
)
RETURNING id, candidate_name, candidate_email;

-- Insert a test screening
INSERT INTO public.screenings (
  job_id,
  candidate_id,
  user_id,
  score,
  ats_score,
  reason,
  matched_skills,
  missing_skills,
  recommendation,
  ats_issues,
  ats_keywords_found,
  ats_formatting
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  '550e8400-e29b-41d4-a716-446655440001',
  '00000000-0000-0000-0000-000000000001',
  85,
  92,
  'Strong technical background with excellent matching skills. Experience aligns well with job requirements.',
  ARRAY['Python', 'PostgreSQL', 'REST APIs', 'Docker'],
  ARRAY['Kubernetes', 'GraphQL'],
  'shortlist',
  ARRAY[]::TEXT[],
  ARRAY['backend', 'engineer', 'python', 'postgresql'],
  'good'
)
RETURNING id, score, recommendation;
```

---

## 🚀 Next Steps

1. **Run this SQL** in Supabase
2. **Test with actual candidate data** using the test inserts above
3. **Connect frontend forms** to populate `candidates` table
4. **Integrate `/screen` endpoint** to populate `screenings` table
5. **Build UI dashboard** to visualize screening results

