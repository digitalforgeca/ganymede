import uuid
ganymede_conv_id = "ganymede_discord_1529634249316110346"
sdk_conversation_id = str(uuid.uuid5(uuid.NAMESPACE_OID, ganymede_conv_id))
print(sdk_conversation_id)
