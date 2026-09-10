class ReflexRouter:
    # Exact token sequences allowed in P1. 
    # If the tokens match exactly, it returns the tool name.
    # If not, it returns None (meaning "send to Deep Core").
    ALLOWED_INTENTS = {
        ("help",): "help_tool",
        ("time",): "time_tool",
        ("date",): "date_tool",
        ("day",): "day_tool",
        ("status",): "status_tool",
        ("system", "status"): "system_status_tool",
        ("cpu",): "cpu_tool",
        ("ram",): "ram_tool",
    }

    @classmethod
    def route(cls, tokens: list[str]) -> str | None:
        """
        Takes a list of sanitized tokens and returns the tool name if it's an exact match.
        Returns None if it needs to go to Deep Core (the LLM).
        """
        # We convert the list to a tuple so it can be used as a dictionary key
        token_tuple = tuple(tokens)
        
        # Look up the exact sequence
        return cls.ALLOWED_INTENTS.get(token_tuple)