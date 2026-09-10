import sqlite3
import json
from pathlib import Path

class MemoryManager:
    def __init__(self, db_path: Path | str = "ultron_memory.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT UNIQUE,
                    category TEXT
                )
            """)

    def add_memory(self, fact: str, category: str = "general"):
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT OR IGNORE INTO memories (fact, category) VALUES (?, ?)",
                    (fact, category)
                )
            return True
        except Exception as e:
            print(f"Memory Error: {e}")
            return False

    def remove_memory(self, keyword: str) -> bool:
        """Remove any memory containing the keyword."""
        try:
            with self.conn:
                cursor = self.conn.execute(
                    "DELETE FROM memories WHERE fact LIKE ?",
                    (f"%{keyword}%",)
                )
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Memory Error: {e}")
            return False

    def get_all_memories(self) -> str:
        cursor = self.conn.execute("SELECT fact, category FROM memories")
        rows = cursor.fetchall()
        
        if not rows:
            return "No specific user memories stored yet."
        
        memory_text = "USER PROFILE MEMORY:\n"
        for fact, category in rows:
            memory_text += f"- [{category.upper()}] {fact}\n"
        return memory_text

    def clear_memories(self):
        with self.conn:
            self.conn.execute("DELETE FROM memories")

# Singleton instance
memory = MemoryManager()