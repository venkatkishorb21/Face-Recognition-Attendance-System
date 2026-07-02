"""
FaceAttend Pro v5 - Complete Attendance Management System
=========================================================
Roles   : Admin | Teacher | Student
Storage : PostgreSQL via SQLAlchemy
Face AI : dlib 128-D embeddings (face_recognition lib)
Features:
  - Admin   : Manage teachers/students/subjects, all reports, system settings
  - Teacher : Own subjects only, start sessions, auto-absent, edit attendance,
              approve leaves, correction log, student CRUD (own class only)
  - Student : Subject-wise attendance, leave apply, view status, face scan
  - Auto    : Class auto-closes after duration, auto-marks absent
  - Logs    : Every attendance edit logged with who/when/why
  - Archive : Deleted students' records archived, not permanently lost

Install:
  pip install flask flask-sqlalchemy flask-migrate flask-cors
              psycopg2-binary face-recognition pillow numpy
              python-dotenv reportlab werkzeug

Setup:
  createdb faceattend_v5
  Edit .env with DB credentials
  python app.py
  Open http://localhost:5000

Demo credentials:
  Admin   : admin@demo.com   / admin123
  Teacher : kumar@demo.com   / teacher123
  Student : kavya@demo.com   / student123
"""

import os, io, math, base64, datetime, json, uuid, threading, time as time_module
from functools import wraps
from dotenv import load_dotenv
load_dotenv()

from flask import (Flask, render_template, jsonify, request,
                   redirect, url_for, session, send_file)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

DB_URL = os.getenv("DATABASE_URL") or (
    f"postgresql://{os.getenv('DB_USER','postgres')}:"
    f"{os.getenv('DB_PASSWORD','yourpassword')}@"
    f"{os.getenv('DB_HOST','localhost')}:"
    f"{os.getenv('DB_PORT','5432')}/"
    f"{os.getenv('DB_NAME','faceattend_v5')}"
)

app.config.update(
    SQLALCHEMY_DATABASE_URI        = DB_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    SECRET_KEY                     = os.getenv("SECRET_KEY", "faceattend-secret-v5"),
    SQLALCHEMY_ENGINE_OPTIONS      = {"pool_pre_ping": True},
    PERMANENT_SESSION_LIFETIME     = datetime.timedelta(hours=8),
)

db      = SQLAlchemy(app)
migrate = Migrate(app, db)

