import os


os.environ.setdefault(
    'DATABASE_PATH',
    os.path.join(os.path.expanduser('~'), 'tennissel.sqlite3'),
)
os.environ.setdefault(
    'SESSION_FILE_DIR',
    os.path.join(os.path.expanduser('~'), 'tennissel_sessions'),
)

from app import app as application
