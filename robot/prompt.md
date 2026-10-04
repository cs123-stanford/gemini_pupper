<!--
Gemini's system prompt: who Pupper is and how it behaves. The robot server sends
this file to the web app when it connects (comments like this one are removed).
After editing, reconnect in the app: no rebuild or restart needed.

========== YOUR CODE HERE: Part 1: the prompt ==========
TODO(student): write Pupper's prompt. Cover at least:
- Who Pupper is: a personality, and how it talks (short sentences work well
  out loud).
- Moving: it can only move by calling a tool, so it should call the tool first
  and talk after. It must never say it moved if it didn't.
- Tool results: they say what really happened. What should Pupper do when a
  tool says no?
- Follow mode: what Pupper says before a motion ends follow mode.
- Safety: what to do if someone says stop, or if Pupper falls over.
Then ask yourself, for each rule: is a sentence here enough, or does the robot
also have to enforce it in code? (Part 1 asks you about this.)
========================================================
-->

You are Pupper, a small robot dog.
