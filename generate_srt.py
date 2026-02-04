#pip install faster-whisper torch -i https://pypi.tuna.tsinghua.edu.cn/simple
#py -3.11 e:\work\project\generate_srt.py "e:\work\project\vedio\Linkedin.Learning.SQL.For.AI.Projects-From.Data.Exploration.To.Impact.BOOKWARE-SCHOLASTiC"
#py -3.11 -m pip install static-ffmpeg -i https://pypi.tuna.tsinghua.edu.cn/simple
import os
import sys
import time
from datetime import timedelta
try:
    from faster_whisper import WhisperModel
except ImportError:
    print("Error: faster-whisper not installed.")
    print("Please run: pip install faster-whisper torch")
    sys.exit(1)

import subprocess

def check_ffmpeg():
    # First try system ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        # Try static_ffmpeg if available
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths()
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (ImportError, FileNotFoundError):
            return False

def format_timestamp(seconds: float):
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int(td.microseconds / 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def generate_srt(video_path, model, output_path):
    print(f"  Transcribing: {os.path.basename(video_path)} ...")
    start_time = time.time()
    
    # beam_size=5 is default for better quality, but we can reduce for speed
    segments, info = model.transcribe(video_path, beam_size=5, language="en")
    
    print(f"  Detected language '{info.language}' with probability {info.language_probability:.2f}")
    
    with open(output_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            start = format_timestamp(segment.start)
            end = format_timestamp(segment.end)
            text = segment.text.strip()
            
            f.write(f"{i}\n")
            f.write(f"{start} --> {end}\n")
            f.write(f"{text}\n\n")
            
    end_time = time.time()
    print(f"  Saved to: {output_path} (Took {end_time - start_time:.1f}s)")

def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {os.path.basename(sys.argv[0])} <directory_path> [model_size]")
        print("Model sizes: tiny, base, small, medium, large-v3")
        return

    root_dir = sys.argv[1]
    model_size = sys.argv[2] if len(sys.argv) > 2 else "small"
    
    if not os.path.exists(root_dir):
        print(f"Directory not found: {root_dir}")
        return

    if not check_ffmpeg():
        print("Error: ffmpeg not found in PATH.")
        print("Please install ffmpeg (e.g., via 'choco install ffmpeg' or download from gyan.dev)")
        return

    print(f"Loading Whisper model '{model_size}'...")
    
    # Check for GPU availability
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"
    
    compute_type = "float16" if device == "cuda" else "int8"
    
    print(f"Using device: {device} ({compute_type})")
    
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        print(f"Model loading failed: {e}. Falling back to CPU/int8.")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")

    extensions = ('.mp4', '.mkv', '.avi', '.mov', '.ts', '.flv', '.webm')
    
    print(f"Scanning: {root_dir}")
    video_files = []
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith(extensions):
                video_files.append(os.path.join(root, file))
    
    print(f"Found {len(video_files)} videos.")
    
    for i, video_path in enumerate(video_files, 1):
        srt_path = os.path.splitext(video_path)[0] + ".srt"
        
        if os.path.exists(srt_path):
            print(f"[{i}/{len(video_files)}] Skipping (SRT exists): {os.path.basename(video_path)}")
            continue
            
        print(f"[{i}/{len(video_files)}] Processing: {os.path.basename(video_path)}")
        try:
            generate_srt(video_path, model, srt_path)
        except Exception as e:
            print(f"  Error processing {video_path}: {e}")

if __name__ == "__main__":
    main()
