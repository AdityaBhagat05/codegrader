# db_manager.py
import sqlite3
from typing import List, Tuple, Optional, Dict

DB_NAME = "grader_results.db"

def get_connection():
    """Create a connection to the SQLite database."""
    return sqlite3.connect(DB_NAME)

def create_table():
    """Create the results table if it doesn't exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reg_no TEXT NOT NULL,
                name TEXT NOT NULL,
                score REAL,
                result TEXT
            )
        ''')
        conn.commit()

def insert_result(reg_no: str, name: str, score: float, result: str):
    """Insert a new grading record."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO results (reg_no, name, score, result) VALUES (?, ?, ?, ?)',
            (reg_no, name, score, result)
        )
        conn.commit()

def update_result(reg_no: str, score: float, result: str):
    """Update an existing record for a student."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE results SET score = ?, result = ? WHERE reg_no = ?',
            (score, result, reg_no)
        )
        conn.commit()

def fetch_all_results() -> List[Tuple]:
    """Fetch all stored results."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM results')
        return cursor.fetchall()

def fetch_result_by_reg(reg_no: str) -> Optional[Dict]:
    """Fetch a single record by registration number."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM results WHERE reg_no = ?', (reg_no,))
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "reg_no": row[1],
                "name": row[2],
                "score": row[3],
                "result": row[4]
            }
        return None

def delete_result(reg_no: str):
    """Delete a record by registration number."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM results WHERE reg_no = ?', (reg_no,))
        conn.commit()

# Automatically ensure table exists when module is imported
create_table()
