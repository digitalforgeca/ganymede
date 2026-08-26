"""Unified JSONL transcript parsing and artifact extraction logic for Ganymede."""

import os
import json
import re
import shutil
import structlog
from typing import Any
from ganymede.core.constants import DEFAULT_GANYMEDE_PORT

logger = structlog.get_logger()


class TranscriptParser:
    """Parses agent JSONL transcripts and extracts structured execution artifacts."""

    @staticmethod
    def parse_transcript(transcript_path: str) -> tuple[str, list[dict], list[dict]]:
        """Parses an agent JSONL transcript file.
        
        Returns:
            Tuple of (final_response_text, artifacts_created, interactive_tools)
        """
        final_text = ""
        tool_calls = []
        artifacts_created = []
        interactive_tools = []

        if not transcript_path or not os.path.exists(transcript_path):
            return final_text, artifacts_created, interactive_tools

        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Bound the turn to the last USER_INPUT or SYSTEM_MESSAGE
            start_idx = 0
            for i in range(len(lines) - 1, -1, -1):
                try:
                    data = json.loads(lines[i])
                    t = data.get("type", "")
                    src = data.get("source", "")
                    content = str(data.get("content", ""))
                    if t in ("USER_INPUT", "SYSTEM_MESSAGE") or src in ("USER_EXPLICIT", "SYSTEM") or "<SYSTEM_MESSAGE>" in content:
                        start_idx = i
                        break
                except Exception:
                    continue

            for i in range(start_idx, len(lines)):
                try:
                    data = json.loads(lines[i])
                    if data.get("type") in ("PLANNER_RESPONSE", "TEXT_RESPONSE"):
                        content = data.get("content", "")
                        if content:
                            final_text = content
                    if data.get("tool_calls"):
                        tool_calls.extend(data.get("tool_calls"))
                except Exception:
                    continue
        except Exception as e:
            logger.error("Failed to parse transcript file", error=str(e), path=transcript_path)

        for t in tool_calls:
            t_name = t.get("name", "")
            args = t.get("args", {})
            args_obj = {}
            try:
                if isinstance(args, str):
                    args_obj = json.loads(args)
                elif isinstance(args, dict):
                    args_obj = args

                if t_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                    meta = args_obj.get("ArtifactMetadata", {})
                    if meta and (meta.get("UserFacing") or meta.get("RequestFeedback")):
                        tf = args_obj.get("TargetFile")
                        summary = meta.get("Summary", "")
                        if tf and not any(a["file"] == tf for a in artifacts_created):
                            artifacts_created.append({"file": tf, "summary": summary})
            except Exception:
                pass

            if "ask_question" in t_name or "ask_permission" in t_name:
                interactive_tools.append({"name": t_name, "args": args_obj})

        return final_text, artifacts_created, interactive_tools

    @staticmethod
    def extract_artifact_files(response: Any, response_text: str) -> list[str]:
        """Extracts existing valid local file paths from response metadata and markdown links."""
        artifact_files = list(getattr(response, "artifact_files", [])) if response else []
        file_links = re.findall(r'\[.*?\]\(file://(.*?)\)|`?file://(.*?)`?', response_text or "")
        for match in file_links:
            path = match[0] or match[1]
            if path and path not in artifact_files and os.path.isabs(path) and os.path.isfile(path):
                artifact_files.append(path)
        return artifact_files

    @staticmethod
    def sync_artifacts(artifacts_created: list[dict], channel_brain_dir: str) -> list[str]:
        """Copies newly created artifacts from subagent directories into the channel's root brain directory."""
        os.makedirs(channel_brain_dir, exist_ok=True)
        synced_paths = []
        for art in artifacts_created:
            target_file = art.get("file")
            if target_file and os.path.exists(target_file):
                name = os.path.basename(target_file)
                dest_file = os.path.join(channel_brain_dir, name)
                synced_paths.append(dest_file)
                if target_file != dest_file:
                    try:
                        shutil.copy2(target_file, dest_file)
                    except Exception as e:
                        logger.error("Failed to copy artifact to channel brain dir", error=str(e), source=target_file, dest=dest_file)
        return synced_paths

    @staticmethod
    def format_artifact_review_text(artifacts_created: list[dict], dashboard_port: int = DEFAULT_GANYMEDE_PORT) -> str:
        """Formats the markdown block presenting created artifacts for user review."""
        if not artifacts_created:
            return ""
        dash_url = f"http://127.0.0.1:{dashboard_port}"
        lines = ["**📄 Artifacts Requiring Review:**"]
        for art in artifacts_created:
            name = os.path.basename(art.get("file", "Unknown File"))
            summary = art.get("summary", "")
            lines.append(f"- **{name}**: {summary}")
        lines.append(f"\n👉 [Open Ganymede Dashboard to review]({dash_url})")
        return "\n".join(lines)
