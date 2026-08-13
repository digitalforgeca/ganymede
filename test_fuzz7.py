from ganymede.platforms.discord.formatter import DiscordFormatter

with open("fail_content.txt", "r") as f:
    content = f.read()

limit = 2000
chunks = []
current_chunk = []
current_length = 0
in_code_block = False
code_block_lang = ""

for line in content.splitlines(keepends=True):
    is_fence = line.strip().startswith("```")
    fence_lang = line.strip().replace("```", "") if is_fence else ""

    while line:
        line_len = len(line)
        space_left = limit - current_length - (4 if in_code_block else 0)

        if line_len <= space_left:
            current_chunk.append(line)
            current_length += line_len
            if is_fence:
                in_code_block = not in_code_block
                if in_code_block:
                    code_block_lang = fence_lang
            break

        has_content = len(current_chunk) > (1 if in_code_block else 0)
        if has_content:
            if in_code_block:
                current_chunk.append("```\n")
            c = "".join(current_chunk)
            if len(c) > 2000:
                print("PUSHED CHUNK > 2000!", len(c))
                print("has_content branch")
                print("pieces lengths:", [len(p) for p in current_chunk])
                print("current_length was:", current_length)
                import sys; sys.exit(1)
            chunks.append(c)
            
            current_chunk = []
            current_length = 0
            if in_code_block:
                prefix = f"```{code_block_lang}\n"
                current_chunk.append(prefix)
                current_length = len(prefix)
            continue

        take_chars = max(1, space_left)
        part = line[:take_chars]
        line = line[take_chars:]
        
        current_chunk.append(part)
        if in_code_block:
            current_chunk.append("```\n")
        c = "".join(current_chunk)
        if len(c) > 2000:
            print("PUSHED CHUNK > 2000!", len(c))
            print("forcibly split branch")
        chunks.append(c)
        
        current_chunk = []
        current_length = 0
        if in_code_block:
            prefix = f"```{code_block_lang}\n"
            current_chunk.append(prefix)
            current_length = len(prefix)

