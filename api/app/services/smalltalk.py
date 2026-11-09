"""Greetings and content-free inputs ("hey", "what?", "help", "thanks").

They are not questions about the documents, so retrieval can only find noise and the
relevance floor would answer "not covered by the documents", which is true but unhelpful.
This step runs before retrieval: it costs no embedding and no model call, never cites
anything, and never answers from the corpus. Anything with real content goes on to the
normal pipeline.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9']+")
_GREETING = {"hi", "hey", "hello", "salam", "salaam", "assalamualaikum", "aoa", "yo", "hii",
             "hiya", "greetings", "morning", "evening", "afternoon", "good"}
_THANKS = {"thanks", "thank", "thx", "ty", "shukriya", "jazakallah"}
_HELP = {"help", "what", "how", "why", "who", "huh", "ok", "okay", "hmm", "test", "testing",
         "you", "u", "are", "can", "do", "there", "anyone", "start", "menu", "options",
         "this", "is", "it", "me", "please", "pls"}
_FILLER = {"a", "an", "the", "to", "of", "and", "so", "um", "uh", "bro", "sir", "rahbar"}

EXAMPLES = ("What minimum CGPA keeps me off academic warning?",
            "What is the deadline to withdraw from a course?",
            "How much is the tuition fee per credit hour?")

GREETING_REPLY = ("Hi! I am RAHBAR. I answer questions about FAST-NUCES academic rules, fees "
                  "and student policies, using only the official documents, and I cite the "
                  "clause I used. Try, for example: " + " / ".join(EXAMPLES))
THANKS_REPLY = "You're welcome! Ask me anything else about FAST-NUCES rules, fees or policies."
VAGUE_REPLY = ("Could you ask a complete question? I answer questions about FAST-NUCES academic "
               "rules, fees and student policies, for example: " + " / ".join(EXAMPLES))


def classify(question: str) -> str | None:
    """'greeting', 'thanks' or 'vague' for inputs with no document content, else None."""
    words = _WORD.findall(question.lower())
    content = [w for w in words if w not in _FILLER]
    if not content or len(content) > 4:
        return None if content else "vague"
    if all(w in _GREETING | _HELP | _FILLER for w in content) and set(content) & _GREETING:
        return "greeting"
    if all(w in _THANKS | _FILLER | {"you", "u", "so", "much", "a", "lot", "ok", "okay"}
           for w in content) and set(content) & _THANKS:
        return "thanks"
    if all(w in _HELP | _GREETING for w in content):
        return "vague"
    return None


def reply(kind: str) -> str:
    return {"greeting": GREETING_REPLY, "thanks": THANKS_REPLY}.get(kind, VAGUE_REPLY)
