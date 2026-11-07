# The ComfyUI graphs ImageGen sends, in Comfy's API format, built from the official FLUX.2 [klein] distilled templates.
# One graph covers every mode: no reference images is text-to-image, one or more is "take this and do X".

# The page's model menu, in order; the first is the default. Add one here and it appears there, greyed out until its files exist.
# kv_cache: the model reads reference pictures once instead of on every step (the "KV" klein models only).
MODELS = {
    "klein-4b": {"label": "Klein 4B", "note": "quick", "kv_cache": False,
                 "files": {"diffusion_models": "flux-2-klein-4b-fp8.safetensors",
                           "text_encoders": "qwen_3_4b.safetensors",
                           "vae": "flux2-vae.safetensors"}},
    "klein-9b-kv": {"label": "Klein 9B KV", "note": "better edits, slower", "kv_cache": True,
                    "files": {"diffusion_models": "flux-2-klein-9b-kv-fp8.safetensors",
                              "text_encoders": "qwen_3_8b_fp8mixed.safetensors",
                              "vae": "full_encoder_small_decoder.safetensors"}},  # same encoder, a lighter decoder
    # SDXL checkpoints: one file with the drawing model, its text readers and its decoder. Words, or one picture to
    # work from. "uncensored" puts a red dot by them in the menu: trained on adult material, they draw what's asked.
    # Both were checked against the sha256 Civitai publishes for them (1 Nov 2026); the Hugging Face copies are re-uploads
    "lustify": {"label": "Lustify APEX", "note": "photoreal, uncensored", "kv_cache": False, "uncensored": True,
                "sdxl": {"steps": 30, "cfg": 4.0, "sampler": "dpmpp_2m_sde", "scheduler": "karras", "prefix": "",
                         "negative": "cartoon, anime, drawing, illustration, lowres, blurry, bad anatomy, bad hands, "
                                     "extra fingers, deformed, watermark, text, signature"},
                "files": {"checkpoints": "lustifySDXLNSFW_apexV8.safetensors"}},
    "wai-illustrious": {"label": "WAI Illustrious v17", "note": "illustration and anime, uncensored", "kv_cache": False,
                        "uncensored": True,
                        "sdxl": {"steps": 28, "cfg": 6.0, "sampler": "euler_ancestral", "scheduler": "normal",
                                 "prefix": "masterpiece, best quality, amazing quality, ",
                                 "negative": "bad quality, worst quality, worst detail, sketch, censor, lowres, "
                                             "bad anatomy, bad hands, extra fingers, watermark, text, signature"},
                        "files": {"checkpoints": "waiIllustriousSDXL_v170.safetensors"}},
}
DEFAULT_MODEL = "klein-4b"
STEPS = 4  # the distilled models are trained for four steps at cfg 1
SDXL_EDIT_STRENGTH = 0.65  # how far a picture-to-work-from may change: lower keeps more of it

# Video, from the official Wan 2.2 5B text-and-image-to-video template. Same menu rules as above.
VIDEO_MODELS = {
    "wan-2.2-5b": {"label": "Wan 2.2 5B", "note": "words or a starting picture", "kv_cache": False,
                   "files": {"diffusion_models": "wan2.2_ti2v_5B_fp16.safetensors",
                             "text_encoders": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                             "vae": "wan2.2_vae.safetensors"}},
}
DEFAULT_VIDEO_MODEL = "wan-2.2-5b"
VIDEO_FPS = 24
VIDEO_STEPS = 20
VIDEO_SIZES = {"small": (832, 480), "full": (1280, 704)}  # full is what Wan 5B was trained at
# Wan's standard negative prompt, kept in Chinese as trained: garish colours, overexposed, static, blurry detail,
# subtitles, worst quality, JPEG artefacts, ugly, extra or fused fingers, bad hands and faces, deformed limbs,
# a frozen frame, cluttered background, three legs, crowds behind, walking backwards.
WAN_NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清"
                "，字幕，风格，作品，画作，画面，静"
                "止，整体发灰，最差质量，低质量，JPEG"
                "压缩残留，丑陋的，残缺的，多余的手"
                "指，画得不好的手部，画得不好的脸部"
                "，畸形的，毁容的，形态畸形的肢体，"
                "手指融合，静止不动的画面，杂乱的背"
                "景，三条腿，背景人很多，倒着走")


def video_frames(seconds):
    # Wan wants 4n+1 frames
    return int(round(seconds * VIDEO_FPS / 4)) * 4 + 1


