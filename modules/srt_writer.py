# modules/srt_writer.py
"""
Generador multi-formato de archivos de subtítulos.
Soporta SRT, VTT (WebVTT), SBV (YouTube), y JSON enriquecido.
"""

import json
import os


def _seconds_to_srt_time(seconds: float) -> str:
    """Convierte segundos a formato SRT: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _seconds_to_vtt_time(seconds: float) -> str:
    """Convierte segundos a formato VTT: HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _seconds_to_sbv_time(seconds: float) -> str:
    """Convierte segundos a formato SBV: H:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"


def write_srt(blocks: list[dict], output_path: str) -> str:
    """
    Genera archivo SRT estándar.

    Formato:
        1
        00:00:01,200 --> 00:00:03,800
        Hello, welcome to the show.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    lines = []
    for i, block in enumerate(blocks, 1):
        start = _seconds_to_srt_time(block["start_sec"])
        end = _seconds_to_srt_time(block["end_sec"])
        text = block.get("text_translated", block["text"])
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def write_vtt(blocks: list[dict], output_path: str) -> str:
    """
    Genera archivo WebVTT para uso en HTML5 <track>.

    Formato:
        WEBVTT

        00:00:01.200 --> 00:00:03.800
        Hello, welcome to the show.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    lines = ["WEBVTT", ""]
    for block in blocks:
        start = _seconds_to_vtt_time(block["start_sec"])
        end = _seconds_to_vtt_time(block["end_sec"])
        text = block.get("text_translated", block["text"])
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def write_sbv(blocks: list[dict], output_path: str) -> str:
    """
    Genera archivo SBV (YouTube subtitle format).

    Formato:
        0:00:01.200,0:00:03.800
        Hello, welcome to the show.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    lines = []
    for block in blocks:
        start = _seconds_to_sbv_time(block["start_sec"])
        end = _seconds_to_sbv_time(block["end_sec"])
        text = block.get("text_translated", block["text"])
        lines.append(f"{start},{end}")
        lines.append(text)
        lines.append("")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def write_json(
    blocks: list[dict],
    output_path: str,
    video_info: dict = None,
    language_info: dict = None,
    zone_info: dict = None,
) -> str:
    """
    Genera archivo JSON enriquecido con metadatos completos.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    data = {
        "version": "1.0",
        "generator": "SubtitleForge",
        "video": video_info or {},
        "language": language_info or {},
        "subtitle_zone": zone_info or {},
        "total_subtitles": len(blocks),
        "subtitles": [],
    }

    # Calculate stats
    if blocks:
        durations = [b["duration_sec"] for b in blocks]
        data["stats"] = {
            "avg_duration_sec": round(sum(durations) / len(durations), 2),
            "min_duration_sec": round(min(durations), 2),
            "max_duration_sec": round(max(durations), 2),
            "total_duration_sec": round(sum(durations), 2),
        }

    for block in blocks:
        entry = {
            "index": block["index"],
            "start": _seconds_to_srt_time(block["start_sec"]),
            "end": _seconds_to_srt_time(block["end_sec"]),
            "start_sec": block["start_sec"],
            "end_sec": block["end_sec"],
            "duration_sec": block["duration_sec"],
            "text": block["text"],
            "confidence": block.get("confidence", 0),
        }
        if "text_translated" in block:
            entry["text_translated"] = block["text_translated"]
        data["subtitles"].append(entry)

    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def write_ass(blocks: list[dict], output_path: str) -> str:
    """
    Genera archivo Advanced SubStation Alpha (.ass).

    Formato estándar para fansub con soporte de estilos.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    def _secs_to_ass(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    header = (
        "[Script Info]\n"
        "Title: SubtitleForge Export\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
        "0,0,0,0,100,100,0,0,1,2,1,2,10,10,30,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for block in blocks:
        start = _secs_to_ass(block["start_sec"])
        end = _secs_to_ass(block["end_sec"])
        text = block.get("text_translated", block["text"]).replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def write_all_formats(
    blocks: list[dict],
    output_dir: str,
    base_name: str = "subtitles",
    formats: list[str] = None,
    video_info: dict = None,
    language_info: dict = None,
    zone_info: dict = None,
) -> dict:
    """
    Genera archivos en todos los formatos solicitados.

    Returns:
        dict mapping format -> filepath
    """
    if formats is None:
        formats = ["srt", "vtt", "json"]

    os.makedirs(output_dir, exist_ok=True)
    generated = {}

    writers = {
        "srt": lambda: write_srt(blocks, os.path.join(output_dir, f"{base_name}.srt")),
        "vtt": lambda: write_vtt(blocks, os.path.join(output_dir, f"{base_name}.vtt")),
        "sbv": lambda: write_sbv(blocks, os.path.join(output_dir, f"{base_name}.sbv")),
        "json": lambda: write_json(blocks, os.path.join(output_dir, f"{base_name}.json"),
                                   video_info, language_info, zone_info),
        "ass": lambda: write_ass(blocks, os.path.join(output_dir, f"{base_name}.ass")),
    }

    for fmt in formats:
        if fmt in writers:
            writers[fmt]()
            generated[fmt] = os.path.join(output_dir, f"{base_name}.{fmt}")

    return generated
