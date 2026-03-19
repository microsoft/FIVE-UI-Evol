import base64
import argparse
import json
import os
import re
from PIL import Image
from tqdm import tqdm
from openai import OpenAI

def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def load_jsonl(path):
    with open(path, "r") as f:
        return [json.loads(line) for line in f]

def normalize_instr_type(x):
    if isinstance(x, int):
        return "implicit" if x == 2 else "explicit"
    return str(x).lower()

def build_sample(item, args):
    image_path = os.path.join(args.dataset, item["image"])

    return {
        "image_path": image_path,
        "instruction": item["instruction"],
        "gt_box": item["bounding_box"],
        "source": item.get("source", "unknown"),
        "el_type": item.get("el_type", "unknown").lower(),
        "instr_type": normalize_instr_type(item.get("annotations", {}).get("instr_type", "unknown"))
    }

def build_messages(sample, args):
    encoded = encode_image(sample["image_path"])

    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encoded}"
                    }
                },
                {
                    "type": "text",
                    "text": args.prompt + sample["instruction"]
                }
            ]
        }
    ]

def parse_prediction(text, mode):
    try:
        # (x, y)
        if mode == "point":
            match = re.search(r"(\d+)[,\s]+(\d+)", text)
            if match:
                return float(match.group(1)), float(match.group(2))

        # [x1,y1,x2,y2]
        elif mode == "bbox":
            nums = list(map(float, re.findall(r"\d+", text)))
            if len(nums) >= 4:
                x = (nums[0] + nums[2]) / 2
                y = (nums[1] + nums[3]) / 2
                return x, y

        # auto
        elif mode == "auto":
            nums = list(map(float, re.findall(r"\d+", text)))
            if len(nums) >= 4:
                return (nums[0] + nums[2]) / 2, (nums[1] + nums[3]) / 2
            elif len(nums) >= 2:
                return nums[0], nums[1]

    except:
        return None

    return None

def is_correct(pred, gt_box):
    if pred is None:
        return False

    x, y = pred
    x1, y1, x2, y2 = gt_box

    return x1 <= x <= x2 and y1 <= y <= y2


def evaluate(samples, predictions, args):
    total = len(samples)
    correct = 0

    # 三类统计
    source_stats = {}
    el_stats = {}
    instr_stats = {}

    def update(stats, key, hit):
        if key not in stats:
            stats[key] = {"correct": 0, "total": 0}
        stats[key]["total"] += 1
        if hit:
            stats[key]["correct"] += 1

    for sample, pred_text in zip(samples, predictions):
        pred = parse_prediction(pred_text, args.parse_mode)
        hit = is_correct(pred, sample["gt_box"])

        if hit:
            correct += 1

        update(source_stats, sample["source"], hit)
        update(el_stats, sample["el_type"], hit)
        update(instr_stats, sample["instr_type"], hit)


    print(f"\nOverall Accuracy: {correct/total:.4f}")

    def print_stats(name, stats):
        print(f"\n=== {name} ===")
        for k, v in stats.items():
            acc = v["correct"] / v["total"] if v["total"] > 0 else 0
            print(f"{k:15s} | acc: {acc:.4f}")

    print_stats("Source", source_stats)
    print_stats("Element Type", el_stats)
    print_stats("Instruction Type", instr_stats)
def run_inference(samples, args):
    client = OpenAI(
        base_url=args.base_url,
        api_key="empty"
    )

    outputs = []

    for sample in tqdm(samples):
        messages = build_messages(sample, args)

        try:
            resp = client.chat.completions.create(
                model=args.model,
                messages=messages,
                temperature=0,
                timeout=15
            )
            text = resp.choices[0].message.content
        except Exception as e:
            print("Error:", e)
            text = ""

        outputs.append(text)

    return outputs

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--datapath", type=str, required=True)
    parser.add_argument("--dataset", type=str, required=True)

    parser.add_argument("--prompt", type=str,
                        default="Please provide the bounding box coordinate of the sentence describes: ")

    parser.add_argument("--parse_mode", type=str,
                        default="auto",
                        choices=["auto", "point", "bbox"])

    parser.add_argument("--base_url", type=str,
                        default="http://127.0.0.1:8001/v1")

    args = parser.parse_args()

    raw_data = load_jsonl(args.datapath)
    samples = [build_sample(x, args) for x in raw_data]

    preds = run_inference(samples, args)

    evaluate(samples, preds, args)


if __name__ == "__main__":
    main()