"""Renderizado final del proyecto con un único comando FFmpeg (rápido y sin archivos intermedios)."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from .ffmpeg_utils import CancelCb, MediaInfo, ProgressCb, probe, run_ffmpeg
from .project import Clip, Project, Subtitle, subtitles_to_srt

PRESETS = {
    "YouTube 1080p (16:9)": (1920, 1080),
    "HD 720p (16:9)": (1280, 720),
    "4K (16:9)": (3840, 2160),
    "TikTok / Reels / Shorts (9:16)": (1080, 1920),
    "Instagram cuadrado (1:1)": (1080, 1080),
    "Instagram vertical (4:5)": (1080, 1350),
}

QUALITY = {  # nombre -> CRF de x264
    "Alta": 18,
    "Normal": 21,
    "Ligera (archivo pequeño)": 26,
}

SPEED = {  # nombre -> preset de x264
    "Rápida": "veryfast",
    "Equilibrada": "medium",
    "Máxima compresión": "slow",
}


@dataclass
class ExportSettings:
    output: str
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    fit: str = "fit"            # "fit" (barras negras), "fill" (recorta), "blur" (fondo desenfocado)
    crf: int = 21
    preset: str = "veryfast"
    burn_subtitles: bool = False
    subtitle_size: int = 0      # 0 = automático
    audio_bitrate: str = "192k"
    write_srt: bool = False


def _atempo_chain(speed: float) -> list[str]:
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-3:
        parts.append(f"atempo={s:.5f}")
    return parts


def _video_chain(clip: Clip, s: ExportSettings, idx: int) -> str:
    W, H, F = s.width, s.height, s.fps
    pre = f"setpts=(PTS-STARTPTS)/{clip.speed:.5f}"
    post = f"fps={F:g},setsar=1,format=yuv420p"
    if s.fit == "fill" or clip.crop_x is not None:
        cx = 0.5 if clip.crop_x is None else max(0.0, min(1.0, clip.crop_x))
        return (f"[{idx}:v]{pre},scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H}:(iw-ow)*{cx:.4f}:(ih-oh)/2,{post}[v{idx}]")
    if s.fit == "blur":
        return (f"[{idx}:v]{pre},split=2[bg{idx}][fg{idx}];"
                f"[bg{idx}]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,"
                f"crop={W // 4}:{H // 4},boxblur=10:2,scale={W}:{H}[bgs{idx}];"
                f"[fg{idx}]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs{idx}];"
                f"[bgs{idx}][fgs{idx}]overlay=(W-w)/2:(H-h)/2,{post}[v{idx}]")
    return (f"[{idx}:v]{pre},scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,{post}[v{idx}]")


def build_command(project: Project, s: ExportSettings, infos: dict[str, MediaInfo],
                  workdir: str) -> tuple[list[str], float]:
    """Construye los argumentos de FFmpeg. Devuelve (args, duración total)."""
    if not project.clips:
        raise ValueError("La línea de tiempo está vacía.")
    args: list[str] = []
    graph: list[str] = []
    concat_in = []
    n = len(project.clips)
    for i, c in enumerate(project.clips):
        info = infos[c.source]
        args += ["-ss", f"{c.start:.3f}", "-t", f"{c.src_length:.3f}", "-i", c.source]
        dur = c.duration
        if info.has_video:
            graph.append(_video_chain(c, s, i))
        else:
            graph.append(f"color=c=black:s={s.width}x{s.height}:r={s.fps:g}:d={dur:.3f},format=yuv420p[v{i}]")
        if info.has_audio:
            chain = ["asetpts=PTS-STARTPTS", *_atempo_chain(c.speed)]
            if abs(c.volume - 1.0) > 1e-3:
                chain.append(f"volume={c.volume:.3f}")
            chain += ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo",
                      "apad", f"atrim=0:{dur:.3f}"]
            graph.append(f"[{i}:a]{','.join(chain)}[a{i}]")
        else:
            graph.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{dur:.3f}[a{i}]")
        concat_in.append(f"[v{i}][a{i}]")

    graph.append(f"{''.join(concat_in)}concat=n={n}:v=1:a=1[vc][ac]")
    vout = "[vc]"
    if s.burn_subtitles and project.subtitles:
        srt = os.path.join(workdir, "subs.srt")
        with open(srt, "w", encoding="utf-8") as fh:
            fh.write(subtitles_to_srt(project.subtitles))
        # libass escala según PlayResY=288 por defecto: calculamos un tamaño legible.
        vertical = s.height > s.width
        size = s.subtitle_size or (11 if vertical else 16)
        margin = 60 if vertical else 20
        style = (f"FontName=Arial,FontSize={size},Bold=1,PrimaryColour=&H00FFFFFF,"
                 f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
                 f"Alignment=2,MarginV={margin}")
        graph.append(f"[vc]subtitles=subs.srt:force_style='{style}'[vs]")
        vout = "[vs]"

    script = os.path.join(workdir, "graph.txt")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(";\n".join(graph))
    args += [
        "-filter_complex_script", script,
        "-map", vout, "-map", "[ac]",
        "-c:v", "libx264", "-preset", s.preset, "-crf", str(s.crf),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", s.audio_bitrate,
        "-movflags", "+faststart", os.path.abspath(s.output),
    ]
    return args, project.duration


def export_project(project: Project, s: ExportSettings, progress: ProgressCb = None,
                   cancel: CancelCb = None, infos: Optional[dict[str, MediaInfo]] = None) -> str:
    infos = dict(infos or {})
    for c in project.clips:
        if c.source not in infos:
            infos[c.source] = probe(c.source)
    # Rutas absolutas porque FFmpeg se ejecuta en una carpeta temporal.
    with tempfile.TemporaryDirectory(prefix="rmstudio_") as tmp:
        abs_proj = Project(
            clips=[Clip(**{**c.__dict__, "source": os.path.abspath(c.source)}) for c in project.clips],
            subtitles=list(project.subtitles), width=s.width, height=s.height, fps=s.fps,
        )
        abs_infos = {os.path.abspath(k): v for k, v in infos.items()}
        args, dur = build_command(abs_proj, s, abs_infos, tmp)
        run_ffmpeg(args, duration=dur, progress=progress, cancel=cancel, cwd=tmp)
    if s.write_srt and project.subtitles:
        with open(os.path.splitext(s.output)[0] + ".srt", "w", encoding="utf-8") as fh:
            fh.write(subtitles_to_srt(project.subtitles))
    return s.output


def export_segment(source: str, start: float, end: float, s: ExportSettings,
                   crop_x: Optional[float] = None, subtitles: Optional[list[Subtitle]] = None,
                   progress: ProgressCb = None, cancel: CancelCb = None) -> str:
    """Exporta un único fragmento (útil para clips cortos / highlights)."""
    p = Project(width=s.width, height=s.height, fps=s.fps)
    clip = p.add_clip(source, start, end)
    clip.crop_x = crop_x
    if subtitles:
        p.subtitles = [Subtitle(x.start - start, x.end - start, x.text)
                       for x in subtitles if x.end > start and x.start < end]
    return export_project(p, s, progress=progress, cancel=cancel)
