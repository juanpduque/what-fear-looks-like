# Attributes gap (vision-gap run)

- Other layers finished at **65,201**
- Attributes stayed at **37,842** (seed only)
- Gap posters on disk: **27,359** — all failed
- Log: `skipped miss=0 fail=27359`
- Root cause: `AttributeError: module 'cv2' has no attribute 'saliency'`
  (EC2 OpenCV without opencv-contrib saliency used by attributes / multi_analyze)
- Chain still uploaded DONE after segmentation finished

## Fix
1. Install `opencv-contrib-python` on worker / userdata
2. Rerun attributes-only for ids in faces∖attributes (~27,359)
3. Gate DONE on attributes count matching peers
