#!/bin/bash
# EC2 UserData script for Rekognition backfill of 10,596 missing posters
#
# Launch with:
#   aws ec2 run-instances \
#     --image-id ami-0c7217cdde317cfec \
#     --instance-type t3.medium \
#     --iam-instance-profile Name=RekognitionS3Role \
#     --user-data file://rekognition_backfill_userdata.sh \
#     --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=rek-backfill}]'
#
# Requirements:
#   - IAM role with: rekognition:DetectLabels, rekognition:DetectModerationLabels,
#                    rekognition:DetectFaces, s3:GetObject, s3:PutObject
#   - S3 bucket: sagemaker-studio-a5572760

set -ex

# Config
BUCKET="sagemaker-studio-a5572760"
PREFIX="wflike-community-72k"
RESULTS_PREFIX="wflike-rek-backfill"
LOG="/var/log/rek_backfill.log"

exec > >(tee -a "$LOG") 2>&1
echo "=== Rekognition Backfill Started: $(date -Iseconds) ==="

# Install dependencies
apt-get update -qq
apt-get install -y -qq python3-pip
pip3 install -q boto3 pandas

# Create working directory
WORKDIR="/opt/rek_backfill"
mkdir -p "$WORKDIR/data"
cd "$WORKDIR"

# Download the backfill script from the repo or create inline
cat > backfill.py << 'PYEOF'
#!/usr/bin/env python3
"""Rekognition backfill - processes posters from S3 that lack analysis."""
import io, json, os, time
import boto3, pandas as pd
from botocore.exceptions import ClientError

S3_BUCKET = os.environ.get("S3_BUCKET", "sagemaker-studio-a5572760")
S3_PREFIX = os.environ.get("S3_PREFIX", "wflike-community-72k/posters")
RESULTS_PREFIX = os.environ.get("RESULTS_PREFIX", "wflike-rek-backfill")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")  # pragma: allowlist secret

WEAPON = {"weapon","blade","knife","dagger","sword","gun","handgun","rifle","axe","hatchet","bow","arrow","spear","mace","chainsaw"}
ANIMAL = {"animal","shark","fish","sea life","insect","bird","dog","cat","wolf","bear","snake","spider","bat","crow","raven","great white shark"}
PERSON = {"person","human","man","woman","boy","girl","adult","child","face","baby"}
WATER = {"water","ocean","sea","lake","beach","wave","underwater"}
FIRE = {"fire","flame","smoke","explosion"}
SILHOUETTE = {"silhouette"}

def _flag(labels, vocab):
    return round(max((c for n,c in labels if n.lower() in vocab), default=0.0), 4)

def _mod_score(mods, *names):
    want = {n.lower() for n in names}
    return round(max((c for n,c in mods if n.lower() in want), default=0.0), 4)

def analyze(rek, data):
    lab = rek.detect_labels(Image={"Bytes":data}, MaxLabels=20, MinConfidence=50,
                            Features=["GENERAL_LABELS","IMAGE_PROPERTIES"],
                            Settings={"ImageProperties":{"MaxDominantColors":5}})
    labels = [(l["Name"], l["Confidence"]/100) for l in lab.get("Labels",[])]
    n_boxes = sum(len(l.get("Instances") or []) for l in lab.get("Labels",[]))
    ip = lab.get("ImageProperties") or {}
    q = ip.get("Quality") or {}
    colors = "|".join(f"{c.get('HexCode','')}:{round(c.get('PixelPercent',0),1)}" 
                      for c in (ip.get("DominantColors") or [])[:5])
    label_s = "|".join(f"{n}:{c:.2f}" for n,c in labels[:10])
    
    mod = rek.detect_moderation_labels(Image={"Bytes":data}, MinConfidence=40)
    mods = [(m["Name"], m["Confidence"]/100) for m in mod.get("ModerationLabels",[])]
    mod_s = "|".join(f"{n}:{c:.2f}" for n,c in mods[:8])
    
    faces = rek.detect_faces(Image={"Bytes":data}, Attributes=["ALL"])
    details = faces.get("FaceDetails") or []
    emotion = gender = ""
    age_lo = age_hi = -1
    if details:
        details = sorted(details, key=lambda f: f["BoundingBox"]["Width"]*f["BoundingBox"]["Height"], reverse=True)
        f0 = details[0]
        emos = sorted(f0.get("Emotions") or [], key=lambda e: -e["Confidence"])
        if emos: emotion = f"{emos[0]['Type']}:{emos[0]['Confidence']/100:.2f}"
        gender = (f0.get("Gender") or {}).get("Value","")
        ar = f0.get("AgeRange") or {}
        age_lo, age_hi = int(ar.get("Low",-1)), int(ar.get("High",-1))
    
    top_n, top_c = (labels[0][0], labels[0][1]) if labels else ("", 0.0)
    return dict(
        rek_labels=label_s, rek_top=top_n, rek_top_conf=round(top_c,4),
        rek_weapon=_flag(labels,WEAPON), rek_animal=_flag(labels,ANIMAL),
        rek_person=_flag(labels,PERSON), rek_water=_flag(labels,WATER),
        rek_fire=_flag(labels,FIRE), rek_silhouette=_flag(labels,SILHOUETTE),
        rek_n_boxes=int(n_boxes), rek_bright=round(float(q.get("Brightness",0)),2),
        rek_sharp=round(float(q.get("Sharpness",0)),2), rek_contrast=round(float(q.get("Contrast",0)),2),
        rek_colors=colors, rek_mod=mod_s,
        rek_violence=_mod_score(mods,"Violence","Graphic Violence"),
        rek_mod_weapons=_mod_score(mods,"Weapons"),
        rek_gore=_mod_score(mods,"Visually Disturbing","Blood & Gore","Gore","Emaciated Bodies","Corpses","Hanging"),
        rek_n_faces=len(details), rek_emotion=emotion, rek_gender=gender,
        rek_age_lo=age_lo, rek_age_hi=age_hi
    )