# ── Utilities ─────────────────────────────────────────────────────────────────
def uid(p=""): return p + str(uuid.uuid4())[:8].upper()
def today():   return datetime.date.today().isoformat()
def now_dt():  return datetime.datetime.now()
def now_str(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def pct(a,b):  return round(a/b*100, 1) if b else 0.0

def haversine(lat1, lon1, lat2, lon2):
    R=6371000; p=math.pi/180
    a=(math.sin((lat2-lat1)*p/2)**2 +
       math.cos(lat1*p)*math.cos(lat2*p)*math.sin((lon2-lon1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))

# ── Auth decorator ────────────────────────────────────────────────────────────
def login_required(role):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if "user_id" not in session or session.get("role") != role:
                return redirect(url_for(f"{role}_login"))
            return f(*args, **kwargs)
        return wrapped
    return decorator

admin_required   = login_required("admin")
teacher_required = login_required("teacher")
student_required = login_required("student")

# ══════════════════════════════════════════════════════════════════════════════
#  MODELS
# ══════════════════════════════════════════════════════════════════════════════

class Admin(db.Model):
    __tablename__ = "admins"
    id            = db.Column(db.String(20),  primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at    = db.Column(db.DateTime,    default=now_dt)
    def set_password(self, pw):   self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    def to_dict(self): return {"id":self.id,"name":self.name,"email":self.email}


class Teacher(db.Model):
    __tablename__  = "teachers"
    id             = db.Column(db.String(20),  primary_key=True)
    name           = db.Column(db.String(100), nullable=False)
    email          = db.Column(db.String(120), unique=True, nullable=False)
    password_hash  = db.Column(db.String(256), nullable=False)
    department     = db.Column(db.String(100), default="")
    phone          = db.Column(db.String(30),  default="")
    qualification  = db.Column(db.String(100), default="")
    created_at     = db.Column(db.DateTime,    default=now_dt)
    subjects       = db.relationship("Subject", backref="teacher", lazy=True)
    sessions       = db.relationship("ClassSession", backref="teacher", lazy=True)
    def set_password(self, pw):   self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    def to_dict(self):
        return {"id":self.id,"name":self.name,"email":self.email,
                "department":self.department,"phone":self.phone,
                "qualification":self.qualification,
                "subjectCount":len(self.subjects)}


class Student(db.Model):
    __tablename__   = "students"
    id              = db.Column(db.String(20),  primary_key=True)
    name            = db.Column(db.String(100), nullable=False)
    email           = db.Column(db.String(120), unique=True, nullable=False)
    password_hash   = db.Column(db.String(256), nullable=False)
    roll_no         = db.Column(db.String(30),  default="")
    department      = db.Column(db.String(100), default="")
    year            = db.Column(db.Integer,     default=1)
    phone           = db.Column(db.String(30),  default="")
    photo           = db.Column(db.Text,        nullable=True)
    face_encoding   = db.Column(db.JSON,        nullable=True)
    face_registered = db.Column(db.Boolean,     default=False)
    status          = db.Column(db.String(20),  default="Active")
    mentor_id       = db.Column(db.String(20),  db.ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    enrolled_at     = db.Column(db.String(20),  default=today)
    created_at      = db.Column(db.DateTime,    default=now_dt)
    attendances     = db.relationship("Attendance",        backref="student", lazy=True, cascade="all,delete-orphan")
    leaves          = db.relationship("LeaveRequest",      backref="student", lazy=True, cascade="all,delete-orphan")
    corrections     = db.relationship("CorrectionRequest", backref="student", lazy=True, cascade="all,delete-orphan")
    mentor          = db.relationship("Teacher", foreign_keys=[mentor_id], backref="mentees")
    def set_password(self, pw):   self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    def to_dict(self):
        return {"id":self.id,"name":self.name,"email":self.email,"rollNo":self.roll_no,
                "department":self.department,"year":self.year,"phone":self.phone,
                "photo":self.photo,"faceRegistered":self.face_registered,"status":self.status,
                "mentorId":self.mentor_id,"mentorName":self.mentor.name if self.mentor else "",
                "enrolledAt":self.enrolled_at}


class ArchivedStudent(db.Model):
    """Keeps deleted student data so attendance history is preserved,
    and so the student can be restored (undo) later if deleted by mistake."""
    __tablename__ = "archived_students"
    id            = db.Column(db.String(20),  primary_key=True)
    name          = db.Column(db.String(100))
    email         = db.Column(db.String(120))
    roll_no       = db.Column(db.String(30))
    department    = db.Column(db.String(100))
    deleted_by    = db.Column(db.String(100))
    deleted_at    = db.Column(db.String(40), default=now_str)
    reason        = db.Column(db.Text, default="")
    # Extra fields preserved so a restore can fully recreate the student record
    password_hash   = db.Column(db.String(256), nullable=True)
    year            = db.Column(db.Integer,     default=1)
    phone           = db.Column(db.String(30),  default="")
    photo           = db.Column(db.Text,        nullable=True)
    face_encoding   = db.Column(db.JSON,        nullable=True)
    face_registered = db.Column(db.Boolean,     default=False)
    mentor_id       = db.Column(db.String(20),  nullable=True)
    enrolled_at     = db.Column(db.String(20),  nullable=True)


class Subject(db.Model):
    __tablename__ = "subjects"
    id            = db.Column(db.String(20),  primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    code          = db.Column(db.String(20),  default="")
    teacher_id    = db.Column(db.String(20),  db.ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    department    = db.Column(db.String(100), default="")
    semester      = db.Column(db.Integer,     default=1)
    credits       = db.Column(db.Integer,     default=3)
    created_at    = db.Column(db.DateTime,    default=now_dt)
    sessions      = db.relationship("ClassSession", backref="subject", lazy=True)
    attendances   = db.relationship("Attendance",   backref="subject", lazy=True)
    leaves        = db.relationship("LeaveRequest", backref="subject", lazy=True)
    corrections   = db.relationship("CorrectionRequest", backref="subject", lazy=True)
    def to_dict(self):
        return {"id":self.id,"name":self.name,"code":self.code,"teacherId":self.teacher_id,
                "teacherName":self.teacher.name if self.teacher else "Unassigned",
                "department":self.department,"semester":self.semester,"credits":self.credits}


class ClassSession(db.Model):
    """One attendance session = one class period"""
    __tablename__     = "class_sessions"
    id                = db.Column(db.String(20),  primary_key=True)
    subject_id        = db.Column(db.String(20),  db.ForeignKey("subjects.id"),  nullable=False)
    teacher_id        = db.Column(db.String(20),  db.ForeignKey("teachers.id"),  nullable=False)
    date              = db.Column(db.String(20),  nullable=False)
    start_time        = db.Column(db.String(20),  nullable=False)
    end_time          = db.Column(db.String(20),  nullable=True)
    duration_minutes  = db.Column(db.Integer,     default=60)
    auto_close_at     = db.Column(db.String(40),  nullable=True)  # ISO datetime string
    status            = db.Column(db.String(20),  default="Active")  # Active/Closed/Extended
    room              = db.Column(db.String(50),  default="")
    lat               = db.Column(db.Float,       nullable=True)
    lng               = db.Column(db.Float,       nullable=True)
    radius            = db.Column(db.Integer,     default=100)
    auto_absent_done  = db.Column(db.Boolean,     default=False)
    total_students    = db.Column(db.Integer,     default=0)
    present_count     = db.Column(db.Integer,     default=0)
    created_at        = db.Column(db.DateTime,    default=now_dt)
    attendances       = db.relationship("Attendance", backref="session", lazy=True)
    def to_dict(self):
        # Calculate remaining time
        remaining = None
        if self.status == "Active" and self.auto_close_at:
            try:
                close = datetime.datetime.fromisoformat(self.auto_close_at)
                diff  = (close - datetime.datetime.now()).total_seconds()
                remaining = max(0, int(diff // 60))
            except: pass
        return {"id":self.id,"subjectId":self.subject_id,
                "subjectName":self.subject.name if self.subject else "",
                "teacherId":self.teacher_id,
                "teacherName":self.teacher.name if self.teacher else "",
                "date":self.date,"startTime":self.start_time,"endTime":self.end_time,
                "durationMinutes":self.duration_minutes,"autoCloseAt":self.auto_close_at,
                "status":self.status,"room":self.room,"lat":self.lat,"lng":self.lng,
                "radius":self.radius,"totalStudents":self.total_students,
                "presentCount":self.present_count,"remainingMinutes":remaining}


class Attendance(db.Model):
    __tablename__ = "attendance"
    id            = db.Column(db.String(20),  primary_key=True)
    student_id    = db.Column(db.String(20),  db.ForeignKey("students.id",  ondelete="CASCADE"), nullable=False)
    subject_id    = db.Column(db.String(20),  db.ForeignKey("subjects.id",  ondelete="CASCADE"), nullable=False)
    session_id    = db.Column(db.String(20),  db.ForeignKey("class_sessions.id"), nullable=True)
    date          = db.Column(db.String(20),  nullable=False)
    time          = db.Column(db.String(20),  default="")
    status        = db.Column(db.String(20),  default="Present")
    marked_by     = db.Column(db.String(50),  default="Face Scan")
    confidence    = db.Column(db.Integer,     default=0)
    remarks       = db.Column(db.Text,        default="")
    original_status = db.Column(db.String(20), default="")
    edited        = db.Column(db.Boolean,     default=False)
    created_at    = db.Column(db.DateTime,    default=now_dt)
    edit_logs     = db.relationship("AttendanceEditLog", backref="attendance", lazy=True, cascade="all,delete-orphan")
    def to_dict(self):
        return {"id":self.id,"studentId":self.student_id,
                "studentName":self.student.name if self.student else "",
                "rollNo":self.student.roll_no if self.student else "",
                "subjectId":self.subject_id,
                "subjectName":self.subject.name if self.subject else "",
                "sessionId":self.session_id,"date":self.date,"time":self.time,
                "status":self.status,"markedBy":self.marked_by,
                "confidence":self.confidence,"remarks":self.remarks,
                "edited":self.edited,"originalStatus":self.original_status}


class AttendanceEditLog(db.Model):
    """Full audit trail of every attendance change"""
    __tablename__    = "attendance_edit_logs"
    id               = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    attendance_id    = db.Column(db.String(20), db.ForeignKey("attendance.id", ondelete="CASCADE"), nullable=False)
    student_name     = db.Column(db.String(100), default="")
    subject_name     = db.Column(db.String(100), default="")
    date             = db.Column(db.String(20),  default="")
    old_status       = db.Column(db.String(20),  default="")
    new_status       = db.Column(db.String(20),  default="")
    modified_by      = db.Column(db.String(100), default="")
    modified_by_role = db.Column(db.String(20),  default="teacher")
    reason           = db.Column(db.Text,        default="")
    modified_at      = db.Column(db.String(40),  default=now_str)
    def to_dict(self):
        return {"id":self.id,"attendanceId":self.attendance_id,
                "studentName":self.student_name,"subjectName":self.subject_name,
                "date":self.date,"oldStatus":self.old_status,"newStatus":self.new_status,
                "modifiedBy":self.modified_by,"modifiedByRole":self.modified_by_role,
                "reason":self.reason,"modifiedAt":self.modified_at}


class LeaveRequest(db.Model):
    __tablename__  = "leave_requests"
    id             = db.Column(db.String(20),  primary_key=True)
    student_id     = db.Column(db.String(20),  db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    subject_id     = db.Column(db.String(20),  db.ForeignKey("subjects.id"), nullable=True)
    from_date      = db.Column(db.String(20),  nullable=False)
    to_date        = db.Column(db.String(20),  nullable=False)
    reason         = db.Column(db.Text,        nullable=False)
    document_b64   = db.Column(db.Text,        nullable=True)
    status         = db.Column(db.String(20),  default="Pending")
    teacher_remark = db.Column(db.Text,        default="")
    reviewed_by    = db.Column(db.String(100), default="")
    reviewed_at    = db.Column(db.String(20),  default="")
    submitted_at   = db.Column(db.String(20),  default=today)
    def to_dict(self):
        # Who is actually responsible for approving/rejecting this leave:
        # the subject's own teacher for a subject-specific leave, or the
        # student's assigned mentor for a full-day leave. Shown to admin as
        # read-only context — admin doesn't review leaves, the responsible
        # teacher/mentor does.
        responsible = ""
        if self.subject_id:
            t = Teacher.query.get(self.subject.teacher_id) if (self.subject and self.subject.teacher_id) else None
            responsible = t.name if t else "Unassigned subject — no teacher"
        else:
            responsible = self.student.mentor.name if (self.student and self.student.mentor) else "No mentor assigned"
        return {"id":self.id,"studentId":self.student_id,
                "studentName":self.student.name if self.student else "",
                "subjectId":self.subject_id,
                "subjectName":self.subject.name if self.subject else "General",
                "fromDate":self.from_date,"toDate":self.to_date,
                "reason":self.reason,"status":self.status,
                "teacherRemark":self.teacher_remark,"reviewedBy":self.reviewed_by,
                "reviewedAt":self.reviewed_at,"submittedAt":self.submitted_at,
                "hasDocument":bool(self.document_b64),
                "responsibleTeacher":responsible}


class CorrectionRequest(db.Model):
    __tablename__  = "correction_requests"
    id             = db.Column(db.String(20),  primary_key=True)
    student_id     = db.Column(db.String(20),  db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    attendance_id  = db.Column(db.String(20),  nullable=True)
    subject_id     = db.Column(db.String(20),  db.ForeignKey("subjects.id"), nullable=True)
    date           = db.Column(db.String(20),  nullable=False)
    message        = db.Column(db.Text,        nullable=False)
    current_status = db.Column(db.String(20),  default="Absent")
    status         = db.Column(db.String(20),  default="Pending")
    teacher_remark = db.Column(db.Text,        default="")
    reviewed_by    = db.Column(db.String(100), default="")
    submitted_at   = db.Column(db.String(20),  default=today)
    def to_dict(self):
        return {"id":self.id,"studentId":self.student_id,
                "studentName":self.student.name if self.student else "",
                "attendanceId":self.attendance_id,"subjectId":self.subject_id,
                "subjectName":self.subject.name if self.subject else "",
                "date":self.date,"message":self.message,
                "currentStatus":self.current_status,"status":self.status,
                "teacherRemark":self.teacher_remark,"reviewedBy":self.reviewed_by,
                "submittedAt":self.submitted_at}


class Notification(db.Model):
    __tablename__ = "notifications"
    id            = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    user_id       = db.Column(db.String(20), nullable=False)
    role          = db.Column(db.String(20), default="student")
    msg           = db.Column(db.Text,       nullable=False)
    type          = db.Column(db.String(20), default="info")
    read          = db.Column(db.Boolean,    default=False)
    created_at    = db.Column(db.DateTime,   default=now_dt)
    def to_dict(self):
        return {"id":self.id,"userId":self.user_id,"msg":self.msg,"type":self.type,
                "read":self.read,"createdAt":str(self.created_at)[:16]}


# ── AI Face Engine ────────────────────────────────────────────────────────────
class FaceAI:
    @staticmethod
    def encode(image_b64):
        try:
            import face_recognition, numpy as np
            from PIL import Image
            if "," in image_b64: image_b64 = image_b64.split(",",1)[1]
            raw = base64.b64decode(image_b64 + "==")
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            arr = np.array(img)
            locs = face_recognition.face_locations(arr, model="hog")
            if not locs: return None, "No face detected in image"
            encs = face_recognition.face_encodings(arr, locs)
            return (encs[0].tolist(), None) if encs else (None, "Encoding failed")
        except ImportError:
            return FaceAI._pixel(image_b64)
        except Exception as e:
            return None, str(e)

    @staticmethod
    def _pixel(b64):
        try:
            from PIL import Image; import numpy as np
            if "," in b64: b64 = b64.split(",",1)[1]
            raw = base64.b64decode(b64 + "==")
            img = Image.open(io.BytesIO(raw)).convert("L").resize((20,20))
            arr = np.array(img, dtype=float).flatten()
            arr = (arr - arr.mean()) / (arr.std() + 1e-6)
            return arr.tolist(), None
        except Exception as e: return None, str(e)

    @staticmethod
    def compare(e1, e2):
        try:
            import numpy as np
            a = np.array(e1); b = np.array(e2)
            if len(a) == 128:
                return max(0, round((1.0 - float(np.linalg.norm(a-b))) * 100))
            ncc = float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-6))
            return round((ncc+1)/2*100)
        except: return 0

    @staticmethod
    def best_match(scan_enc, candidates, threshold=55):
        best, best_c = None, 0
        for stu, enc in candidates:
            if not enc: continue
            c = FaceAI.compare(scan_enc, enc)
            if c > best_c: best_c = c; best = stu
        return (best, best_c) if best and best_c >= threshold else (None, best_c)


# ── Auto-close sessions background thread ────────────────────────────────────
def auto_close_worker():
    """Background thread: every 30s check for expired sessions, mark absent"""
    while True:
        try:
            with app.app_context():
                now = datetime.datetime.now()
                expired = ClassSession.query.filter_by(status="Active").all()
                for sess in expired:
                    if not sess.auto_close_at: continue
                    try:
                        close_dt = datetime.datetime.fromisoformat(sess.auto_close_at)
                    except: continue
                    if now >= close_dt:
                        _do_auto_close(sess)
        except Exception as e:
            print(f"Auto-close error: {e}")
        time_module.sleep(30)

def _do_auto_close(sess):
    if sess.auto_absent_done: return
    sess.status = "Closed"
    sess.end_time = datetime.datetime.now().strftime("%H:%M")
    sess.auto_absent_done = True
    students = Student.query.filter_by(status="Active").all()
    absent_count = 0
    for stu in students:
        already = Attendance.query.filter_by(student_id=stu.id, session_id=sess.id).first()
        if not already:
            att = Attendance(id=uid("A"), student_id=stu.id, subject_id=sess.subject_id,
                session_id=sess.id, date=sess.date, time=sess.end_time,
                status="Absent", marked_by="Auto-Absent", confidence=0,
                original_status="Absent")
            db.session.add(att)
            absent_count += 1
            db.session.add(Notification(user_id=stu.id, role="student",
                msg=f"You were marked Absent in {sess.subject.name} on {sess.date} (auto-close)",
                type="warn"))
    sess.total_students = len(students)
    sess.present_count  = len(students) - absent_count
    db.session.commit()
    print(f"Auto-closed session {sess.id}: {absent_count} absent")


# ── Seed ─────────────────────────────────────────────────────────────────────
def seed():
    if not Admin.query.get("ADM001"):
        a = Admin(id="ADM001", name="Super Admin", email="admin@demo.com")
        a.set_password("admin123"); db.session.add(a)

    if not Teacher.query.get("TCH001"):
        for d in [
            {"id":"TCH001","name":"Dr. Kumar",  "email":"kumar@demo.com",  "department":"CSE","phone":"9000000001","qualification":"Ph.D CS"},
            {"id":"TCH002","name":"Prof. Meera", "email":"meera@demo.com",  "department":"CSE","phone":"9000000002","qualification":"M.Tech"},
            {"id":"TCH003","name":"Dr. Rajan",   "email":"rajan@demo.com",  "department":"IT", "phone":"9000000003","qualification":"Ph.D IT"},
        ]:
            t = Teacher(**d); t.set_password("teacher123"); db.session.add(t)

    if not Student.query.get("STU001"):
        for d in [
            {"id":"STU001","name":"Kavya Sharma",  "email":"kavya@demo.com",  "roll_no":"CS001","department":"CSE","year":2,"phone":"9100000001","mentor_id":"TCH001"},
            {"id":"STU002","name":"Rahul Singh",   "email":"rahul@demo.com",  "roll_no":"CS002","department":"CSE","year":2,"phone":"9100000002","mentor_id":"TCH001"},
            {"id":"STU003","name":"Priya Patel",   "email":"priya@demo.com",  "roll_no":"CS003","department":"CSE","year":2,"phone":"9100000003","mentor_id":"TCH002"},
            {"id":"STU004","name":"Arjun Mehta",   "email":"arjun@demo.com",  "roll_no":"CS004","department":"CSE","year":2,"phone":"9100000004","mentor_id":"TCH002"},
            {"id":"STU005","name":"Sneha Reddy",   "email":"sneha@demo.com",  "roll_no":"CS005","department":"CSE","year":2,"phone":"9100000005","mentor_id":"TCH002"},
            {"id":"STU006","name":"Dev Sharma",    "email":"dev@demo.com",    "roll_no":"IT001","department":"IT", "year":2,"phone":"9100000006","mentor_id":"TCH003"},
        ]:
            s = Student(**d); s.set_password("student123"); db.session.add(s)

    db.session.flush()

    if not Subject.query.get("SUB001"):
        for d in [
            {"id":"SUB001","name":"C Programming",    "code":"CS101","teacher_id":"TCH001","department":"CSE","semester":1,"credits":4},
            {"id":"SUB002","name":"Java",             "code":"CS201","teacher_id":"TCH001","department":"CSE","semester":2,"credits":4},
            {"id":"SUB003","name":"Python",           "code":"CS301","teacher_id":"TCH002","department":"CSE","semester":3,"credits":3},
            {"id":"SUB004","name":"DBMS",             "code":"CS401","teacher_id":"TCH002","department":"CSE","semester":4,"credits":4},
            {"id":"SUB005","name":"Data Structures",  "code":"CS202","teacher_id":"TCH001","department":"CSE","semester":2,"credits":4},
            {"id":"SUB006","name":"Computer Networks","code":"IT301","teacher_id":"TCH003","department":"IT", "semester":3,"credits":3},
        ]:
            db.session.add(Subject(**d))

    db.session.commit()

    # Seed attendance history
    if Attendance.query.count() == 0:
        import random
        students = Student.query.all()
        subjects = Subject.query.all()
        for sub in subjects:
            for day_offset in range(30):
                d = (datetime.date.today()-datetime.timedelta(days=day_offset+1)).isoformat()
                if datetime.date.fromisoformat(d).weekday() >= 5: continue
                sess = ClassSession(id=uid("S"), subject_id=sub.id, teacher_id=sub.teacher_id or "TCH001",
                    date=d, start_time="09:00", end_time="10:00", duration_minutes=60,
                    status="Closed", auto_absent_done=True, room="LH-"+sub.code[-3:])
                db.session.add(sess); db.session.flush()
                dept_students = [s for s in students if s.department == sub.department]
                for stu in dept_students:
                    st = "Present" if random.random() > 0.22 else "Absent"
                    db.session.add(Attendance(id=uid("A"), student_id=stu.id,
                        subject_id=sub.id, session_id=sess.id, date=d,
                        time="09:05" if st=="Present" else "",
                        status=st, marked_by="Face Scan" if st=="Present" else "Auto-Absent",
                        confidence=random.randint(75,98) if st=="Present" else 0,
                        original_status=st))
        db.session.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def home(): return redirect(url_for("student_login"))

@app.route("/admin/login",   methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        d = request.json
        a = Admin.query.filter_by(email=d.get("email","")).first()
        if a and a.check_password(d.get("password","")):
            session.permanent=True
            session["user_id"]=a.id; session["role"]="admin"; session["name"]=a.name
            return jsonify({"ok":True,"redirect":"/admin/dashboard"})
        return jsonify({"error":"Invalid credentials"}),401
    return render_template("auth/login.html", role="admin", title="Admin Login", icon="🛡")

@app.route("/teacher/login", methods=["GET","POST"])
def teacher_login():
    if request.method=="POST":
        d = request.json
        t = Teacher.query.filter_by(email=d.get("email","")).first()
        if t and t.check_password(d.get("password","")):
            session.permanent=True
            session["user_id"]=t.id; session["role"]="teacher"; session["name"]=t.name
            return jsonify({"ok":True,"redirect":"/teacher/dashboard"})
        return jsonify({"error":"Invalid credentials"}),401
    return render_template("auth/login.html", role="teacher", title="Teacher Login", icon="👨‍🏫")

@app.route("/student/login", methods=["GET","POST"])
def student_login():
    if request.method=="POST":
        d = request.json
        s = Student.query.filter_by(email=d.get("email","")).first()
        if s and s.check_password(d.get("password","")):
            session.permanent=True
            session["user_id"]=s.id; session["role"]="student"; session["name"]=s.name
            return jsonify({"ok":True,"redirect":"/student/dashboard"})
        return jsonify({"error":"Invalid credentials"}),401
    return render_template("auth/login.html", role="student", title="Student Login", icon="🎓")

@app.route("/logout")
def logout():
    role = session.get("role","student")
    session.clear()
    return redirect(url_for(f"{role}_login"))


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

# Admin pages
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard(): return render_template("admin/dashboard.html", name=session["name"])
@app.route("/admin/teachers")
@admin_required
def admin_teachers():  return render_template("admin/teachers.html",  name=session["name"])
@app.route("/admin/students")
@admin_required
def admin_students():  return render_template("admin/students.html",  name=session["name"])
@app.route("/admin/subjects")
@admin_required
def admin_subjects():  return render_template("admin/subjects.html",  name=session["name"])
@app.route("/admin/attendance")
@admin_required
def admin_attendance():return render_template("admin/attendance.html",name=session["name"])
@app.route("/admin/leaves")
@admin_required
def admin_leaves():    return render_template("admin/leaves.html",    name=session["name"])
@app.route("/admin/logs")
@admin_required
def admin_logs():      return render_template("admin/logs.html",      name=session["name"])
@app.route("/admin/reports")
@admin_required
def admin_reports():   return render_template("admin/reports.html",   name=session["name"])
@app.route("/admin/settings")
@admin_required
def admin_settings():  return render_template("admin/settings.html",  name=session["name"])

# Teacher pages
@app.route("/teacher/dashboard")
@teacher_required
def teacher_dashboard():   return render_template("teacher/dashboard.html",   name=session["name"], tid=session["user_id"])
@app.route("/teacher/sessions")
@teacher_required
def teacher_sessions():    return render_template("teacher/sessions.html",    name=session["name"], tid=session["user_id"])
@app.route("/teacher/students")
@teacher_required
def teacher_students():    return render_template("teacher/students.html",    name=session["name"], tid=session["user_id"])
@app.route("/teacher/attendance")
@teacher_required
def teacher_attendance():  return render_template("teacher/attendance.html",  name=session["name"], tid=session["user_id"])
@app.route("/teacher/leaves")
@teacher_required
def teacher_leaves():      return render_template("teacher/leaves.html",      name=session["name"], tid=session["user_id"])
@app.route("/teacher/corrections")
@teacher_required
def teacher_corrections(): return render_template("teacher/corrections.html", name=session["name"], tid=session["user_id"])
@app.route("/teacher/logs")
@teacher_required
def teacher_logs():        return render_template("teacher/logs.html",        name=session["name"], tid=session["user_id"])
@app.route("/teacher/reports")
@teacher_required
def teacher_reports():     return render_template("teacher/reports.html",     name=session["name"], tid=session["user_id"])
@app.route("/teacher/profile")
@teacher_required
def teacher_profile():     return render_template("teacher/profile.html",     name=session["name"], tid=session["user_id"])

# Student pages
@app.route("/student/dashboard")
@student_required
def student_dashboard():     return render_template("student/dashboard.html",     name=session["name"], sid=session["user_id"])
@app.route("/student/register-face")
@student_required
def student_register_face(): return render_template("student/register_face.html", name=session["name"], sid=session["user_id"])
@app.route("/student/scan")
@student_required
def student_scan():          return render_template("student/scan.html",          name=session["name"], sid=session["user_id"])
@app.route("/student/attendance")
@student_required
def student_attendance():    return render_template("student/attendance.html",    name=session["name"], sid=session["user_id"])
@app.route("/student/leaves")
@student_required
def student_leaves():        return render_template("student/leaves.html",        name=session["name"], sid=session["user_id"])
@app.route("/student/profile")
@student_required
def student_profile():       return render_template("student/profile.html",       name=session["name"], sid=session["user_id"])


# ══════════════════════════════════════════════════════════════════════════════
#  API — SHARED
# ══════════════════════════════════════════════════════════════════════════════

def push_notif(user_id, role, msg, ntype="info"):
    db.session.add(Notification(user_id=user_id, role=role, msg=msg, type=ntype))

@app.route("/api/notifications")
def api_notifs():
    uid_ = session.get("user_id") or request.args.get("userId")
    n    = Notification.query.filter_by(user_id=uid_).order_by(Notification.created_at.desc()).limit(30).all()
    return jsonify([x.to_dict() for x in n])

@app.route("/api/notifications/read-all", methods=["POST"])
def api_read_all():
    Notification.query.filter_by(user_id=session.get("user_id")).update({"read":True})
    db.session.commit(); return jsonify({"ok":True})

@app.route("/api/me")
def api_me():
    role = session.get("role")
    uid_ = session.get("user_id")
    if role=="student":   return jsonify(Student.query.get_or_404(uid_).to_dict())
    if role=="teacher":   return jsonify(Teacher.query.get_or_404(uid_).to_dict())
    if role=="admin":     return jsonify(Admin.query.get_or_404(uid_).to_dict())
    return jsonify({"error":"Not logged in"}),401


# ══════════════════════════════════════════════════════════════════════════════
#  API — ADMIN
# ══════════════════════════════════════════════════════════════════════════════

# Teachers
@app.route("/api/admin/teachers", methods=["GET"])
@admin_required
def api_get_teachers():
    return jsonify([t.to_dict() for t in Teacher.query.order_by(Teacher.name).all()])

@app.route("/api/admin/teachers", methods=["POST"])
@admin_required
def api_add_teacher():
    d = request.json
    if Teacher.query.filter_by(email=d["email"]).first():
        return jsonify({"error":"Email already exists"}),400
    t = Teacher(id=uid("TCH"),name=d["name"],email=d["email"],
                department=d.get("department",""),phone=d.get("phone",""),
                qualification=d.get("qualification",""))
    t.set_password(d.get("password","teacher123"))
    db.session.add(t); db.session.commit()
    return jsonify({"ok":True,"teacher":t.to_dict()})

@app.route("/api/admin/teachers/<tid>", methods=["PUT"])
@admin_required
def api_update_teacher(tid):
    t = Teacher.query.get_or_404(tid); d = request.json
    for f in ["name","email","department","phone","qualification"]:
        if f in d: setattr(t,f,d[f])
    if d.get("password"): t.set_password(d["password"])
    db.session.commit(); return jsonify({"ok":True,"teacher":t.to_dict()})

@app.route("/api/admin/teachers/<tid>", methods=["DELETE"])
@admin_required
def api_delete_teacher(tid):
    t = Teacher.query.get_or_404(tid)
    # unassign subjects
    Subject.query.filter_by(teacher_id=tid).update({"teacher_id":None})
    # unassign mentorship (mentees keep their record, just lose this mentor)
    Student.query.filter_by(mentor_id=tid).update({"mentor_id":None})
    db.session.delete(t); db.session.commit()
    return jsonify({"ok":True})

# Assign subject to teacher
@app.route("/api/admin/subjects/<subid>/assign", methods=["POST"])
@admin_required
def api_assign_subject(subid):
    sub = Subject.query.get_or_404(subid)
    sub.teacher_id = request.json.get("teacherId")
    db.session.commit()
    return jsonify({"ok":True})

# ── Mentor / Mentee assignment ────────────────────────────────────────────────
# Each student has at most one mentor (a teacher); one teacher can mentor many
# students. Admin assigns/changes/removes the mentor. Used to route full-day
# (no specific subject) leave requests straight to the right teacher.
@app.route("/api/admin/students/<sid>/mentor", methods=["POST"])
@admin_required
def api_assign_mentor(sid):
    s = Student.query.get_or_404(sid)
    teacher_id = request.json.get("teacherId") or None
    if teacher_id and not Teacher.query.get(teacher_id):
        return jsonify({"error":"Unknown teacher"}),400
    s.mentor_id = teacher_id
    db.session.commit()
    return jsonify({"ok":True,"student":s.to_dict()})

@app.route("/api/admin/mentors", methods=["GET"])
@admin_required
def api_mentor_overview():
    """List every teacher with the count + list of their mentees, for the
    admin's Assign Mentor screen."""
    result=[]
    for t in Teacher.query.order_by(Teacher.name).all():
        mentees = Student.query.filter_by(mentor_id=t.id).order_by(Student.name).all()
        result.append({"teacherId":t.id,"teacherName":t.name,
                       "mentees":[{"id":m.id,"name":m.name,"rollNo":m.roll_no} for m in mentees]})
    return jsonify(result)

# Admin analytics
@app.route("/api/admin/analytics")
@admin_required
def api_admin_analytics():
    t = today()
    total_att = Attendance.query.count()
    present   = Attendance.query.filter_by(status="Present").count()
    absent    = Attendance.query.filter_by(status="Absent").count()
    trend = []
    for i in range(14):
        d=(datetime.date.today()-datetime.timedelta(days=i)).isoformat()
        trend.insert(0,{"date":d,
            "present":Attendance.query.filter_by(date=d,status="Present").count(),
            "absent": Attendance.query.filter_by(date=d,status="Absent").count()})
    sub_stats=[]
    for sub in Subject.query.all():
        tot=Attendance.query.filter_by(subject_id=sub.id).count()
        pre=Attendance.query.filter_by(subject_id=sub.id,status="Present").count()
        sub_stats.append({"name":sub.name,"code":sub.code,"teacherName":sub.teacher.name if sub.teacher else "—",
                          "total":tot,"present":pre,"rate":pct(pre,tot)})
    return jsonify({
        "totalStudents":Student.query.count(),
        "activeStudents":Student.query.filter_by(status="Active").count(),
        "totalTeachers":Teacher.query.count(),
        "totalSubjects":Subject.query.count(),
        "totalSessions":ClassSession.query.count(),
        "activeSessions":ClassSession.query.filter_by(status="Active").count(),
        "totalAttendance":total_att,"present":present,"absent":absent,
        "overallRate":pct(present,total_att),
        "todayPresent":Attendance.query.filter_by(date=t,status="Present").count(),
        "todaySessions":ClassSession.query.filter_by(date=t).count(),
        "pendingLeaves":LeaveRequest.query.filter_by(status="Pending").count(),
        "pendingCorrections":CorrectionRequest.query.filter_by(status="Pending").count(),
        "faceRegistered":Student.query.filter_by(face_registered=True).count(),
        "editedRecords":Attendance.query.filter_by(edited=True).count(),
        "trend":trend,"subjectStats":sub_stats,
    })

# Full export
@app.route("/api/admin/export/full")
@admin_required
def api_full_export():
    import csv
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["StudentID","Name","RollNo","Dept","Year","Subject","SubjectCode","Date","Time","Status","Confidence","MarkedBy","Edited","EditedBy"])
    for r in Attendance.query.order_by(Attendance.date.desc()).all():
        s=r.student; sub=r.subject
        w.writerow([r.student_id,r.name,s.roll_no if s else "",s.department if s else "",
                    s.year if s else "",sub.name if sub else "",sub.code if sub else "",
                    r.date,r.time,r.status,r.confidence,r.marked_by,
                    "Yes" if r.edited else "No",""])
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()),mimetype="text/csv",
                     as_attachment=True,download_name=f"full_export_{today()}.csv")

# Archived students
@app.route("/api/admin/archived")
@admin_required
def api_archived():
    return jsonify([{"id":a.id,"name":a.name,"email":a.email,"rollNo":a.roll_no,
                     "department":a.department,"deletedBy":a.deleted_by,"deletedAt":a.deleted_at}
                    for a in ArchivedStudent.query.all()])

# Edit logs (admin view all)
@app.route("/api/admin/logs")
@admin_required
def api_all_logs():
    logs = AttendanceEditLog.query.order_by(AttendanceEditLog.id.desc()).limit(200).all()
    return jsonify([l.to_dict() for l in logs])

# System settings
@app.route("/api/admin/system-settings", methods=["GET","PUT"])
@admin_required
def api_system_settings():
    # Store settings in a JSON file for simplicity
    sf = "data/system_settings.json"
    os.makedirs("data", exist_ok=True)
    defaults = {"institutionName":"TechVerse University","session":"Spring 2026",
                "faceThreshold":55,"lateWindow":15,"absentThreshold":75,
                "locationRequired":True,"classDuration":60,"autoAbsent":True}
    if request.method=="GET":
        try: return jsonify(json.loads(open(sf).read()))
        except: return jsonify(defaults)
    data = request.json
    open(sf,"w").write(json.dumps({**defaults,**data}))
    return jsonify({"ok":True})


# ══════════════════════════════════════════════════════════════════════════════
#  API — STUDENTS (shared for admin + teacher)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/students", methods=["GET"])
def api_students():
    role = session.get("role")
    q = Student.query
    if role == "teacher":
        # Teachers see students in their subjects' departments
        my_subs = Subject.query.filter_by(teacher_id=session["user_id"]).all()
        depts = list(set(s.department for s in my_subs))
        if depts: q = q.filter(Student.department.in_(depts))
    return jsonify([s.to_dict() for s in q.order_by(Student.name).all()])

@app.route("/api/students", methods=["POST"])
def api_add_student():
    if session.get("role") not in ["admin","teacher"]:
        return jsonify({"error":"Unauthorized"}),403
    d = request.json
    sid = d.get("id","").strip().upper()
    if not sid or Student.query.get(sid) or Student.query.filter_by(email=d.get("email","")).first():
        return jsonify({"error":"ID already exists or email duplicate"}),400
    s = Student(id=sid,name=d["name"],email=d["email"],roll_no=d.get("rollNo",""),
                department=d.get("department",""),year=int(d.get("year",1)),phone=d.get("phone",""))
    s.set_password(d.get("password","student123"))
    db.session.add(s); db.session.commit()
    return jsonify({"ok":True,"student":s.to_dict()})

@app.route("/api/students/<sid>", methods=["GET"])
def api_get_student(sid):
    return jsonify(Student.query.get_or_404(sid).to_dict())

@app.route("/api/students/<sid>", methods=["PUT"])
def api_update_student(sid):
    if session.get("role") not in ["admin","teacher","student"]:
        return jsonify({"error":"Unauthorized"}),403
    if session.get("role")=="student" and session.get("user_id")!=sid:
        return jsonify({"error":"Can only edit own profile"}),403
    s = Student.query.get_or_404(sid); d = request.json
    allowed = ["name","email","phone","year","department","roll_no","status"] if session.get("role")!="student" else ["name","phone"]
    if session.get("role")=="admin" and "mentorId" in d:
        if d["mentorId"] and not Teacher.query.get(d["mentorId"]):
            return jsonify({"error":"Unknown mentor teacher"}),400
        s.mentor_id = d["mentorId"] or None
    for f in allowed:
        if f in d: setattr(s,f,d[f])
    if d.get("password") and session.get("role")!="student":
        s.set_password(d["password"])
    db.session.commit()
    return jsonify({"ok":True,"student":s.to_dict()})

@app.route("/api/students/<sid>", methods=["DELETE"])
def api_delete_student(sid):
    if session.get("role") not in ["admin","teacher"]:
        return jsonify({"error":"Unauthorized"}),403
    s = Student.query.get_or_404(sid)
    # Archive before delete — preserve everything needed to restore later
    arch = ArchivedStudent(id=s.id,name=s.name,email=s.email,roll_no=s.roll_no,
        department=s.department,deleted_by=session["name"],deleted_at=now_str(),
        reason=request.json.get("reason","") if request.json else "",
        password_hash=s.password_hash,year=s.year,phone=s.phone,photo=s.photo,
        face_encoding=s.face_encoding,face_registered=s.face_registered,
        mentor_id=s.mentor_id,enrolled_at=s.enrolled_at)
    db.session.add(arch); db.session.delete(s); db.session.commit()
    return jsonify({"ok":True,"archived":True})

@app.route("/api/admin/archived/<sid>/restore", methods=["POST"])
@admin_required
def api_restore_student(sid):
    """Undo a student deletion: recreate the active student record from the
    archive snapshot, then remove the archive entry. Attendance/leave/correction
    records were never deleted (only the student row was), so history reappears
    automatically once the student row exists again."""
    arch = ArchivedStudent.query.get_or_404(sid)
    if Student.query.get(sid):
        return jsonify({"error":"A student with this ID already exists — cannot restore"}),400
    s = Student(id=arch.id, name=arch.name, email=arch.email, roll_no=arch.roll_no,
        department=arch.department, year=arch.year or 1, phone=arch.phone or "",
        photo=arch.photo, face_encoding=arch.face_encoding,
        face_registered=bool(arch.face_registered), status="Active",
        mentor_id=arch.mentor_id, enrolled_at=arch.enrolled_at or today())
    # Restore the original password hash directly so the student's old password still works
    s.password_hash = arch.password_hash or generate_password_hash("student123")
    db.session.add(s)
    db.session.delete(arch)
    db.session.commit()
    return jsonify({"ok":True,"student":s.to_dict()})


@app.route("/api/students/<sid>/register-face", methods=["POST"])
def api_register_face(sid):
    s = Student.query.get_or_404(sid)
    photo = request.json.get("photo")
    s.photo = photo
    enc, err = FaceAI.encode(photo)
    if enc:
        s.face_encoding = enc; s.face_registered = True
        db.session.commit()
        return jsonify({"ok":True,"message":f"Face registered! {len(enc)}-D AI encoding saved.","dims":len(enc)})
    db.session.commit()
    return jsonify({"ok":False,"error":f"Face not detected: {err}"})

# Student's own profile
@app.route("/api/students/me/profile", methods=["PUT"])
@student_required
def api_update_my_profile():
    s = Student.query.get(session["user_id"]); d = request.json
    for f in ["name","phone"]:
        if f in d: setattr(s,f,d[f])
    if d.get("newPassword"):
        if not d.get("currentPassword") or not s.check_password(d["currentPassword"]):
            return jsonify({"error":"Current password is incorrect"}),400
        if len(d["newPassword"]) < 6:
            return jsonify({"error":"New password must be at least 6 characters"}),400
        s.set_password(d["newPassword"])
    db.session.commit()
    return jsonify({"ok":True,"student":s.to_dict()})


# ══════════════════════════════════════════════════════════════════════════════
#  API — SUBJECTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/subjects", methods=["GET"])
def api_subjects():
    role = session.get("role")
    q = Subject.query
    if role == "teacher":
        q = q.filter_by(teacher_id=session["user_id"])
    return jsonify([s.to_dict() for s in q.order_by(Subject.name).all()])

@app.route("/api/subjects", methods=["POST"])
@admin_required
def api_add_subject():
    d = request.json
    sub = Subject(id=uid("SUB"),name=d["name"],code=d.get("code",""),
                  teacher_id=d.get("teacherId"),department=d.get("department",""),
                  semester=int(d.get("semester",1)),credits=int(d.get("credits",3)))
    db.session.add(sub); db.session.commit()
    return jsonify({"ok":True,"subject":sub.to_dict()})

@app.route("/api/subjects/<subid>", methods=["PUT"])
@admin_required
def api_update_subject(subid):
    sub = Subject.query.get_or_404(subid); d = request.json
    for f in ["name","code","teacher_id","department","semester","credits"]:
        if f in d: setattr(sub,f,d[f])
    db.session.commit(); return jsonify({"ok":True})

@app.route("/api/subjects/<subid>", methods=["DELETE"])
@admin_required
def api_delete_subject(subid):
    sub = Subject.query.get_or_404(subid)
    db.session.delete(sub); db.session.commit()
    return jsonify({"ok":True})


# ══════════════════════════════════════════════════════════════════════════════
#  API — SESSIONS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions", methods=["GET"])
def api_sessions():
    q = ClassSession.query
    if session.get("role")=="teacher": q=q.filter_by(teacher_id=session["user_id"])
    if request.args.get("status"):     q=q.filter_by(status=request.args["status"])
    if request.args.get("subjectId"):  q=q.filter_by(subject_id=request.args["subjectId"])
    return jsonify([s.to_dict() for s in q.order_by(ClassSession.created_at.desc()).limit(50).all()])

@app.route("/api/sessions/active")
def api_active_sessions():
    q = ClassSession.query.filter_by(status="Active")
    return jsonify([s.to_dict() for s in q.all()])

@app.route("/api/sessions/start", methods=["POST"])
@teacher_required
def api_start_session():
    d = request.json
    sub = Subject.query.get_or_404(d["subjectId"])
    # Only teacher's own subject
    if sub.teacher_id != session["user_id"]:
        return jsonify({"error":"Not your subject"}),403
    duration = int(d.get("durationMinutes",60))
    auto_close = (datetime.datetime.now()+datetime.timedelta(minutes=duration)).isoformat()
    sess = ClassSession(
        id=uid("S"),subject_id=sub.id,teacher_id=session["user_id"],
        date=today(),start_time=datetime.datetime.now().strftime("%H:%M"),
        duration_minutes=duration,auto_close_at=auto_close,
        status="Active",room=d.get("room",""),
        lat=d.get("lat"),lng=d.get("lng"),radius=int(d.get("radius",100)))
    db.session.add(sess); db.session.commit()
    return jsonify({"ok":True,"session":sess.to_dict()})

@app.route("/api/sessions/<sess_id>/extend", methods=["POST"])
@teacher_required
def api_extend_session(sess_id):
    sess = ClassSession.query.get_or_404(sess_id)
    if sess.teacher_id != session["user_id"]: return jsonify({"error":"Not your session"}),403
    extra = int(request.json.get("minutes",15))
    try:
        close_dt = datetime.datetime.fromisoformat(sess.auto_close_at)
        new_close = close_dt + datetime.timedelta(minutes=extra)
    except:
        new_close = datetime.datetime.now() + datetime.timedelta(minutes=extra)
    sess.auto_close_at = new_close.isoformat()
    sess.duration_minutes += extra; sess.status="Extended"
    db.session.commit(); return jsonify({"ok":True,"session":sess.to_dict()})

@app.route("/api/sessions/<sess_id>/close", methods=["POST"])
@teacher_required
def api_close_session(sess_id):
    sess = ClassSession.query.get_or_404(sess_id)
    if sess.teacher_id != session["user_id"]: return jsonify({"error":"Not your session"}),403
    _do_auto_close(sess)
    return jsonify({"ok":True})

@app.route("/api/sessions/<sess_id>/reopen", methods=["POST"])
@teacher_required
def api_reopen_session(sess_id):
    sess = ClassSession.query.get_or_404(sess_id)
    if sess.date != today(): return jsonify({"error":"Can only reopen today's sessions"}),400
    extra = int(request.json.get("minutes",30))
    sess.status="Active"
    sess.auto_close_at=(datetime.datetime.now()+datetime.timedelta(minutes=extra)).isoformat()
    db.session.commit(); return jsonify({"ok":True,"session":sess.to_dict()})


# ══════════════════════════════════════════════════════════════════════════════
#  API — FACE SCAN (Student marks attendance)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/scan", methods=["POST"])
@student_required
def api_scan():
    d           = request.json
    session_id  = d.get("sessionId")
    scan_image  = d.get("image")
    user_lat    = d.get("lat")
    user_lng    = d.get("lng")
    student_id  = session["user_id"]

    if not scan_image: return jsonify({"ok":False,"error":"No image captured"})

    stu = Student.query.get(student_id)
    if not stu.face_registered or not stu.face_encoding:
        return jsonify({"ok":False,"error":"Register your face first (Register Face tab)"})

    sess = ClassSession.query.get(session_id)
    if not sess: return jsonify({"ok":False,"error":"Session not found"})
    if sess.status not in ["Active","Extended"]:
        return jsonify({"ok":False,"error":"⏰ Session is closed — attendance window ended","lock":"time"})

    # Location check
    if sess.lat and sess.lng:
        if user_lat is None or user_lng is None:
            return jsonify({"ok":False,"error":"📍 Enable GPS location","lock":"location"})
        dist = haversine(user_lat,user_lng,sess.lat,sess.lng)
        if dist > sess.radius:
            return jsonify({"ok":False,"error":f"📍 {int(dist)}m away — must be within {sess.radius}m of classroom","lock":"location"})

    # Duplicate
    already = Attendance.query.filter_by(student_id=student_id,session_id=session_id).first()
    if already:
        return jsonify({"ok":False,"error":"Already marked for this session","duplicate":True})

    # AI face match — verify it's THIS student
    scan_enc, err = FaceAI.encode(scan_image)
    if not scan_enc:
        return jsonify({"ok":False,"error":f"No face detected. {err or 'Ensure good lighting.'}"})

    confidence = FaceAI.compare(scan_enc, stu.face_encoding)
    try:
        sf = json.loads(open("data/system_settings.json").read())
        threshold = int(sf.get("faceThreshold",55))
        late_win  = int(sf.get("lateWindow",15))
    except:
        threshold,late_win = 55,15

    if confidence < threshold:
        return jsonify({"ok":False,"matched":False,"confidence":confidence,
            "error":f"Face not matched ({confidence}%). Stand closer to camera in good lighting."})

    # Present / Late
    h,m    = map(int,sess.start_time.split(":"))
    start  = datetime.datetime.combine(datetime.date.today(),datetime.time(h,m))
    diff   = int((datetime.datetime.now()-start).total_seconds()/60)
    status = "Late" if diff > late_win else "Present"

    att = Attendance(id=uid("A"),student_id=student_id,subject_id=sess.subject_id,
        session_id=session_id,date=sess.date,time=datetime.datetime.now().strftime("%H:%M"),
        status=status,marked_by="Face Scan (AI)",confidence=confidence,original_status=status)
    db.session.add(att)
    sess.present_count = (sess.present_count or 0) + 1
    db.session.commit()

    # Check at-risk
    sub_recs = Attendance.query.filter_by(student_id=student_id,subject_id=sess.subject_id).all()
    rate     = pct(sum(1 for r in sub_recs if r.status=="Present"),len(sub_recs))
    try:
        abs_thr = int(json.loads(open("data/system_settings.json").read()).get("absentThreshold",75))
    except: abs_thr = 75
    if rate < abs_thr:
        push_notif(student_id,"student",f"⚠ {sess.subject.name} attendance at {rate}% — below {abs_thr}%","warn")
        db.session.commit()

    return jsonify({"ok":True,"matched":True,"confidence":confidence,"status":status,
                    "studentName":stu.name,"subjectName":sess.subject.name,"rate":rate})


# ══════════════════════════════════════════════════════════════════════════════
#  API — ATTENDANCE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/attendance", methods=["GET"])
def api_attendance():
    q = Attendance.query
    if request.args.get("studentId"): q=q.filter_by(student_id=request.args["studentId"])
    if request.args.get("subjectId"): q=q.filter_by(subject_id=request.args["subjectId"])
    if request.args.get("sessionId"): q=q.filter_by(session_id=request.args["sessionId"])
    if request.args.get("date"):      q=q.filter_by(date=request.args["date"])
    if request.args.get("status"):    q=q.filter_by(status=request.args["status"])
    return jsonify([r.to_dict() for r in q.order_by(Attendance.date.desc()).limit(500).all()])

@app.route("/api/attendance/<aid>", methods=["PUT"])
def api_edit_attendance(aid):
    if session.get("role") not in ["admin","teacher"]:
        return jsonify({"error":"Unauthorized"}),403
    att = Attendance.query.get_or_404(aid); d = request.json
    old = att.status
    # Log the edit
    log = AttendanceEditLog(
        attendance_id=att.id,student_name=att.student.name if att.student else "",
        subject_name=att.subject.name if att.subject else "",
        date=att.date,old_status=old,new_status=d["status"],
        modified_by=session["name"],modified_by_role=session["role"],
        reason=d.get("reason",""),modified_at=now_str())
    att.status   = d["status"]
    att.remarks  = d.get("reason","")
    att.edited   = True
    if not att.original_status: att.original_status = old
    db.session.add(log); db.session.commit()
    # Notify student
    push_notif(att.student_id,"student",
        f"Attendance on {att.date} changed {old}→{att.status} by {session['name']} — {d.get('reason','')}","info")
    db.session.commit()
    return jsonify({"ok":True,"record":att.to_dict()})

@app.route("/api/attendance/<aid>", methods=["DELETE"])
def api_delete_attendance(aid):
    if session.get("role") not in ["admin","teacher"]:
        return jsonify({"error":"Unauthorized"}),403
    att = Attendance.query.get_or_404(aid)
    db.session.delete(att); db.session.commit()
    return jsonify({"ok":True})

@app.route("/api/attendance/clear-session/<sess_id>", methods=["DELETE"])
@teacher_required
def api_clear_session(sess_id):
    Attendance.query.filter_by(session_id=sess_id).delete()
    db.session.commit(); return jsonify({"ok":True})

# Subject-wise summary for a student
@app.route("/api/attendance/summary/<student_id>")
def api_summary(student_id):
    subjects = Subject.query.all(); result=[]
    for sub in subjects:
        recs = Attendance.query.filter_by(student_id=student_id,subject_id=sub.id).all()
        if not recs: continue
        total=len(recs); present=sum(1 for r in recs if r.status=="Present")
        absent=sum(1 for r in recs if r.status=="Absent")
        late=sum(1 for r in recs if r.status=="Late")
        rate=pct(present,total)
        result.append({"subjectId":sub.id,"subjectName":sub.name,"subjectCode":sub.code,
            "teacherName":sub.teacher.name if sub.teacher else "","totalClasses":total,
            "present":present,"absent":absent,"late":late,"percentage":rate,
            "status":"Safe" if rate>=75 else "At Risk"})
    return jsonify(result)

# Subject detail — all students for teacher
@app.route("/api/attendance/subject/<subject_id>")
def api_subject_detail(subject_id):
    sub = Subject.query.get_or_404(subject_id)
    if session.get("role")=="teacher" and sub.teacher_id!=session["user_id"]:
        return jsonify({"error":"Not your subject"}),403
    students=Student.query.filter_by(status="Active",department=sub.department).all()
    result=[]
    for stu in students:
        recs=Attendance.query.filter_by(student_id=stu.id,subject_id=subject_id).order_by(Attendance.date.desc()).all()
        total=len(recs); present=sum(1 for r in recs if r.status=="Present")
        result.append({"studentId":stu.id,"studentName":stu.name,"rollNo":stu.roll_no,
            "photo":stu.photo,"faceRegistered":stu.face_registered,
            "totalClasses":total,"present":present,"absent":total-present,
            "percentage":pct(present,total),"status":"Safe" if pct(present,total)>=75 else "At Risk",
            "records":[r.to_dict() for r in recs[:30]]})
    total_sessions=ClassSession.query.filter_by(subject_id=subject_id,status="Closed").count()
    return jsonify({"subject":sub.to_dict(),"students":result,"totalSessions":total_sessions})

# Edit logs
@app.route("/api/attendance/logs")
def api_edit_logs():
    q = AttendanceEditLog.query.order_by(AttendanceEditLog.id.desc())
    if session.get("role")=="teacher":
        q=q.filter_by(modified_by=session["name"])
    return jsonify([l.to_dict() for l in q.limit(200).all()])


# ══════════════════════════════════════════════════════════════════════════════
#  API — LEAVES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/leaves", methods=["GET"])
def api_leaves():
    q = LeaveRequest.query
    if session.get("role")=="student":
        q=q.filter_by(student_id=session["user_id"])
    elif session.get("role")=="teacher":
        tid = session["user_id"]
        my_sub_ids=[s.id for s in Subject.query.filter_by(teacher_id=tid).all()]
        my_mentee_ids=[s.id for s in Student.query.filter_by(mentor_id=tid).all()]
        # A teacher sees: (a) subject-specific leaves for their own subjects,
        # and (b) full-day/general leaves (no subject) from their own mentees.
        q=q.filter(db.or_(
            LeaveRequest.subject_id.in_(my_sub_ids),
            db.and_(LeaveRequest.subject_id.is_(None), LeaveRequest.student_id.in_(my_mentee_ids)),
        ))
    if request.args.get("status"): q=q.filter_by(status=request.args["status"])
    return jsonify([l.to_dict() for l in q.order_by(LeaveRequest.submitted_at.desc()).all()])

@app.route("/api/leaves", methods=["POST"])
@student_required
def api_apply_leave():
    d = request.json
    if not d.get("fromDate") or not d.get("toDate") or not (d.get("reason") or "").strip():
        return jsonify({"error":"fromDate, toDate and reason are required"}),400
    subject_id = d.get("subjectId") or None
    lv = LeaveRequest(id=uid("LV"),student_id=session["user_id"],
        subject_id=subject_id,
        from_date=d["fromDate"],to_date=d["toDate"],
        reason=d["reason"],document_b64=d.get("document"))
    db.session.add(lv); db.session.commit()
    # Route the notification per the workflow:
    #   subject selected      -> that subject's teacher only
    #   no subject (full-day) -> the student's assigned mentor only
    if subject_id:
        sub = Subject.query.get(subject_id)
        if sub and sub.teacher_id:
            push_notif(sub.teacher_id,"teacher",
                f"Leave request from {session['name']} for {sub.name} ({lv.from_date}→{lv.to_date})","info")
    else:
        stu = Student.query.get(session["user_id"])
        if stu and stu.mentor_id:
            push_notif(stu.mentor_id,"teacher",
                f"Full-day leave request from {session['name']} ({lv.from_date}→{lv.to_date})","info")
        else:
            push_notif(session["user_id"],"student",
                "Your leave request was submitted, but you don't have a mentor assigned yet — "
                "ask your admin to assign one so a teacher can review it.","warn")
    db.session.commit()
    return jsonify({"ok":True,"leave":lv.to_dict()})

@app.route("/api/leaves/<lid>/review", methods=["POST"])
def api_review_leave(lid):
    """Only the teacher who actually owns this leave request may approve or
    reject it — the subject's own teacher for a subject-specific leave, or
    the student's assigned mentor for a full-day leave. Admin can see every
    leave request (read-only oversight) but does not approve/reject them;
    that decision belongs to the teacher/mentor, per the intended workflow."""
    if session.get("role") != "teacher":
        return jsonify({"error":"Only the responsible teacher or mentor can approve or reject a leave request"}),403
    lv = LeaveRequest.query.get_or_404(lid); d = request.json
    tid = session["user_id"]
    if lv.subject_id:
        # Subject-specific leave: only that subject's own teacher may review
        sub = Subject.query.get(lv.subject_id)
        if not sub or sub.teacher_id != tid:
            return jsonify({"error":"Only the subject's teacher can review this leave"}),403
    else:
        # Full-day leave: only the student's assigned mentor may review
        stu = Student.query.get(lv.student_id)
        if not stu or stu.mentor_id != tid:
            return jsonify({"error":"Only the student's assigned mentor can review this leave"}),403
    lv.status=d["status"]; lv.teacher_remark=d.get("remark","")
    lv.reviewed_by=session["name"]; lv.reviewed_at=today()
    db.session.commit()
    push_notif(lv.student_id,"student",
        f"Leave {d['status']}: {lv.from_date}→{lv.to_date}. {lv.teacher_remark}",
        "success" if d["status"]=="Approved" else "warn")
    db.session.commit()
    return jsonify({"ok":True})

@app.route("/api/leaves/<lid>", methods=["DELETE"])
def api_delete_leave(lid):
    if session.get("role") not in ["admin","teacher"]: return jsonify({"error":"Unauthorized"}),403
    lv = LeaveRequest.query.get_or_404(lid)
    db.session.delete(lv); db.session.commit()
    return jsonify({"ok":True})


# ══════════════════════════════════════════════════════════════════════════════
#  API — CORRECTIONS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/corrections", methods=["GET"])
def api_corrections():
    q = CorrectionRequest.query
    if session.get("role")=="student":
        q=q.filter_by(student_id=session["user_id"])
    elif session.get("role")=="teacher":
        my_sub_ids=[s.id for s in Subject.query.filter_by(teacher_id=session["user_id"]).all()]
        q=q.filter(CorrectionRequest.subject_id.in_(my_sub_ids))
    return jsonify([c.to_dict() for c in q.order_by(CorrectionRequest.submitted_at.desc()).all()])

@app.route("/api/corrections", methods=["POST"])
@student_required
def api_apply_correction():
    d = request.json
    cr = CorrectionRequest(id=uid("CR"),student_id=session["user_id"],
        attendance_id=d.get("attendanceId"),subject_id=d.get("subjectId"),
        date=d["date"],message=d["message"],current_status=d.get("currentStatus","Absent"))
    db.session.add(cr); db.session.commit()
    return jsonify({"ok":True,"correction":cr.to_dict()})

@app.route("/api/corrections/<cid>/review", methods=["POST"])
def api_review_correction(cid):
    """Only the subject's own teacher may approve or reject a correction
    request — admin can see every correction (read-only oversight) but does
    not approve/reject, matching the leave-request workflow. A correction
    with no subject attached (shouldn't normally happen, since every
    attendance record belongs to a subject) is rejected outright rather
    than silently allowed through by any teacher."""
    if session.get("role") != "teacher":
        return jsonify({"error":"Only the subject's teacher can approve or reject a correction request"}),403
    cr = CorrectionRequest.query.get_or_404(cid); d = request.json
    if not cr.subject_id:
        return jsonify({"error":"This correction has no subject on record and cannot be reviewed"}),400
    sub = Subject.query.get(cr.subject_id)
    if not sub or sub.teacher_id != session["user_id"]:
        return jsonify({"error":"Only the subject's teacher can review this correction"}),403
    cr.status=d["status"]; cr.teacher_remark=d.get("remark",""); cr.reviewed_by=session["name"]
    if d["status"]=="Approved" and cr.attendance_id:
        att = Attendance.query.get(cr.attendance_id)
        if att:
            old = att.status
            log = AttendanceEditLog(attendance_id=att.id,student_name=att.student.name if att.student else "",
                subject_name=att.subject.name if att.subject else "",date=att.date,
                old_status=old,new_status="Present",modified_by=session["name"],
                modified_by_role=session["role"],reason="Correction approved",modified_at=now_str())
            att.status="Present"; att.edited=True; att.remarks="Correction approved"
            if not att.original_status: att.original_status=old
            db.session.add(log)
    db.session.commit()
    push_notif(cr.student_id,"student",
        f"Correction {d['status']} for {cr.date}. {cr.teacher_remark}",
        "success" if d["status"]=="Approved" else "warn")
    db.session.commit()
    return jsonify({"ok":True})


# ══════════════════════════════════════════════════════════════════════════════
#  API — TEACHER PROFILE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/teacher/profile", methods=["PUT"])
@teacher_required
def api_update_teacher_profile():
    t = Teacher.query.get(session["user_id"]); d = request.json
    for f in ["name","phone","department","qualification"]:
        if f in d: setattr(t,f,d[f])
    if d.get("newPassword"):
        if not d.get("currentPassword") or not t.check_password(d["currentPassword"]):
            return jsonify({"error":"Current password incorrect"}),400
        t.set_password(d["newPassword"])
    db.session.commit()
    session["name"] = t.name
    return jsonify({"ok":True,"teacher":t.to_dict()})


# ══════════════════════════════════════════════════════════════════════════════
#  API — ADMIN PROFILE (change own email / password)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/admin/profile", methods=["PUT"])
@admin_required
def api_update_admin_profile():
    """Lets the logged-in admin change their own login email and/or password.
    Requires the current password to confirm identity before any change is
    made, and the new credentials are hashed and saved to the database so
    they take effect for all future logins."""
    a = Admin.query.get(session["user_id"]); d = request.json
    if not d.get("currentPassword") or not a.check_password(d["currentPassword"]):
        return jsonify({"error":"Current password is incorrect"}),400

    new_email = (d.get("email") or "").strip()
    if new_email and new_email != a.email:
        if Admin.query.filter(Admin.email==new_email, Admin.id!=a.id).first():
            return jsonify({"error":"That email is already in use"}),400
        a.email = new_email

    if d.get("name"): a.name = d["name"]

    if d.get("newPassword"):
        if len(d["newPassword"]) < 6:
            return jsonify({"error":"New password must be at least 6 characters"}),400
        a.set_password(d["newPassword"])

    db.session.commit()
    session["name"] = a.name
    return jsonify({"ok":True,"admin":a.to_dict()})


# ══════════════════════════════════════════════════════════════════════════════
#  API — REPORTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/reports/pdf/<subject_id>")
def api_pdf_report(subject_id):
    if session.get("role") not in ["admin","teacher"]: return jsonify({"error":"Unauthorized"}),403
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        sub  = Subject.query.get_or_404(subject_id)
        stus = Student.query.filter_by(status="Active",department=sub.department).all()
        buf  = io.BytesIO()
        doc  = SimpleDocTemplate(buf,pagesize=A4); st=getSampleStyleSheet(); elems=[]

        try: inst=json.loads(open("data/system_settings.json").read()).get("institutionName","FaceAttend Pro")
        except: inst="FaceAttend Pro"

        elems.append(Paragraph(inst, st["Title"]))
        elems.append(Paragraph(f"Attendance Report — {sub.name} ({sub.code})", st["Heading2"]))
        elems.append(Paragraph(f"Teacher: {sub.teacher.name if sub.teacher else '—'} | Generated: {now_str()}", st["Normal"]))
        elems.append(Spacer(1,18))

        data=[["Roll No","Student Name","Total","Present","Absent","Percentage","Status"]]
        for stu in stus:
            recs=Attendance.query.filter_by(student_id=stu.id,subject_id=subject_id).count()
            pres=Attendance.query.filter_by(student_id=stu.id,subject_id=subject_id,status="Present").count()
            if not recs: continue
            rate=pct(pres,recs)
            data.append([stu.roll_no,stu.name,recs,pres,recs-pres,f"{rate}%","✓ Safe" if rate>=75 else "⚠ Risk"])

        t=Table(data,repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A7FD4")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#EBF4FF")]),
            ("GRID",(0,0),(-1,-1),.5,colors.HexColor("#C2D8F0")),
            ("PADDING",(0,0),(-1,-1),8),
        ]))
        elems.append(t); doc.build(elems); buf.seek(0)
        return send_file(buf,mimetype="application/pdf",as_attachment=True,
                         download_name=f"report_{sub.code}_{today()}.pdf")
    except ImportError:
        return jsonify({"error":"Install reportlab: pip install reportlab"}),500

@app.route("/api/reports/csv/<subject_id>")
def api_csv_report(subject_id):
    if session.get("role") not in ["admin","teacher"]: return jsonify({"error":"Unauthorized"}),403
    import csv
    sub  = Subject.query.get_or_404(subject_id)
    recs = Attendance.query.filter_by(subject_id=subject_id).order_by(Attendance.date.desc()).all()
    out  = io.StringIO(); w=csv.writer(out)
    w.writerow(["Student ID","Name","Roll No","Date","Time","Status","Confidence","Marked By","Remarks","Edited"])
    for r in recs:
        w.writerow([r.student_id,r.name,r.student.roll_no if r.student else "",
                    r.date,r.time,r.status,r.confidence,r.marked_by,r.remarks,"Yes" if r.edited else "No"])
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()),mimetype="text/csv",
                     as_attachment=True,download_name=f"{sub.code}_{today()}.csv")

