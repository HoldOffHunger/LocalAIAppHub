# Reading what a model file says about itself: the GGUF header (Ollama and LM Studio models) and the safetensors
# header (ComfyUI models). Only the header is read, never the weights, so even a 24 GB file takes a moment.
# Standard library only.

import json
import struct

# general.file_type in a GGUF header, as llama.cpp numbers it
GGUF_FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S",
                   12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
                   19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL",
                   26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16"}
_FIXED = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
# The keys worth showing; tokenizer.* holds the vocabulary (hundreds of thousands of strings) and is never read
_KEEP = ("general.", ".context_length", ".block_count", ".embedding_length", ".expert_count")


def _read(handle, fmt):
    size = struct.calcsize(fmt)
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("the header ends early")
    return struct.unpack(fmt, data)[0]


def _string(handle):
    length = _read(handle, "<Q")
    if length > 1 << 24:
        raise ValueError("a header string is impossibly long")
    return handle.read(length).decode("utf-8", "replace")


def _value(handle, kind, keep):
    if kind in _FIXED:
        return _read(handle, _FIXED[kind])
    if kind == 8:
        return _string(handle)
    if kind == 9:
        inner, count = _read(handle, "<I"), _read(handle, "<Q")
        if not keep:
            if inner in _FIXED:
                handle.seek(count * struct.calcsize(_FIXED[inner]), 1)
            else:
                for _ in range(count):
                    _value(handle, inner, False)
            return None
        return [_value(handle, inner, True) for _ in range(min(count, 64))] if count <= 64 else "(%d items)" % count
    raise ValueError("unknown GGUF value type %d" % kind)


def gguf(path):
    # {"general.name": ..., "llama.context_length": ..., ...}, or {} if it isn't a GGUF file
    try:
        with open(path, "rb") as handle:
            if handle.read(4) != b"GGUF":
                return {}
            version = _read(handle, "<I")
            count_format = "<I" if version == 1 else "<Q"
            _read(handle, count_format)  # tensors
            pairs = _read(handle, count_format)
            found = {}
            for _ in range(pairs):
                key = _string(handle)
                if key.startswith("tokenizer."):
                    break  # general.* and the architecture's numbers come first; the vocabulary is all that's left
                kind = _read(handle, "<I")
                keep = key.startswith(_KEEP[0]) or key.endswith(_KEEP[1:])
                value = _value(handle, kind, keep)
                if keep:
                    found[key] = value
            if isinstance(found.get("general.file_type"), int):
                found["general.file_type"] = GGUF_FILE_TYPES.get(found["general.file_type"], str(found["general.file_type"]))
            return found
    except (OSError, ValueError, struct.error):
        return {}


def safetensors(path):
    # The __metadata__ block (modelspec.title, modelspec.author, ...), without the thumbnails and embedded workflows,
    # plus how many tensors there are and the main number type
    try:
        with open(path, "rb") as handle:
            length = _read(handle, "<Q")
            if length > 200 * 1024 * 1024:
                return {}
            header = json.loads(handle.read(length))
    except (OSError, ValueError, struct.error):
        return {}
    meta = header.pop("__metadata__", {}) or {}
    kept = {key: value for key, value in meta.items()
            if isinstance(value, str) and len(value) < 400 and key not in ("workflow", "prompt") and "thumbnail" not in key}
    dtypes = {}
    for tensor in header.values():
        if isinstance(tensor, dict) and "dtype" in tensor:  # weighed by bytes, so a few big fp8 tensors beat many small f32 ones
            start, end = (tensor.get("data_offsets") or [0, 1])[:2]
            dtypes[tensor["dtype"]] = dtypes.get(tensor["dtype"], 0) + (end - start)
    kept["_tensors"] = len(header)
    if dtypes:
        kept["_dtype"] = max(dtypes, key=dtypes.get)
    return kept