def main():
    s3 = boto3.client("s3", region_name=REGION)
    rek = boto3.client("rekognition", region_name=REGION)
    
    print("Downloading manifest and existing results...")
    obj = s3.get_object(Bucket=S3_BUCKET, Key="wflike-community-72k/results/download_manifest.csv")
    manifest = pd.read_csv(io.BytesIO(obj["Body"].read()))
    downloaded = set(manifest[manifest["status"].isin(["ok","exists"])]["id"])
    
    obj = s3.get_object(Bucket=S3_BUCKET, Key="wflike-community-72k/results/rekognition_community_72k.csv")
    existing_s3 = set(pd.read_csv(io.BytesIO(obj["Body"].read()))["id"])
    
    # Check for partial results from previous runs
    partial_ids = set()
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=f"{RESULTS_PREFIX}/rekognition_backfill.csv")
        partial = pd.read_csv(io.BytesIO(obj["Body"].read()))
        partial_ids = set(partial["id"])
        print(f"Found {len(partial_ids)} already processed in partial results")
    except: pass
    
    missing = downloaded - existing_s3 - partial_ids
    print(f"Missing IDs to process: {len(missing)}")
    
    if not missing:
        print("Nothing to process!")
        # Upload DONE marker
        s3.put_object(Bucket=S3_BUCKET, Key=f"{RESULTS_PREFIX}/DONE", Body=b"")
        return
    
    # Get metadata
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key="wflike-community-72k/results/tmdb_horror_ids.csv")
        meta = pd.read_csv(io.BytesIO(obj["Body"].read()))
        meta = meta[meta["id"].isin(missing)][["id","title","year"]].set_index("id").to_dict("index")
    except:
        meta = {}
    
    rows = []
    errors = []
    t0 = time.time()
    
    for i, pid in enumerate(sorted(missing)):
        pid = int(pid)
        m = meta.get(pid, {})
        title, year = m.get("title",""), m.get("year",0)
        
        # Download poster
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=f"{S3_PREFIX}/{pid}.jpg")
            data = obj["Body"].read()
        except Exception as e:
            errors.append({"id":pid, "error":f"s3:{e}"})
            continue
        
        # Analyze
        try:
            feats = analyze(rek, data)
        except ClientError as e:
            code = e.response.get("Error",{}).get("Code","")
            if code in ("ThrottlingException","ProvisionedThroughputExceededException"):
                time.sleep(2)
                try: feats = analyze(rek, data)
                except: errors.append({"id":pid,"error":str(e)}); continue
            else:
                errors.append({"id":pid,"error":str(e)}); continue
        except Exception as e:
            errors.append({"id":pid,"error":str(e)}); continue
        
        rows.append(dict(id=pid, year=year, title=title, **feats))
        
        if len(rows) % 50 == 0:
            elapsed = time.time() - t0
            rate = len(rows) / max(elapsed, 0.001)
            eta = (len(missing) - i) / rate if rate > 0 else 0
            print(f"{len(rows)}/{len(missing)} | {rate:.1f}/s | ETA:{eta/60:.0f}m | {pid} {title[:30]}")
            
            # Save checkpoint
            df = pd.DataFrame(rows)
            csv_data = df.to_csv(index=False)
            s3.put_object(Bucket=S3_BUCKET, Key=f"{RESULTS_PREFIX}/rekognition_backfill.csv", 
                         Body=csv_data.encode())
            s3.put_object(Bucket=S3_BUCKET, Key=f"{RESULTS_PREFIX}/progress.json",
                         Body=json.dumps({"processed":len(rows),"errors":len(errors),
                                         "total":len(missing),"rate":round(rate,2),
                                         "ts":time.strftime("%Y-%m-%dT%H:%M:%SZ")}).encode())
    
    # Final save
    if rows:
        df = pd.DataFrame(rows)
        csv_data = df.to_csv(index=False)
        s3.put_object(Bucket=S3_BUCKET, Key=f"{RESULTS_PREFIX}/rekognition_backfill.csv", Body=csv_data.encode())
    
    if errors:
        s3.put_object(Bucket=S3_BUCKET, Key=f"{RESULTS_PREFIX}/errors.json", 
                     Body=json.dumps(errors).encode())
    
    s3.put_object(Bucket=S3_BUCKET, Key=f"{RESULTS_PREFIX}/DONE", Body=b"")
    print(f"DONE: {len(rows)} processed, {len(errors)} errors in {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
PYEOF

# Run the backfill
python3 backfill.py

echo "=== Rekognition Backfill Completed: $(date -Iseconds) ==="

# Self-terminate (optional - comment out for debugging)
# shutdown -h now
