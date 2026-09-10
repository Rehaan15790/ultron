from typing import List, Dict, Any

class HistoryManager:
    def __init__(self, system_message: str):
        if not system_message:
            raise ValueError("System message cannot be empty")
        self.system_message = system_message
        self.conversation: List[Dict[str, str]] = []
        self.max_turns = 20 # P1 simple truncation limit

    def add_user_message(self, text: str):
        self.conversation.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str):
        self.conversation.append({"role": "assistant", "content": text})

    def pop_last(self):
        """Drop the most recent entry - used to roll back a failed turn."""
        if self.conversation:
            self.conversation.pop()

    def get_messages(self, system_context: str = "") -> List[Dict[str, Any]]:
        """
        Build the message list. `system_context` (e.g. user profile memory) is
        appended to the SYSTEM message at call time rather than stored in the
        conversation, so it never accumulates and is never attributed to the user.
        """
        system_content = self.system_message
        if system_context:
            system_content = f"{self.system_message}\n\n{system_context}"

        messages = [{"role": "system", "content": system_content}]

        # Truncate if conversation gets too long (keep the most recent turns)
        if len(self.conversation) > self.max_turns * 2:
            self.conversation = self.conversation[-(self.max_turns * 2):]

        messages.extend(self.conversation)
        return messages

    def clear(self):
        self.conversation.clear()
