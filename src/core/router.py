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

    # Tier 1 commands take an argument, so they cannot be matched by exact
    # token sequence. They use an explicit "verb: argument" grammar, matching
    # the existing "remember:" / "forget:" convention.
    #
    # Requiring the colon is deliberate. A bare leading verb would hijack
    # ordinary conversation - "read me something" would become a file read -
    # and P1's whole premise is that routing is unambiguous rather than
    # best-guess.
    COMMAND_PREFIXES = {
        "list": "list_files_tool",
        "read": "read_file_tool",
        "find": "find_files_tool",
        "search": "search_files_tool",
        "tree": "tree_tool",
    }

    @classmethod
    def route_command(cls, clean_text: str) -> tuple[str, str] | None:
        """
        Match "verb: argument". Returns (tool_name, argument) or None.
        The argument is returned raw - the tool is responsible for validating
        it, and for filesystem tools that means fs_sandbox.resolve_path().
        """
        if ":" not in clean_text:
            return None

        verb, _, argument = clean_text.partition(":")
        tool_name = cls.COMMAND_PREFIXES.get(verb.strip().lower())
        if tool_name is None:
            return None
        return tool_name, argument.strip()

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