import os
import subprocess

import pytest

from rmstudio.ai.highlights import find_highlights
from rmstudio.ai.scenes import detect_scenes, ranges_from_cuts
from rmstudio.ai.silence import detect_silences, keep_ranges
from rmstudio.core.exporter import ExportSettings, export_project
from rmstudio.core.ffmpeg_utils import probe
from rmstudio.core.project import Project, Subtitle, subtitles_to_srt


@pytest.fixture(scope="session")
def sample(tmp_path_factory):
    """6 s de video: 0-2 s tono, 2-4 s silencio, 4-6 s tono; cambio de color a los 3 s."""
    d = tmp_path_factory.mktemp("media")
    out = str(d / "sample.mp4")
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:r=25:d=3",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=25:d=3",
        "-f", "lavfi", "-i", "sine=f=440:d=6:sample_rate=48000",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a]volume='if(between(t,2,4),0,1)':eval=frame[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out,
    ], check=True)
    return out


def test_probe(sample):
    info = probe(sample)
    assert info.has_video and info.has_audio
    assert info.width == 320 and abs(info.duration - 6) < 0.2


def test_project_split_undo_and_save(tmp_path, sample):
    p = Project()
    p.snapshot()
    p.add_clip(sample, 0, 6)
    p.snapshot()
    assert p.split_at(2.5)
    assert len(p.clips) == 2 and abs(p.clips[0].end - 2.5) < 1e-6
    p.clips[1].speed = 2.0
    assert abs(p.duration - (2.5 + 3.5 / 2)) < 1e-6
    assert p.source_time(3.0) == (1, pytest.approx(3.5))
    p.undo()
    assert len(p.clips) == 1
    p.redo()
    assert len(p.clips) == 2
    f = tmp_path / "p.rmproj"
    p.save(str(f))
    q = Project.load(str(f))
    assert [c.start for c in q.clips] == [c.start for c in p.clips]


def test_remove_clip_shifts_subtitles(sample):
    p = Project()
    p.add_clip(sample, 0, 2)
    p.add_clip(sample, 2, 4)
    p.add_clip(sample, 4, 6)
    p.subtitles = [Subtitle(0.5, 1.5, "a"), Subtitle(4.5, 5.5, "c")]
    p.remove_clip(1)
    assert [(s.start, s.end) for s in p.subtitles] == [(0.5, 1.5), (2.5, 3.5)]
    assert "00:00:02,500 --> 00:00:03,500" in subtitles_to_srt(p.subtitles)


def test_silence_detection(sample):
    sil = detect_silences(sample, 0, 6, noise_db=-40, min_silence=0.5)
    assert len(sil) == 1
    s, e = sil[0]
    assert 1.8 < s < 2.3 and 3.7 < e < 4.2
    keep = keep_ranges(0, 6, sil, padding=0.1)
    assert len(keep) == 2


def test_scene_detection(sample):
    cuts = detect_scenes(sample, 0, 6, threshold=0.3)
    assert any(2.8 < c < 3.2 for c in cuts)
    assert len(ranges_from_cuts(0, 6, cuts)) == 2


def test_highlights(sample):
    hs = find_highlights(sample, 6.0, clip_len=1.5, count=2)
    assert len(hs) == 2
    for h in hs:  # nunca dentro del silencio
        assert not (2.2 < h.start < 3.8 and 2.2 < h.end < 3.8)


@pytest.mark.parametrize("fit,size", [("fit", (640, 360)), ("blur", (360, 640)), ("fill", (240, 240))])
def test_export(tmp_path, sample, fit, size):
    p = Project()
    p.add_clip(sample, 0, 2)
    c = p.add_clip(sample, 4, 6)
    c.speed = 2.0
    c.volume = 0.5
    p.subtitles = [Subtitle(0.2, 1.8, "Hola mundo")]
    out = str(tmp_path / f"out_{fit}.mp4")
    prog = []
    export_project(p, ExportSettings(output=out, width=size[0], height=size[1], fps=25, fit=fit,
                                     burn_subtitles=True, write_srt=True), progress=prog.append)
    info = probe(out)
    assert (info.width, info.height) == size
    assert abs(info.duration - 3.0) < 0.25
    assert prog and prog[-1] == 1.0
    assert os.path.exists(out[:-4] + ".srt")
