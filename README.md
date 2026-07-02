# Face-Recognition-Attendance-System
FaceAttend Pro is an AI-powered Face Recognition Attendance Management System built with Python, Flask, PostgreSQL, HTML, CSS, and JavaScript. It automates attendance using facial recognition and GPS verification, offering secure role-based access for Admin, Faculty, and Students, along with analytics, reports, and attendance management.

1. Overview & Purpose
FaceAttend Pro v5 is a comprehensive, role-based school/college attendance management system designed to eliminate manual roll-calls and proxy attendance. It replaces traditional attendance register logs with a secure biometric face-scanning client, validated by classroom geofencing (GPS Lock) and an automated session manager.

2. Key Modules & Role Capabilities

🛡️ Admin Module

The administrator is responsible for high-level management and system settings:

User Management: Add, update, or delete Teachers and Students.
Course Setup: Create subjects and assign them to specific teachers.
Leave Management: Review leave requests submitted by students (viewing details like remarks and reasons).
System Settings: Set global thresholds (attendance percentage warning threshold, GPS radius, face-scanning confidence limit).
Audit Trail: Access attendance_edit_logs to monitor who changed whose attendance, when, and why.
Reports: Generate and export reports (PDF + CSV format).

👨‍🏫 Teacher Module

Teachers manage class schedules and review attendance:

Start Sessions: Select a subject and start an attendance window, specifying a custom duration (e.g., 60 minutes) and classroom coordinates.
Manage Sessions: Reopen today's closed sessions, manually close a session, or extend active sessions (+15/30 minutes).
Correction Logs: Edit a student's attendance records (Absent ↔ Present) by writing a mandatory reason, which is automatically saved to the audit trail.
Leaves & Correction Requests: Approve or reject leave applications and attendance correction requests from students.

🎓 Student Module

Students access a personal portal to scan and verify their presence:

Register Face: Captures a webcam image and runs the neural network encoder to extract a unique biometric key.
Attendance Scan: Scans face to verify identity during active classes. Must be inside the classroom GPS geofencing radius.
Attendance Dashboard: Displays progress rings for attendance percentages per subject and flags subjects falling below the warning threshold (e.g., <75%).
Requests & Leaves: Apply for leaves (with date ranges and document uploads) and request corrections if face matching failed.

3. Technology Stack & Mechanics
   
Backend: Flask web application in 
app.py
/faceattend_v5/app.py) using SQLite database configuration.
Frontend: Dynamic UI built using HTML5, CSS, and Vanilla JavaScript. Includes webcam streaming via WebRTC API and GPS tracking via HTML5 Geolocation API.
Face Recognition:
Primary Model: Uses dlib to detect faces and maps 68 key points into a 128-dimensional floating-point vector. The similarity is measured using Euclidean Distance.
Fallback Model: Resizes images to 20×20 grayscale matrices and evaluates similarity using Normalized Cross-Correlation (NCC).
GPS Validation: Computes student-to-teacher distance using the Haversine Formula to prevent out-of-classroom check-ins.
Background Process: An asynchronous thread runs a daemon worker every 30 seconds to close expired sessions and auto-mark absent students.

5. Code & File Structure
The project contains the following primary files and directories:

app.py
/faceattend_v5/app.py): Contains the main application controller, database models, Flask routing (Auth, Admin, Teacher, Student, APIs), biometric comparison modules, and background threads.
.env
/faceattend_v5/.env): System environment variables configuring the database URL (sqlite:///faceattend.db), server port, and session secret keys.
requirements.txt
/faceattend_v5/requirements.txt): List of dependencies (flask, flask-sqlalchemy, dlib, face-recognition, numpy, pillow, reportlab, etc.).
templates/: Contains the HTML templates separated by user dashboard roles:
auth/: Login interface.
admin/: Manage users, settings, and logs.
teacher/: Live sessions, corrections, and profile.
student/: Face register, scan, and leaves.
static/: Contains CSS styling (static/css/style.css) and modular Javascript APIs (static/js/shared.js).


FaceAttend Pro is designed as a lightweight, scalable, and user-friendly application, making it an ideal solution for educational institutions and an excellent MCA final-year project that demonstrates practical applications of Artificial Intelligence, Computer Vision, and Web Development.
