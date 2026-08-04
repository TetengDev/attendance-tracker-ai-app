# Face Recognition & Anti-Spoofing Models

This directory contains the ONNX weights for the face detection, recognition, and liveness models. 
Under the project's strict privacy policy and model-vending rules, these large weights are git-ignored and fetched programmatically via `infra/fetch_models.sh`.

## Model Details

### 1. Face Detection (SCRFD)
* **Model File**: `det_10g.onnx`
* **Architecture**: SCRFD-10G (Sample-and-Filter ResNet Face Detector)
* **License**: Non-commercial research use only (buffalo_l model pack).

### 2. Face Embedding (ArcFace)
* **Model File**: `w600k_r50.onnx`
* **Architecture**: ResNet-50 ArcFace
* **License**: Non-commercial research use only (buffalo_l model pack).

### 3. Face Anti-Spoofing (MiniFASNet)
* **Model Files**:
  - `2.7_80x80_MiniFASNetV2.onnx` (Scale 2.7 crop)
  - `4_0_0_80x80_MiniFASNetV1SE.onnx` (Scale 4.0 crop)
* **Architecture**: MiniFASNet
* **License**: Apache-2.0.
* **Why**: Dual-model ensemble to classify inputs into `live`, `print-attack`, and `replay-attack` classes.

## Fetching the models

Run the following command to download and verify the models:
```bash
bash infra/fetch_models.sh
```
