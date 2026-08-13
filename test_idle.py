import json

payload = {
  "conversationId": "a2c1db46-ea91-4887-8cfb-90b26385ec88",
  "fullyIdle": False, 
  "tasks": {"outstanding": 1}
}
print("is_interactive_tool: False")
print("fullyIdle:", payload.get("fullyIdle"))