@app.route("/api/teacher/analytics")
@teacher_required
def api_teacher_analytics():
    tid = session["user_id"]
    my_subs = Subject.query.filter_by(teacher_id=tid).all()
    sub_ids = [s.id for s in my_subs]
    t = today()
    total_att = Attendance.query.filter(Attendance.subject_id.in_(sub_ids)).count()
    present   = Attendance.query.filter(Attendance.subject_id.in_(sub_ids),Attendance.status=="Present").count()
    trend=[]
    for i in range(7):
        d=(datetime.date.today()-datetime.timedelta(days=i)).isoformat()
        trend.insert(0,{"date":d,
            "present":Attendance.query.filter(Attendance.subject_id.in_(sub_ids),Attendance.date==d,Attendance.status=="Present").count(),
            "absent": Attendance.query.filter(Attendance.subject_id.in_(sub_ids),Attendance.date==d,Attendance.status=="Absent").count()})
    sub_stats=[]
    for sub in my_subs:
        tot=Attendance.query.filter_by(subject_id=sub.id).count()
        pre=Attendance.query.filter_by(subject_id=sub.id,status="Present").count()
        sub_stats.append({"id":sub.id,"name":sub.name,"code":sub.code,"total":tot,"present":pre,"rate":pct(pre,tot)})
    return jsonify({
        "mySubjects":len(my_subs),"totalAttendance":total_att,"present":present,
        "overallRate":pct(present,total_att),
        "todaySessions":ClassSession.query.filter_by(teacher_id=tid,date=t).count(),
        "activeSessions":ClassSession.query.filter_by(teacher_id=tid,status="Active").count(),
        "pendingLeaves":LeaveRequest.query.filter(LeaveRequest.subject_id.in_(sub_ids),LeaveRequest.status=="Pending").count(),
        "pendingCorrections":CorrectionRequest.query.filter(CorrectionRequest.subject_id.in_(sub_ids),CorrectionRequest.status=="Pending").count(),
        "trend":trend,"subjectStats":sub_stats,
    })


