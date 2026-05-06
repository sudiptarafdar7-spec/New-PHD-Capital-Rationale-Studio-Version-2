import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from backend.config import Config

def get_db_connection():
    conn = psycopg2.connect(
        Config.DATABASE_URL,
        sslmode='prefer'
    )
    return conn

@contextmanager
def get_db_cursor(commit=False):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield cursor
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def init_database():
    with get_db_cursor(commit=True) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(50) PRIMARY KEY,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                mobile VARCHAR(20),
                role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'employee')),
                password_hash VARCHAR(255) NOT NULL,
                avatar_path TEXT,
                job_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
        """)
        
        # API Keys table (multi-row: one row per provider)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id SERIAL PRIMARY KEY,
                provider VARCHAR(50) UNIQUE NOT NULL,
                key_value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_provider ON api_keys(provider);
        """)
        
        # PDF Template table (single row for company information)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pdf_template (
                id SERIAL PRIMARY KEY,
                company_name TEXT,
                registration_details TEXT,
                disclaimer_text TEXT,
                disclosure_text TEXT,
                company_data TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Insert default row if table is empty
        cursor.execute("SELECT COUNT(*) as count FROM pdf_template")
        result = cursor.fetchone()
        count = result['count'] if result else 0
        if count == 0:
            cursor.execute("""
                INSERT INTO pdf_template (company_name, registration_details, disclaimer_text, disclosure_text, company_data, updated_at)
                VALUES ('', '', '', '', '', CURRENT_TIMESTAMP)
            """)
        
        # Uploaded Files table (multi-row: masterFile, companyLogo, customFonts)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id SERIAL PRIMARY KEY,
                file_type VARCHAR(50) NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                file_path TEXT NOT NULL,
                file_size VARCHAR(20) NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_uploaded_files_type ON uploaded_files(file_type);
        """)
        
        # Channels table (multi-row: supports multiple platforms - YouTube, Facebook, Instagram, Telegram, WhatsApp)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY,
                channel_name VARCHAR(255),
                channel_logo_path TEXT,
                channel_url TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Add platform column if it doesn't exist (supports: youtube, facebook, instagram, telegram, whatsapp)
        cursor.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'channels' AND column_name = 'platform'
                ) THEN
                    ALTER TABLE channels ADD COLUMN platform VARCHAR(50) DEFAULT 'youtube';
                END IF;
            END $$;
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_channels_name ON channels(channel_name);
        """)
        
        # Jobs table (stores each Media/Premium/Manual Rationale job)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id VARCHAR(50) PRIMARY KEY,
                youtube_url TEXT,
                video_id VARCHAR(50),
                title TEXT,
                channel_id INTEGER REFERENCES channels(id),
                date DATE,
                time TIME,
                duration VARCHAR(20),
                user_id VARCHAR(50) REFERENCES users(id),
                tool_used VARCHAR(50) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'recording', 'awaiting_review', 'arranging', 'awaiting_arrange_review', 'bulk_started', 'awaiting_step8_review', 'awaiting_csv_review', 'awaiting_step4_review', 'awaiting_chart_upload', 'pdf_ready', 'completed', 'failed', 'signed')),
                progress INTEGER DEFAULT 0,
                current_step INTEGER DEFAULT 0,
                folder_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Add payload JSONB column for Manual Rationale stock data
        cursor.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'jobs' AND column_name = 'payload'
                ) THEN
                    ALTER TABLE jobs ADD COLUMN payload JSONB;
                END IF;
            END $$;
        """)
        
        # Update status constraint to include 'awaiting_chart_upload'
        cursor.execute("""
            DO $$
            BEGIN
                -- Drop old constraint if it exists and doesn't include awaiting_chart_upload
                IF EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'jobs_status_check' 
                    AND contype = 'c'
                    AND NOT pg_get_constraintdef(oid) LIKE '%awaiting_chart_upload%'
                ) THEN
                    ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
                    ALTER TABLE jobs ADD CONSTRAINT jobs_status_check 
                        CHECK (status IN ('pending', 'processing', 'awaiting_step8_review', 'awaiting_csv_review', 'awaiting_step4_review', 'awaiting_chart_upload', 'pdf_ready', 'completed', 'failed', 'signed'));
                END IF;
            END $$;
        """)

        # Update status constraint to include Voice Typing statuses
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'jobs_status_check'
                    AND contype = 'c'
                    AND NOT pg_get_constraintdef(oid) LIKE '%recording%'
                ) THEN
                    ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
                    ALTER TABLE jobs ADD CONSTRAINT jobs_status_check
                        CHECK (status IN ('pending', 'processing', 'recording', 'awaiting_review', 'arranging', 'awaiting_arrange_review', 'bulk_started', 'awaiting_step8_review', 'awaiting_csv_review', 'awaiting_step4_review', 'awaiting_chart_upload', 'pdf_ready', 'completed', 'failed', 'signed'));
                END IF;
            END $$;
        """)

        # Add 'live', 'extracting', 'awaiting_extract_review' for Live Transcribe.
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'jobs_status_check'
                    AND contype = 'c'
                    AND NOT pg_get_constraintdef(oid) LIKE '%''live''%'
                ) THEN
                    ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
                    ALTER TABLE jobs ADD CONSTRAINT jobs_status_check
                        CHECK (status IN ('pending', 'processing', 'recording', 'live', 'awaiting_review', 'arranging', 'awaiting_arrange_review', 'extracting', 'awaiting_extract_review', 'bulk_started', 'awaiting_step8_review', 'awaiting_csv_review', 'awaiting_step4_review', 'awaiting_chart_upload', 'pdf_ready', 'completed', 'failed', 'signed'));
                END IF;
            END $$;
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_tool_used ON jobs(tool_used);
        """)
        
        # Job Steps table (tracks each step in pipeline for each job)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_steps (
                id SERIAL PRIMARY KEY,
                job_id VARCHAR(50) REFERENCES jobs(id) ON DELETE CASCADE,
                step_number INTEGER NOT NULL,
                step_name VARCHAR(100) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'success', 'failed')),
                message TEXT,
                input_files TEXT[],
                output_files TEXT[],
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_steps_job_id ON job_steps(job_id);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_steps_status ON job_steps(status);
        """)
        
        # Saved Rationale table (final saved rationales)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS saved_rationale (
                id SERIAL PRIMARY KEY,
                job_id VARCHAR(50) UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
                tool_used VARCHAR(50) NOT NULL,
                channel_id INTEGER REFERENCES channels(id),
                title TEXT,
                date DATE,
                youtube_url TEXT,
                unsigned_pdf_path TEXT,
                signed_pdf_path TEXT,
                sign_status VARCHAR(20) DEFAULT 'Unsigned' CHECK (sign_status IN ('Unsigned', 'Signed')),
                signed_uploaded_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Add metadata JSONB column for storing summary data
        cursor.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'saved_rationale' AND column_name = 'metadata'
                ) THEN
                    ALTER TABLE saved_rationale ADD COLUMN metadata JSONB;
                END IF;
            END $$;
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_saved_rationale_tool_used ON saved_rationale(tool_used);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_saved_rationale_channel_id ON saved_rationale(channel_id);
        """)
        
        # Activity Logs table (audit trail for all system activities)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) REFERENCES users(id),
                job_id VARCHAR(50) REFERENCES jobs(id) ON DELETE SET NULL,
                action VARCHAR(50) NOT NULL CHECK (action IN ('job_started', 'job_completed', 'job_failed', 'login', 'logout', 'user_created', 'user_updated', 'user_deleted')),
                tool_used VARCHAR(50),
                message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id ON activity_logs(user_id);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_logs_action ON activity_logs(action);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_logs_timestamp ON activity_logs(timestamp);
        """)

        # Media Presence table — daily TV/YouTube media event tracker
        # Each entry can be processed via one of three transcribe methods:
        #   - voice_typing  (frontend Web Speech API → save transcript → trigger bulk/transcript rationale)
        #   - ai_transcribe (backend AssemblyAI download+transcribe → trigger bulk/transcript rationale)
        #   - auto          (full Media Rationale 14-step pipeline end-to-end)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media_presence (
                id SERIAL PRIMARY KEY,
                platform VARCHAR(50) NOT NULL,
                channel_id INTEGER REFERENCES channels(id) ON DELETE SET NULL,
                event_date DATE NOT NULL,
                event_time TIME NOT NULL,
                video_url TEXT,
                video_title TEXT,
                rationale_tool VARCHAR(40) NOT NULL CHECK (rationale_tool IN ('bulk_rationale', 'media_rationale')),
                transcribe_method VARCHAR(30) CHECK (transcribe_method IN ('voice_typing', 'ai_transcribe', 'auto', 'live_transcribe')),
                transcribe_status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (transcribe_status IN ('pending', 'started', 'completed', 'failed')),
                transcript_text TEXT,
                transcript_file_path TEXT,
                rationale_status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (rationale_status IN ('pending', 'started', 'done', 'failed')),
                rationale_job_id VARCHAR(50) REFERENCES jobs(id) ON DELETE SET NULL,
                output_pdf_path TEXT,
                notes TEXT,
                created_by VARCHAR(50) REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Idempotent upgrade for pre-existing media_presence tables that were
        # created before 'live_transcribe' was a permitted transcribe_method.
        # MUST run after CREATE TABLE media_presence so the constraint exists.
        cursor.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'media_presence_transcribe_method_check'
                    AND contype = 'c'
                    AND NOT pg_get_constraintdef(oid) LIKE '%live_transcribe%'
                ) THEN
                    ALTER TABLE media_presence DROP CONSTRAINT media_presence_transcribe_method_check;
                    ALTER TABLE media_presence ADD CONSTRAINT media_presence_transcribe_method_check
                        CHECK (transcribe_method IN ('voice_typing', 'ai_transcribe', 'auto', 'live_transcribe'));
                END IF;
            END $$;
        """)

        # Idempotent: link the MP row to the spawned voice/live/ai-transcribe
        # parent job so the table can render the Transcribe pill as a clickable
        # shortcut into that job's review page.
        cursor.execute("""
            ALTER TABLE media_presence
                ADD COLUMN IF NOT EXISTS linked_transcribe_job_id VARCHAR(50)
                REFERENCES jobs(id) ON DELETE SET NULL;
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_media_presence_event_date ON media_presence(event_date);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_media_presence_transcribe_status ON media_presence(transcribe_status);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_media_presence_rationale_status ON media_presence(rationale_status);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_media_presence_created_by ON media_presence(created_by);
        """)

        print("✓ Database tables created successfully")
