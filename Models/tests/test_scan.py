import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import file_meta  # noqa: E402
import known  # noqa: E402
import scan  # noqa: E402


def gguf_string(text):
    data = text.encode("utf-8")
    return struct.pack("<Q", len(data)) + data


def test_gguf_header_is_read_up_to_the_vocabulary(tmp_path):
    path = tmp_path / "tiny.gguf"
    pairs = [gguf_string("general.name") + struct.pack("<I", 8) + gguf_string("Tiny Model"),
             gguf_string("general.file_type") + struct.pack("<I", 4) + struct.pack("<I", 15),
             gguf_string("llama.context_length") + struct.pack("<I", 4) + struct.pack("<I", 8192),
             gguf_string("tokenizer.ggml.tokens") + b"never read"]
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, len(pairs)) + b"".join(pairs))
    meta = file_meta.gguf(path)
    assert meta == {"general.name": "Tiny Model", "general.file_type": "Q4_K_M", "llama.context_length": 8192}


def test_ollama_in_a_path_is_not_llama():
    assert known.lookup("granite3.3:8b", "8b")["creator"] == "IBM"
    assert known.lookup("full_encoder_small_decoder", "full_encoder_small_decoder.safetensors") == {}


def test_size_classes_sort_in_billions():
    assert scan.params_value("137M") < scan.params_value("3.8B") < scan.params_value("30B-A3B") == 30
