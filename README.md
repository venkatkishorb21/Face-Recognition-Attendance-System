# FaceAttend Pro v5 — Complete Attendance Management System

## Demo Login Credentials

| Role    | Email              | Password    |
|---------|--------------------|-------------|
| Admin   | admin@demo.com     | admin123    |
| Teacher | kumar@demo.com     | teacher123  |
| Teacher | meera@demo.com     | teacher123  |
| Student | kavya@demo.com     | student123  |
| Student | rahul@demo.com     | student123  |

---

## Setup (3 Steps)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

> face-recognition needs cmake:
> - Mac: `brew install cmake`
> - Ubuntu: `sudo apt install cmake build-essential`
> - If it fails the app auto-falls back to pixel comparison

### 2. Create PostgreSQL database
```bash
# Option A: local postgres
createdb faceattend_v5

# Option B: Docker
docker run --name facedb \
  -e POSTGRES_DB=faceattend_v5 \
  -e POSTGRES_PASSWORD=yourpassword \
  -p 5432:5432 -d postgres:15
```

### 3. Edit .env then Run
```bash
# Edit DB_PASSWORD in .env first
python app.py
```

Open:
- Student: http://localhost:5000/student/login
- Teacher: http://localhost:5000/teacher/login
- Admin:   http://localhost:5000/admin/login

---

## All Features

### 🛡 Admin Module
- Login with own credentials
- Add / Edit / Delete Teachers
- Add / Edit / Delete Students (deleted = archived)
- Add / Edit / Delete Subjects
- Assign subjects to teachers
- View all attendance records
- View all leave requests + approve/reject
- View full edit logs (who changed what, when, why)
- Generate PDF + CSV reports per subject
- System settings (thresholds, GPS, duration, face confidence)
- Export full attendance data CSV

### 👨‍🏫 Teacher Module (3 teachers, each sees only their subjects)
- Login with own credentials
- **Start Session** — select subject, set duration (e.g. 60 min)
- **Auto-close** — session closes automatically after duration
- **Auto-absent** — students who didn't scan = Absent automatically
- **Extend session** — +15 or +30 minutes if needed
- **Reopen session** — reopen today's closed session
- **View session** — see who's present/absent per session
- **Edit attendance** — change Absent→Present with mandatory reason
- **Every edit logged** — stored in correction log with name + time
- **Manage Students** — add/edit/delete (archived on delete)
- **Leave Requests** — approve or reject with remark
- **Correction Requests** — approve → auto-marks Present
- **Edit Logs** — full audit trail of own changes
- **Reports** — PDF + CSV per subject
- **Profile** — edit own name, phone, password

### 🎓 Student Module
- Login with own credentials
- **Register Face** — capture photo, AI extracts 128-D embedding
- **Scan Attendance** — face scan verifies identity, marks Present/Late
- **Time Lock** — can only scan during active session
- **GPS Lock** — must be within classroom radius
- **Dashboard** — subject cards with attendance % ring charts
- **Subject-wise Attendance** — click subject → see all dates + status
- **Request Correction** — submit message if face recognition failed
- **Apply Leave** — with date range, reason, optional document upload
- **View Leave Status** — Pending / Approved / Rejected
- **Profile** — edit name and phone

### 🤖 Auto Features
- Session auto-closes after set duration (background thread checks every 30s)
- All unscanned students auto-marked Absent on close
- Students notified when marked absent
- Students notified when below attendance threshold
- Teachers notified on new leave requests

### 🗂 Archive Feature
- When admin or teacher deletes a student:
  - Student is removed from active list
  - All attendance records preserved (foreign key with cascade)
  - Student info saved in archived_students table
  - Admin can view archive anytime

---

## Project Structure
```
faceattend_v5/
├── app.py                    # All Flask routes + models + AI + background thread
├── requirements.txt
├── .env                      # DB credentials
├── README.md
├── data/
│   └── system_settings.json  # System config (auto-created)
├── templates/
│   ├── auth/login.html        # Shared login page for all roles
│   ├── admin/
│   │   ├── dashboard.html
│   │   ├── teachers.html
│   │   ├── students.html
│   │   ├── subjects.html
│   │   ├── attendance.html
│   │   ├── leaves.html
│   │   ├── logs.html
│   │   ├── reports.html
│   │   └── settings.html
│   ├── teacher/
│   │   ├── dashboard.html
│   │   ├── sessions.html      # Start/close/extend sessions + auto-absent
│   │   ├── attendance.html    # Student-wise, click to expand records + edit
│   │   ├── students.html      # Add/edit/delete students + view full profile
│   │   ├── leaves.html        # Approve/reject leave requests
│   │   ├── corrections.html   # Review attendance corrections
│   │   ├── logs.html          # My edit history
│   │   ├── reports.html       # PDF + CSV reports
│   │   └── profile.html       # Edit own profile + password
│   └── student/
│       ├── dashboard.html     # Subject cards + active sessions
│       ├── register_face.html # Webcam face capture + AI encoding
│       ├── scan.html          # Face scan during active session
│       ├── attendance.html    # Subject-wise records + correction request
│       ├── leaves.html        # Apply + view leave status
│       └── profile.html       # Edit basic profile
└── static/
    ├── css/style.css
    └── js/shared.js
```

---

## Database Tables
```
admins               — id, name, email, password_hash
teachers             — id, name, email, password_hash, department, phone, qualification
students             — id, name, email, password_hash, roll_no, department, year,
                       phone, photo, face_encoding (JSON 128-D), face_registered, status
archived_students    — id, name, email, roll_no, department, deleted_by, deleted_at, reason
subjects             — id, name, code, teacher_id (FK), department, semester, credits
class_sessions       — id, subject_id, teacher_id, date, start_time, end_time,
                       duration_minutes, auto_close_at, status, room, lat, lng, radius,
                       auto_absent_done, total_students, present_count
attendance           — id, student_id, subject_id, session_id, date, time, status,
                       marked_by, confidence, remarks, original_status, edited
attendance_edit_logs — id, attendance_id, student_name, subject_name, date,
                       old_status, new_status, modified_by, modified_by_role, reason, modified_at
leave_requests       — id, student_id, subject_id, from_date, to_date, reason,
                       document_b64, status, teacher_remark, reviewed_by, reviewed_at
correction_requests  — id, student_id, attendance_id, subject_id, date, message,
                       current_status, status, teacher_remark, reviewed_by
notifications        — id, user_id, role, msg, type, read, created_at
```