def wan_video(model_id, prompt, seed, size, seconds, start_image_name):
    files = VIDEO_MODELS[model_id]["files"]
    width, height = VIDEO_SIZES[size]
    graph = {
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": files["diffusion_models"], "weight_dtype": "default"}},
        "shift": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["model", 0], "shift": 8.0}},
        "clip": {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": files["text_encoders"], "type": "wan", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": files["vae"]}},
        "prompt": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["clip", 0]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": WAN_NEGATIVE, "clip": ["clip", 0]}},
    }
    latent_inputs = {"vae": ["vae", 0], "width": width, "height": height, "length": video_frames(seconds), "batch_size": 1}
    if start_image_name:
        # The clip opens on the picture and keeps its shape, at about the chosen size's pixel count, in 32-pixel steps
        graph["start_load"] = {"class_type": "LoadImage", "inputs": {"image": start_image_name}}
        graph["start_scale"] = {"class_type": "ImageScaleToTotalPixels",
                                "inputs": {"image": ["start_load", 0], "upscale_method": "lanczos",
                                           "megapixels": width * height / 1e6, "resolution_steps": 32}}
        graph["start_size"] = {"class_type": "GetImageSize", "inputs": {"image": ["start_scale", 0]}}
        latent_inputs.update(width=["start_size", 0], height=["start_size", 1], start_image=["start_scale", 0])
    graph.update({
        "latent": {"class_type": "Wan22ImageToVideoLatent", "inputs": latent_inputs},
        "sample": {"class_type": "KSampler",
                   "inputs": {"model": ["shift", 0], "seed": seed, "steps": VIDEO_STEPS, "cfg": 5.0,
                              "sampler_name": "uni_pc", "scheduler": "simple", "positive": ["prompt", 0],
                              "negative": ["negative", 0], "latent_image": ["latent", 0], "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "video": {"class_type": "CreateVideo", "inputs": {"images": ["decode", 0], "fps": float(VIDEO_FPS)}},
        "save": {"class_type": "SaveVideo",
                 "inputs": {"video": ["video", 0], "filename_prefix": "ImageGen", "format": "mp4", "format.codec": "h264"}},
    })
    return graph


def image(model_id, prompt, seed, width, height, reference_names):
    builder = sdxl_image if "sdxl" in MODELS[model_id] else klein_image
    return builder(model_id, prompt, seed, width, height, reference_names)


def sdxl_image(model_id, prompt, seed, width, height, reference_names):
    # The standard SDXL graph. With a picture, it starts from that picture instead of noise (and keeps its shape)
    model = MODELS[model_id]
    tune = model["sdxl"]
    graph = {
        "checkpoint": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model["files"]["checkpoints"]}},
        "prompt": {"class_type": "CLIPTextEncode", "inputs": {"text": tune["prefix"] + prompt, "clip": ["checkpoint", 1]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": tune["negative"], "clip": ["checkpoint", 1]}},
    }
    if reference_names:
        graph["ref_load"] = {"class_type": "LoadImage", "inputs": {"image": reference_names[0]}}
        graph["ref_scale"] = {"class_type": "ImageScaleToTotalPixels",
                              "inputs": {"image": ["ref_load", 0], "upscale_method": "lanczos", "megapixels": 1.0,
                                         "resolution_steps": 8}}
        graph["latent"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["ref_scale", 0], "vae": ["checkpoint", 2]}}
        denoise = SDXL_EDIT_STRENGTH
    else:
        graph["latent"] = {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
        denoise = 1.0
    graph.update({
        "sample": {"class_type": "KSampler",
                   "inputs": {"model": ["checkpoint", 0], "seed": seed, "steps": tune["steps"], "cfg": tune["cfg"],
                              "sampler_name": tune["sampler"], "scheduler": tune["scheduler"], "positive": ["prompt", 0],
                              "negative": ["negative", 0], "latent_image": ["latent", 0], "denoise": denoise}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["checkpoint", 2]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "ImageGen"}},
    })
    return graph


def klein_image(model_id, prompt, seed, width, height, reference_names):
    files = MODELS[model_id]["files"]
    graph = {
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": files["diffusion_models"], "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": files["text_encoders"], "type": "flux2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": files["vae"]}},
        "prompt": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["clip", 0]}},
        "empty_prompt": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["prompt", 0]}},
    }
    model = ["model", 0]
    if MODELS[model_id]["kv_cache"]:
        graph["kv_cache"] = {"class_type": "FluxKVCache", "inputs": {"model": model}}
        model = ["kv_cache", 0]
    positive, negative = ["prompt", 0], ["empty_prompt", 0]
    for index, name in enumerate(reference_names):
        # Each reference is scaled to about a megapixel, encoded, and attached to both sides of the guidance
        tag = "ref%d" % index
        graph[tag + "_load"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        graph[tag + "_scale"] = {"class_type": "ImageScaleToTotalPixels",
                                 "inputs": {"image": [tag + "_load", 0], "upscale_method": "lanczos",
                                            "megapixels": 1.0, "resolution_steps": 1}}
        graph[tag + "_latent"] = {"class_type": "VAEEncode", "inputs": {"pixels": [tag + "_scale", 0], "vae": ["vae", 0]}}
        graph[tag + "_pos"] = {"class_type": "ReferenceLatent",
                               "inputs": {"conditioning": positive, "latent": [tag + "_latent", 0]}}
        graph[tag + "_neg"] = {"class_type": "ReferenceLatent",
                               "inputs": {"conditioning": negative, "latent": [tag + "_latent", 0]}}
        positive, negative = [tag + "_pos", 0], [tag + "_neg", 0]
    if reference_names:
        # An edit comes out the shape of the first image
        graph["size"] = {"class_type": "GetImageSize", "inputs": {"image": ["ref0_scale", 0]}}
        width, height = ["size", 0], ["size", 1]
    graph.update({
        "latent": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "sigmas": {"class_type": "Flux2Scheduler", "inputs": {"steps": STEPS, "width": width, "height": height}},
        "guider": {"class_type": "CFGGuider",
                   "inputs": {"model": model, "positive": positive, "negative": negative, "cfg": 1.0}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "sample": {"class_type": "SamplerCustomAdvanced",
                   "inputs": {"noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0],
                              "sigmas": ["sigmas", 0], "latent_image": ["latent", 0]}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "ImageGen"}},
    })
    return graph
