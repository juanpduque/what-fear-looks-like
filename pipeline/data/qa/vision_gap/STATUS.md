# Vision gap EC2

{
  "updated_at": "2026-08-05T01:17:53Z",
  "instance_id": "i-07b62870cc441c343",
  "public_ip": "3.83.143.122",
  "region": "us-east-1",
  "instance_type": "c5.9xlarge",
  "duplicate_terminated": "i-0f7435c5b73f5b39b",
  "s3": "s3://sagemaker-studio-a5572760/wflike-vision-gap/",
  "n_todo_per_layer": {
    "faces_v2": 27359,
    "census": 27359,
    "attributes": 27359,
    "segmentation": 27359,
    "typography": 27359,
    "medium": 27359,
    "clip_embeddings": 27359
  },
  "todo_breakdown": {
    "union": 27359,
    "local_community": 11717,
    "s3_only": 15642,
    "must_upload_from_mac": 1133
  },
  "pipelines": [
    "faces_v2",
    "attributes",
    "clip_embeddings",
    "census",
    "typography",
    "medium",
    "segmentation"
  ],
  "medium": "clip_medium.py canonical medium.csv",
  "monitor": {
    "progress": "AWS_PROFILE=sandbox aws s3 cp s3://sagemaker-studio-a5572760/wflike-vision-gap/results/PROGRESS.json -",
    "log": "AWS_PROFILE=sandbox aws s3 cp s3://sagemaker-studio-a5572760/wflike-vision-gap/results/vision_gap_aws.log - | tail -100",
    "ls": "AWS_PROFILE=sandbox aws s3 ls s3://sagemaker-studio-a5572760/wflike-vision-gap/results/",
    "ec2": "AWS_PROFILE=sandbox aws ec2 describe-instances --instance-ids i-07b62870cc441c343 --query 'Reservations[0].Instances[0].[State.Name,PublicIpAddress]' --output text",
    "pull": "AWS_PROFILE=sandbox bash pipeline/aws/pull_vision_gap.sh"
  },
  "blockers": [
    {
      "item": "GPU sandbox",
      "why": "G/VT On-Demand vCPU quota=0",
      "status": "blocked; using c5.9xlarge CPU"
    },
    {
      "item": "Custom Labels inference",
      "why": "TRAINING_COMPLETED F1=0.645 but not RUNNING; StartProjectVersion costs inference units; schema \u2260 medium.csv",
      "status": "skipped; clip_medium used"
    },
    {
      "item": "U without poster",
      "why": "4649 ids in U=68011 lack poster local\u222aS3",
      "status": "out of scope"
    },
    {
      "item": "AOF GPU cross-account",
      "why": "posters in sandbox S3; OWL family left untouched; no cross-account stage",
      "status": "not used"
    }
  ],
  "eta_hours_rough": "12\u201318 (seg dominates on CPU)"
}
