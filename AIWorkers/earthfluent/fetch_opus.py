import sys
from pathlib import Path

from huggingface_hub import snapshot_download

# Downloads OPUS-MT models (Helsinki-NLP, CC-BY 4.0) into E:\AIModels\opus-mt: python fetch_opus.py it-en en-it
MODELS = Path(r"E:\AIModels\opus-mt")
for pair in sys.argv[1:]:
    name = f"opus-mt-{pair}"
    print(snapshot_download(f"Helsinki-NLP/{name}", local_dir=MODELS / name,
                            allow_patterns=["*.json", "*.bin", "*.safetensors", "*.spm", "*.txt", "vocab*"]), flush=True)
