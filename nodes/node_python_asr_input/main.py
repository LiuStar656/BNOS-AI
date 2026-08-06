"""ASR 语音识别节点（Phase 2+）"""
import sys
import json
import os
import time

def process(data):
    data_type = data.get("data_type", "")
    
    if data_type == "audio_path":
        audio_path = data.get("content", "")
        # TODO: Phase 2 集成 Whisper
        # from whisper import load_model
        # model = load_model("small")
        # result = model.transcribe(audio_path)
        # text = result["text"]
        return {
            "data_type": "text",
            "content": "",  # 占位: 真实转写结果
            "source": "asr",
            "audio_path": audio_path
        }
    
    elif data.get("cmd") == "init_check":
        return {
            "node_name": "asr_input",
            "init_status": "ok",
            "components": {"whisper": {"status": "placeholder", "detail": "Phase 2 集成"}}
        }
    
    return data

if __name__ == "__main__":
    if getattr(sys, 'frozen', False) or sys.argv[0].lower().endswith('.exe'):
        NODE_DIR = os.getcwd()
    else:
        NODE_DIR = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(NODE_DIR, "node_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if len(sys.argv) < 2:
        print(json.dumps({"code": -1, "error": "no input"}))
        sys.exit(1)
    input_data = json.loads(sys.argv[1])
    result = process(input_data)
    print(json.dumps({"code": 0, "type": cfg["output_type"], "data": result}, ensure_ascii=False))
