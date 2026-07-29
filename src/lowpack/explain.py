"""Render stored, reproducible codec decisions."""

from __future__ import annotations

from typing import Any


def explain_manifest(manifest: dict[str, Any]) -> str:
    lines: list[str] = []
    for item in manifest["files"]:
        decision = item["decision"]
        transform = item.get("transform", {})
        lines.append(str(item["path"]))
        detected = transform.get("detected", [])
        applied = transform.get("applied", [])
        if detected:
            lines.append("\nDetected:")
            lines.extend(f"  {value}" for value in detected)
        if applied:
            lines.append("\nApplied:")
            lines.extend(f"  {value}" for value in applied)
        level = decision.get("level")
        lines.append(
            f"\nFinal codec:\n  {decision['final_codec']}"
            + (f" level {level}" if level is not None else "")
        )
        lines.append(f"\nReason:\n  {decision['reason']}.")
        rejected = [
            candidate
            for candidate in decision["candidates"]
            if candidate["codec"] != decision["final_codec"]
        ]
        if rejected:
            lines.append("\nRejected candidates:")
            for candidate in rejected:
                lines.append(
                    f"  {candidate['codec']} level {candidate['level']} — "
                    f"{candidate['packed_bytes']} packed bytes from "
                    f"{candidate['sample_bytes']} sampled bytes"
                )
        lines.append("\nThese results apply to the sampled input and recorded codec environment.\n")
    return "\n".join(lines).rstrip()
