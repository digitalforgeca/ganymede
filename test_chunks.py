import asyncio
from ganymede.core.schema import Text
import google.antigravity.types as gatypes

t = Text(text="hi", step_index=0)
print("schema text name:", t.__class__.__name__)

t2 = gatypes.Text(text="hi2", step_index=0)
print("google text name:", t2.__class__.__name__)