# ══════════════════════════════════════════════════════════════════════════════
#  BOOT
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_new_columns():
    """db.create_all() only creates missing TABLES, it never ALTERs existing
    ones. This app has no Alembic migration history, so for installs that
    already had a database before the mentor/mentee feature was added, we
    add the new columns here if they're missing — safe to run every boot."""
    from sqlalchemy import inspect, text
    try:
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())

        def add_column_if_missing(table, column, ddl_type):
            if table not in existing_tables:
                return  # table doesn't exist yet — create_all() will make it fresh, already correct
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
                db.session.commit()
                print(f"[migration] Added missing column {table}.{column}")

        add_column_if_missing("students", "mentor_id", "VARCHAR(20)")
        add_column_if_missing("archived_students", "password_hash", "VARCHAR(256)")
        add_column_if_missing("archived_students", "year", "INTEGER")
        add_column_if_missing("archived_students", "phone", "VARCHAR(30)")
        add_column_if_missing("archived_students", "photo", "TEXT")
        add_column_if_missing("archived_students", "face_encoding", "JSON")
        add_column_if_missing("archived_students", "face_registered", "BOOLEAN")
        add_column_if_missing("archived_students", "mentor_id", "VARCHAR(20)")
        add_column_if_missing("archived_students", "enrolled_at", "VARCHAR(20)")
    except Exception as e:
        # Don't block app startup over a best-effort migration — worst case,
        # db.create_all() below still creates everything correctly for fresh installs.
        print(f"[migration] Skipped column check: {e}")

with app.app_context():
    db.create_all()
    _ensure_new_columns()
    seed()

# Start auto-close background thread
t = threading.Thread(target=auto_close_worker, daemon=True)
t.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT",5000))
    print("\n"+"="*60)
    print("  🎓  FaceAttend Pro v5 — Complete Attendance System")
    print(f"  ▶   http://localhost:{port}")
    print("  🛡   Admin   : admin@demo.com   / admin123")
    print("  👨‍🏫   Teacher : kumar@demo.com   / teacher123")
    print("  🎓   Student : kavya@demo.com   / student123")
    print("="*60+"\n")
    app.run(debug=True, port=port, use_reloader=False)
