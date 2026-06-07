#!/usr/bin/env python3
import os
import sys
import hashlib
import vt

API_KEY = os.environ.get("VT_API_KEY", "")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def scan_file(client, path):
    file_hash = sha256(path)
    try:
        analysis = client.get_object(f"/files/{file_hash}")
        stats = analysis.last_analysis_stats
        detected = stats.get("malicious", 0) + stats.get("suspicious", 0)
        total = sum(stats.values())
        status = "CLEAN" if detected == 0 else "THREAT"
        print(f"[{status}] {path}")
        print(f"         {detected}/{total} engines flagged | hash: {file_hash[:16]}...")
        if detected > 0:
            results = analysis.last_analysis_results
            flagged = {k: v["result"] for k, v in results.items() if v["category"] in ("malicious", "suspicious")}
            for engine, result in list(flagged.items())[:5]:
                print(f"         ! {engine}: {result}")
    except vt.error.APIError as e:
        if e.code == "NotFoundError":
            print(f"[UPLOAD] {path} (not in VT, uploading...)")
            with open(path, "rb") as f:
                analysis = client.scan_file(f)
            print(f"         Submitted. Check https://www.virustotal.com/gui/file/{file_hash}")
        else:
            print(f"[ERROR]  {path}: {e}")

def scan_path(client, path):
    if os.path.isfile(path):
        scan_file(client, path)
    elif os.path.isdir(path):
        for root, _, files in os.walk(path):
            for name in files:
                scan_file(client, os.path.join(root, name))
    else:
        print(f"[ERROR] Path not found: {path}")

if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: VT_API_KEY environment variable not set.")
        sys.exit(1)
    if len(sys.argv) < 2:
        print("Usage: scan.py <file_or_directory>")
        print("  e.g. scan.py /scan/sabnzbd")
        sys.exit(1)

    with vt.Client(API_KEY) as client:
        for target in sys.argv[1:]:
            scan_path(client, target)
